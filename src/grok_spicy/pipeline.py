"""Prefect flow — main pipeline orchestration."""

from __future__ import annotations

import logging
import os

from prefect import flow

from grok_spicy.client import download
from grok_spicy.observer import NullObserver, PipelineObserver
from grok_spicy.schemas import (
    Character,
    PipelineConfig,
    PipelineState,
    VideoConfig,
)
from grok_spicy.tasks.assembly import assemble_final_video
from grok_spicy.tasks.characters import generate_character_sheet
from grok_spicy.tasks.keyframes import compose_keyframe
from grok_spicy.tasks.script import compile_script
from grok_spicy.tasks.video import generate_scene_video

# Note: tasks/ideation.py is no longer used — story plans come from video.json.

logger = logging.getLogger(__name__)


def _save_state(state: PipelineState, run_dir: str = "output") -> None:
    """Persist pipeline state to {run_dir}/state.json."""
    os.makedirs(run_dir, exist_ok=True)
    path = f"{run_dir}/state.json"
    with open(path, "w", encoding="utf-8") as f:
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
    character_refs: dict[str, list[str]],
    characters: list[Character],
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Map uploaded reference names to generated character names.

    Returns {Character.name: [file_path, ...]} for matched characters.
    """
    if not character_refs:
        logger.debug("No character references to match")
        return {}

    char_names = {c.name for c in characters}
    matched: dict[str, list[str]] = {}

    # Phase 1: exact match (case-insensitive)
    unmatched_refs: dict[str, list[str]] = {}
    for ref_label, ref_paths in character_refs.items():
        found = False
        for cname in char_names:
            if ref_label.lower() == cname.lower():
                matched[cname] = ref_paths
                logger.info(
                    "Ref match (exact): label=%r → character=%r (%d images)",
                    ref_label,
                    cname,
                    len(ref_paths),
                )
                found = True
                break
        if not found:
            unmatched_refs[ref_label] = ref_paths
            logger.debug("Ref label %r had no exact match", ref_label)

    logger.info(
        "Phase 1 ref matching: %d exact, %d unmatched",
        len(matched),
        len(unmatched_refs),
    )

    if not unmatched_refs:
        return matched

    # Phase 2: substring matching (cheap heuristic before LLM)
    unmatched_char_names = char_names - set(matched.keys())
    still_unmatched: dict[str, list[str]] = {}
    for ref_label, ref_paths in unmatched_refs.items():
        found = False
        for cname in unmatched_char_names:
            if ref_label.lower() in cname.lower() or cname.lower() in ref_label.lower():
                matched[cname] = ref_paths
                logger.info(
                    "Ref match (substring): label=%r → character=%r",
                    ref_label,
                    cname,
                )
                found = True
                break
        if not found:
            still_unmatched[ref_label] = ref_paths

    if not still_unmatched:
        logger.info("All refs matched after substring phase")
        return matched

    # Phase 3: LLM fallback matching (with retry)
    unmatched_char_names = char_names - set(matched.keys())
    if not unmatched_char_names:
        logger.debug("All character names already matched, skipping LLM fallback")
        return matched

    if dry_run:
        logger.info("Dry-run: skipping LLM fallback for ref matching")
        return matched

    logger.info(
        "Phase 3: LLM fallback matching %d refs → %d characters",
        len(still_unmatched),
        len(unmatched_char_names),
    )
    max_llm_attempts = 2
    for attempt in range(1, max_llm_attempts + 1):
        try:
            from grok_spicy.client import MODEL_STRUCTURED, get_client
            from grok_spicy.schemas import CharacterRefMapping

            client = get_client()
            # Include visual_description snippets for better matching context
            char_info = [
                {
                    "name": c.name,
                    "role": c.role,
                    "description_snippet": c.visual_description[:120],
                }
                for c in characters
                if c.name in unmatched_char_names
            ]
            from xai_sdk.chat import user

            ref_match_prompt = (
                f"Map these uploaded reference image labels to story characters.\n"
                f"Uploaded labels: {list(still_unmatched.keys())}\n"
                f"Characters: {char_info}\n"
                f"Return a mapping from each label to the best-matching character name."
            )
            logger.info(
                "LLM ref-matching prompt (attempt %d): %s", attempt, ref_match_prompt
            )
            chat = client.chat.create(model=MODEL_STRUCTURED)
            chat.append(user(ref_match_prompt))
            _, result = chat.parse(CharacterRefMapping)
            for label, char_name in result.mapping.items():
                if label in still_unmatched and char_name in unmatched_char_names:
                    matched[char_name] = still_unmatched[label]
                    logger.info(
                        "Ref match (LLM): label=%r → character=%r", label, char_name
                    )
            break  # Success — exit retry loop
        except Exception:
            logger.warning(
                "LLM character ref matching attempt %d/%d failed",
                attempt,
                max_llm_attempts,
                exc_info=True,
            )

    # Warn about any refs that remain unmatched after all phases
    final_matched_paths = set()
    for paths in matched.values():
        final_matched_paths.update(paths)
    for ref_label, ref_paths in character_refs.items():
        for ref_path in ref_paths:
            if ref_path not in final_matched_paths:
                logger.warning(
                    "Reference image %r (%s) could not be matched to any character",
                    ref_label,
                    ref_path,
                )

    logger.info("Final ref matching result: %d matched total", len(matched))
    return matched


@flow(
    name="grok-video-pipeline",
    log_prints=True,
)
def video_pipeline(
    video_config: VideoConfig,
    observer: PipelineObserver | None = None,
    character_refs: dict[str, list[str]] | None = None,
    config: PipelineConfig | None = None,
) -> str:
    """End-to-end video generation pipeline.

    All input comes from video_config (loaded from video.json).
    The story_plan field defines characters and scenes explicitly —
    no LLM ideation step.
    """
    if config is None:
        config = PipelineConfig()
    if observer is None:
        observer = NullObserver()
    if character_refs is None:
        character_refs = {}

    if video_config.story_plan is None:
        raise ValueError(
            "video_config.story_plan is required — define a story_plan "
            "section in video.json with title, style, characters, and scenes."
        )

    concept = video_config.story_plan.title
    logger.info("Pipeline started — title=%r, refs=%d", concept, len(character_refs))
    logger.info(
        "Config — v%s, intensity=%s, %d config characters, %d modifiers",
        video_config.version,
        video_config.spicy_mode.intensity,
        len(video_config.characters),
        len(video_config.spicy_mode.enabled_modifiers),
    )
    print(
        f"=== CONFIG: intensity={video_config.spicy_mode.intensity}, "
        f"characters={len(video_config.characters)} ==="
    )

    # Resolve config character images and merge into character_refs.
    import uuid

    from grok_spicy.config import resolve_character_images

    staging_id = uuid.uuid4().hex[:8]
    resolved_images = resolve_character_images(video_config)
    for cfg_char in video_config.characters:
        imgs = resolved_images.get(cfg_char.id, [])
        if imgs and cfg_char.name not in character_refs:
            # Take up to 3 reference images per character
            paths: list[str] = []
            for idx, img_src in enumerate(imgs[:3]):
                if not img_src.startswith(("http://", "https://")):
                    paths.append(img_src)
                    logger.info(
                        "Config: added local ref image for %r [%d]: %s",
                        cfg_char.name,
                        idx,
                        img_src,
                    )
                elif not config.dry_run:
                    safe = cfg_char.name.replace(" ", "_")
                    dest = f"output/staging/{staging_id}/references/{safe}_config_{idx}.jpg"
                    try:
                        download(img_src, dest)
                        paths.append(dest)
                        logger.info(
                            "Config: downloaded ref image for %r [%d]: %s",
                            cfg_char.name,
                            idx,
                            dest,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to download config image for %r [%d]: %s",
                            cfg_char.name,
                            idx,
                            img_src,
                            exc_info=True,
                        )
            if paths:
                character_refs[cfg_char.name] = paths

    run_id = observer.on_run_start(concept)
    logger.info("Run ID assigned: %d", run_id)

    # ═══ COMPUTE PER-RUN DIRECTORY ═══
    if run_id > 0:
        # Web runs: use DB run_id
        config.run_dir = f"output/runs/{run_id}"
    else:
        # CLI runs: use ISO timestamp
        from datetime import UTC, datetime

        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        config.run_dir = f"output/runs/{ts}"
    os.makedirs(config.run_dir, exist_ok=True)
    logger.info("Run directory: %s", config.run_dir)

    # Relocate staging references into run directory
    if character_refs:
        run_refs_dir = f"{config.run_dir}/references"
        os.makedirs(run_refs_dir, exist_ok=True)
        import shutil

        updated_refs: dict[str, list[str]] = {}
        for ref_name, ref_paths in character_refs.items():
            new_paths: list[str] = []
            for ref_path in ref_paths:
                dest = os.path.join(run_refs_dir, os.path.basename(ref_path))
                if os.path.isfile(ref_path):
                    shutil.copy2(ref_path, dest)
                    new_paths.append(dest)
                    logger.debug(
                        "Relocated ref %r: %s → %s", ref_name, ref_path, dest
                    )
                else:
                    new_paths.append(ref_path)
                    logger.debug(
                        "Ref %r path not found, keeping: %s", ref_name, ref_path
                    )
            updated_refs[ref_name] = new_paths
        character_refs = updated_refs

    try:
        # ═══ PLAN FROM CONFIG (no ideation) ═══
        plan = video_config.story_plan  # type: ignore[assignment]  # validated above
        logger.info(
            "Plan loaded from config: title=%r, characters=%d, scenes=%d, "
            "style=%r, aspect=%s",
            plan.title,
            len(plan.characters),
            len(plan.scenes),
            plan.style,
            plan.aspect_ratio,
        )
        print(
            f"-> {plan.title}: {len(plan.characters)} chars, "
            f"{len(plan.scenes)} scenes"
        )
        _notify(observer, "on_plan", run_id, plan)

        # Merge spicy_traits from config characters into plan characters
        for char in plan.characters:
            for cfg_char in video_config.characters:
                if char.name == cfg_char.name and cfg_char.spicy_traits:
                    char.spicy_traits = cfg_char.spicy_traits
                    break

        # Match uploaded reference names to plan character names
        matched_refs = _match_character_refs(
            character_refs, plan.characters, dry_run=config.dry_run
        )
        if matched_refs:
            print(f"  Ref images matched: {list(matched_refs.keys())}")

        # ═══ STYLE OVERRIDE ═══
        plan.style = config.effective_style(plan.style)

        # ═══ DEBUG MODE: trim to 1 scene ═══
        if config.debug and len(plan.scenes) > 1:
            logger.info("DEBUG MODE: trimming scenes from %d to 1", len(plan.scenes))
            print("** DEBUG MODE: using only 1 scene **")
            plan.scenes = plan.scenes[:1]
            # Keep only characters present in the remaining scene
            keep = set(plan.scenes[0].characters_present)
            plan.characters = [c for c in plan.characters if c.name in keep]
            logger.info(
                "DEBUG MODE: kept %d character(s): %s",
                len(plan.characters),
                [c.name for c in plan.characters],
            )

        # ═══ DURATION CLAMPING ═══
        for scene in plan.scenes:
            clamped = min(scene.duration_seconds, config.max_duration)
            if clamped != scene.duration_seconds:
                logger.info(
                    "Clamping scene %d duration: %ds → %ds (max_duration=%d)",
                    scene.scene_id,
                    scene.duration_seconds,
                    clamped,
                    config.max_duration,
                )
                scene.duration_seconds = clamped

        # ═══ STEP 2: CHARACTER SHEETS (parallel) ═══
        # INVARIANT: character.visual_description is NEVER mutated after
        # ideation.  Spicy traits live in character.spicy_traits and are
        # injected at the prompt level only (character_*_prompt functions
        # use a local `desc` copy).  This keeps the canonical description
        # clean for DB writes, vision checks, keyframes, and script output.
        # Violating this invariant corrupts the DB (bug #6).
        #
        # Enhancement mode (Case 3): when a config character has both
        # images and a description, the description is passed as
        # `enhancements` for a two-pass generation (base + enhance).
        logger.info("STEP 2: Character sheets — generating %d", len(plan.characters))
        print("=== STEP 2: Character sheets ===")

        # Build {char_name: enhancement_text_or_None} lookup
        _enhancements: dict[str, str | None] = {}
        for c in plan.characters:
            cfg_char = next(
                (sc for sc in video_config.characters if sc.name == c.name), None
            )
            if cfg_char and cfg_char.images and cfg_char.description:
                _enhancements[c.name] = cfg_char.description
                logger.info(
                    "Character %r: Case 3 (images + description) — enhancement mode",
                    c.name,
                )
            else:
                _enhancements[c.name] = None

        char_futures = [
            generate_character_sheet.submit(
                c,
                plan.style,
                plan.aspect_ratio,
                reference_image_paths=matched_refs.get(c.name),
                enhancements=_enhancements.get(c.name),
                config=config,
                video_config=video_config,
            )
            for c in plan.characters
        ]
        characters = [f.result() for f in char_futures]
        char_map = {ca.name: ca for ca in characters}
        for ca in characters:
            logger.info(
                "STEP 2 result: %s — score=%.2f, attempts=%d, path=%s",
                ca.name,
                ca.consistency_score,
                ca.generation_attempts,
                ca.portrait_path,
            )
            print(
                f"  {ca.name}: score={ca.consistency_score:.2f}, "
                f"attempts={ca.generation_attempts}"
            )
            _notify(observer, "on_character", run_id, ca)

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
            kf = compose_keyframe(
                scene,
                plan,
                char_map,
                prev_url,
                config=config,
                video_config=video_config,
            )
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
        script = compile_script(plan, characters, keyframes, run_dir=config.run_dir)
        logger.info("STEP 4 complete: script=%s", script)
        print(f"-> {script}")
        _notify(observer, "on_script", run_id, script)

        # Save intermediate state (with resumability metadata)
        state = PipelineState(
            plan=plan,
            characters=characters,
            keyframes=keyframes,
            run_id=run_id,
            config=config,
            video_config=video_config,
            character_refs=character_refs or {},
            matched_refs=matched_refs,
        )
        _save_state(state, run_dir=config.run_dir)

        # ═══ STEP 5: VIDEOS (sequential) ═══
        logger.info("STEP 5: Video generation — %d scenes", len(plan.scenes))
        print("=== STEP 5: Videos ===")
        videos = []
        for scene, kf in zip(plan.scenes, keyframes, strict=True):
            tier = (
                "standard (correction eligible)"
                if scene.duration_seconds <= 8
                else "extended (no correction)"
            )
            logger.debug(
                "Generating video for scene %d, duration=%ds, tier=%s",
                scene.scene_id,
                scene.duration_seconds,
                tier,
            )
            _notify(
                observer,
                "on_video_start",
                run_id,
                scene.scene_id,
                scene.duration_seconds,
                tier,
            )
            v = generate_scene_video(
                kf,
                scene,
                char_map,
                config=config,
                video_config=video_config,
            )
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
        if config.dry_run:
            logger.info("STEP 6: Skipped (dry-run)")
            print("=== STEP 6: Assembly (skipped — dry-run) ===")

            # Collect all prompt files and write summary
            import glob as globmod

            from grok_spicy.dry_run import write_summary

            prompts_dir = os.path.join(config.run_dir, "prompts")
            prompt_files = sorted(
                globmod.glob(os.path.join(prompts_dir, "**", "*.md"), recursive=True)
            )
            summary_path = write_summary(prompt_files, run_dir=config.run_dir)
            logger.info("Dry-run summary written to %s", summary_path)
            print(f"-> Summary: {summary_path}")

            # Save state (with placeholder paths)
            state.videos = videos
            _save_state(state, run_dir=config.run_dir)

            _notify(observer, "on_complete", run_id, summary_path)
            return summary_path
        else:
            logger.info("STEP 6: Assembly — %d clips", len(videos))
            print("=== STEP 6: Assembly ===")
            final = assemble_final_video(videos, run_dir=config.run_dir)
            logger.info("STEP 6 complete: final_video=%s", final)
            print(f"-> {final}")

            # Save final state
            state.videos = videos
            state.final_video_path = final
            _save_state(state, run_dir=config.run_dir)

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
