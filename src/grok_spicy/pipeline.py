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
    with open("output/state.json", "w") as f:
        f.write(state.model_dump_json(indent=2))


def _notify(observer: PipelineObserver, method: str, *args: object) -> None:
    """Fire-and-forget observer call — never crash the pipeline."""
    try:
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
                found = True
                break
        if not found:
            unmatched_refs[ref_label] = ref_path

    if not unmatched_refs:
        return matched

    # Phase 2: LLM fallback matching
    unmatched_char_names = char_names - set(matched.keys())
    if not unmatched_char_names:
        return matched

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

        chat = client.chat.create(model=MODEL_STRUCTURED)
        chat.append(
            user(
                f"Map these uploaded reference image labels to story characters.\n"
                f"Uploaded labels: {list(unmatched_refs.keys())}\n"
                f"Characters: {char_info}\n"
                f"Return a mapping from each label to the best-matching character name."
            )
        )
        _, result = chat.parse(CharacterRefMapping)
        for label, char_name in result.mapping.items():
            if label in unmatched_refs and char_name in unmatched_char_names:
                matched[char_name] = unmatched_refs[label]
    except Exception:
        logger.warning("LLM character ref matching failed", exc_info=True)

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

    run_id = observer.on_run_start(concept)

    try:
        # ═══ STEP 1: IDEATION ═══
        print("=== STEP 1: Planning story ===")
        ideation_concept = concept
        if character_refs:
            names = ", ".join(character_refs.keys())
            ideation_concept += (
                f"\nThe user has provided reference images for these characters: "
                f"{names}. Use these exact names for the corresponding characters."
            )
        plan = plan_story(ideation_concept)
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
            print(
                f"  {c.name}: score={c.consistency_score:.2f}, "
                f"attempts={c.generation_attempts}"
            )
            _notify(observer, "on_character", run_id, c)

        # ═══ STEP 3: KEYFRAMES (sequential for frame chaining) ═══
        print("=== STEP 3: Keyframes ===")
        keyframes = []
        prev_url = None
        for scene in plan.scenes:
            kf = compose_keyframe(scene, plan, char_map, prev_url)
            keyframes.append(kf)
            prev_url = kf.keyframe_url
            print(
                f"  Scene {scene.scene_id}: score={kf.consistency_score:.2f}, "
                f"edits={kf.edit_passes}"
            )
            _notify(observer, "on_keyframe", run_id, kf)

        # ═══ STEP 4: SCRIPT ═══
        print("=== STEP 4: Script ===")
        script = compile_script(plan, characters, keyframes)
        print(f"-> {script}")
        _notify(observer, "on_script", run_id, script)

        # Save intermediate state
        state = PipelineState(plan=plan, characters=characters, keyframes=keyframes)
        _save_state(state)

        # ═══ STEP 5: VIDEOS (sequential) ═══
        print("=== STEP 5: Videos ===")
        videos = []
        for scene, kf in zip(plan.scenes, keyframes, strict=True):
            v = generate_scene_video(kf, scene, char_map)
            videos.append(v)
            print(
                f"  Scene {scene.scene_id}: score={v.consistency_score:.2f}, "
                f"corrections={v.correction_passes}"
            )
            _notify(observer, "on_video", run_id, v)

        # ═══ STEP 6: ASSEMBLY ═══
        print("=== STEP 6: Assembly ===")
        final = assemble_final_video(videos)
        print(f"-> {final}")

        # Save final state
        state.videos = videos
        state.final_video_path = final
        _save_state(state)

        _notify(observer, "on_complete", run_id, final)

        return final

    except Exception as exc:
        _notify(observer, "on_error", run_id, str(exc))
        raise
