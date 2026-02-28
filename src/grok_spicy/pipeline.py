"""Prefect flow — main pipeline orchestration."""

from __future__ import annotations

import logging
import os

from prefect import flow

from grok_spicy.observer import NullObserver, PipelineObserver
from grok_spicy.schemas import Character, PipelineState
from grok_spicy.tasks.assembly import assemble_final_video
from grok_spicy.tasks.characters import generate_character_sheet
from grok_spicy.tasks.ideation import plan_story
from grok_spicy.tasks.keyframes import compose_keyframe
from grok_spicy.tasks.script import compile_script
from grok_spicy.tasks.video import generate_scene_video

logger = logging.getLogger(__name__)


def _save_state(state: PipelineState) -> None:
    """Persist pipeline state to output/state.json."""
    os.makedirs("output", exist_ok=True)
    path = "output/state.json"
    with open(path, "w") as f:
        f.write(state.model_dump_json(indent=2))
    logger.debug("Pipeline state saved to %s", path)


def _notify(observer: PipelineObserver, method: str, *args: object) -> None:
    """Fire-and-forget observer call — never crash the pipeline."""
    try:
        logger.debug("Notifying observer: %s", method)
        getattr(observer, method)(*args)
    except Exception:
        logger.warning("Observer.%s failed", method, exc_info=True)


def _match_character_refs(
    character_refs: dict[str, str],
    characters: list[Character],
) -> dict[str, str]:
    """Map uploaded reference names to generated character names.

    Returns {Character.name: file_path} for matched characters.
    """
    if not character_refs:
        logger.debug("No character references to match")
        return {}

    char_names = {c.name for c in characters}
    matched: dict[str, str] = {}

    # Phase 1: exact match (case-insensitive)
    unmatched_refs: dict[str, str] = {}
    for ref_label, ref_path in character_refs.items():
        found = False
        for cname in char_names:
            if ref_label.lower() == cname.lower():
                matched[cname] = ref_path
                logger.info(
                    "Ref match (exact): label=%r → character=%r", ref_label, cname
                )
                found = True
                break
        if not found:
            unmatched_refs[ref_label] = ref_path
            logger.debug("Ref label %r had no exact match", ref_label)

    logger.info(
        "Phase 1 ref matching: %d exact, %d unmatched",
        len(matched),
        len(unmatched_refs),
    )

    if not unmatched_refs:
        return matched

    # Phase 2: LLM fallback matching
    unmatched_char_names = char_names - set(matched.keys())
    if not unmatched_char_names:
        logger.debug("All character names already matched, skipping LLM fallback")
        return matched

    logger.info(
        "Phase 2: LLM fallback matching %d refs → %d characters",
        len(unmatched_refs),
        len(unmatched_char_names),
    )
    try:
        from grok_spicy.client import MODEL_STRUCTURED, get_client
        from grok_spicy.schemas import CharacterRefMapping

        client = get_client()
        char_info = [
            {"name": c.name, "role": c.role}
            for c in characters
            if c.name in unmatched_char_names
        ]
        from xai_sdk.chat import user

        ref_match_prompt = (
            f"Map these uploaded reference image labels to story characters.\n"
            f"Uploaded labels: {list(unmatched_refs.keys())}\n"
            f"Characters: {char_info}\n"
            f"Return a mapping from each label to the best-matching character name."
        )
        logger.info("LLM ref-matching prompt: %s", ref_match_prompt)
        chat = client.chat.create(model=MODEL_STRUCTURED)
        chat.append(user(ref_match_prompt))
        _, result = chat.parse(CharacterRefMapping)
        for label, char_name in result.mapping.items():
            if label in unmatched_refs and char_name in unmatched_char_names:
                matched[char_name] = unmatched_refs[label]
                logger.info(
                    "Ref match (LLM): label=%r → character=%r", label, char_name
                )
    except Exception:
        logger.warning("LLM character ref matching failed", exc_info=True)

    logger.info("Final ref matching result: %d matched total", len(matched))
    return matched


@flow(
    name="grok-video-pipeline",
    retries=1,
    retry_delay_seconds=60,
    log_prints=True,
)
def video_pipeline(
    concept: str,
    observer: PipelineObserver | None = None,
    character_refs: dict[str, str] | None = None,
) -> str:
    """End-to-end video generation pipeline.

    Takes a concept string and produces a final assembled video.
    """
    if observer is None:
        observer = NullObserver()
    if character_refs is None:
        character_refs = {}

    logger.info("Pipeline started — concept=%r, refs=%d", concept, len(character_refs))

    run_id = observer.on_run_start(concept)
    logger.info("Run ID assigned: %d", run_id)

    try:
        # ═══ STEP 1: IDEATION ═══
        logger.info("STEP 1: Ideation — generating story plan")
        print("=== STEP 1: Planning story ===")
        ideation_concept = concept
        if character_refs:
            names = ", ".join(character_refs.keys())
            ideation_concept += (
                f"\nThe user has provided reference images for these characters: "
                f"{names}. Use these exact names for the corresponding characters."
            )
            logger.debug("Ideation concept augmented with ref names: %s", names)
        plan = plan_story(ideation_concept)
        logger.info(
            "STEP 1 complete: title=%r, characters=%d, scenes=%d, "
            "style=%r, aspect=%s",
            plan.title,
            len(plan.characters),
            len(plan.scenes),
            plan.style,
            plan.aspect_ratio,
        )
        for c in plan.characters:
            logger.debug(
                "Character planned: name=%r, role=%r, visual_desc_len=%d",
                c.name,
                c.role,
                len(c.visual_description),
            )
        for s in plan.scenes:
            logger.debug(
                "Scene planned: id=%d, title=%r, chars=%s, duration=%ds",
                s.scene_id,
                s.title,
                s.characters_present,
                s.duration_seconds,
            )
        print(
            f"-> {plan.title}: {len(plan.characters)} chars, "
            f"{len(plan.scenes)} scenes"
        )
        _notify(observer, "on_plan", run_id, plan)

        # Match uploaded reference names to generated character names
        matched_refs = _match_character_refs(character_refs, plan.characters)
        if matched_refs:
            print(f"  Ref images matched: {list(matched_refs.keys())}")

        # ═══ STEP 2: CHARACTER SHEETS (parallel) ═══
        logger.info("STEP 2: Character sheets — generating %d", len(plan.characters))
        print("=== STEP 2: Character sheets ===")
        char_futures = [
            generate_character_sheet.submit(
                c,
                plan.style,
                plan.aspect_ratio,
                reference_image_path=matched_refs.get(c.name),
            )
            for c in plan.characters
        ]
        characters = [f.result() for f in char_futures]
        char_map = {c.name: c for c in characters}
        for c in characters:
            logger.info(
                "STEP 2 result: %s — score=%.2f, attempts=%d, path=%s",
                c.name,
                c.consistency_score,
                c.generation_attempts,
                c.portrait_path,
            )
            print(
                f"  {c.name}: score={c.consistency_score:.2f}, "
                f"attempts={c.generation_attempts}"
            )
            _notify(observer, "on_character", run_id, c)

        # ═══ STEP 3: KEYFRAMES (sequential for frame chaining) ═══
        logger.info("STEP 3: Keyframes — generating %d", len(plan.scenes))
        print("=== STEP 3: Keyframes ===")
        keyframes = []
        prev_url = None
        for scene in plan.scenes:
            logger.debug(
                "Composing keyframe for scene %d, prev_url=%s",
                scene.scene_id,
                "yes" if prev_url else "none",
            )
            kf = compose_keyframe(scene, plan, char_map, prev_url)
            keyframes.append(kf)
            prev_url = kf.keyframe_url
            logger.info(
                "STEP 3 result: scene %d — score=%.2f, edits=%d, path=%s",
                scene.scene_id,
                kf.consistency_score,
                kf.edit_passes,
                kf.keyframe_path,
            )
            print(
                f"  Scene {scene.scene_id}: score={kf.consistency_score:.2f}, "
                f"edits={kf.edit_passes}"
            )
            _notify(observer, "on_keyframe", run_id, kf)

        # ═══ STEP 4: SCRIPT ═══
        logger.info("STEP 4: Script compilation")
        print("=== STEP 4: Script ===")
        script = compile_script(plan, characters, keyframes)
        logger.info("STEP 4 complete: script=%s", script)
        print(f"-> {script}")
        _notify(observer, "on_script", run_id, script)

        # Save intermediate state
        state = PipelineState(plan=plan, characters=characters, keyframes=keyframes)
        _save_state(state)

        # ═══ STEP 5: VIDEOS (sequential) ═══
        logger.info("STEP 5: Video generation — %d scenes", len(plan.scenes))
        print("=== STEP 5: Videos ===")
        videos = []
        for scene, kf in zip(plan.scenes, keyframes, strict=True):
            logger.debug(
                "Generating video for scene %d, duration=%ds",
                scene.scene_id,
                scene.duration_seconds,
            )
            v = generate_scene_video(kf, scene, char_map)
            videos.append(v)
            logger.info(
                "STEP 5 result: scene %d — score=%.2f, corrections=%d, path=%s",
                scene.scene_id,
                v.consistency_score,
                v.correction_passes,
                v.video_path,
            )
            print(
                f"  Scene {scene.scene_id}: score={v.consistency_score:.2f}, "
                f"corrections={v.correction_passes}"
            )
            _notify(observer, "on_video", run_id, v)

        # ═══ STEP 6: ASSEMBLY ═══
        logger.info("STEP 6: Assembly — %d clips", len(videos))
        print("=== STEP 6: Assembly ===")
        final = assemble_final_video(videos)
        logger.info("STEP 6 complete: final_video=%s", final)
        print(f"-> {final}")

        # Save final state
        state.videos = videos
        state.final_video_path = final
        _save_state(state)

        _notify(observer, "on_complete", run_id, final)

        logger.info(
            "Pipeline finished successfully — run_id=%d, output=%s", run_id, final
        )
        return final

    except Exception as exc:
        logger.error(
            "Pipeline failed — run_id=%d, error=%s", run_id, exc, exc_info=True
        )
        _notify(observer, "on_error", run_id, str(exc))
        raise
