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
    StoryPlan,
    VideoConfig,
)
from grok_spicy.tasks.assembly import assemble_final_video
from grok_spicy.tasks.characters import generate_character_sheet
from grok_spicy.tasks.describe_ref import describe_reference_image
from grok_spicy.tasks.ideation import plan_story
from grok_spicy.tasks.keyframes import compose_keyframe
from grok_spicy.tasks.script import compile_script
from grok_spicy.tasks.video import generate_scene_video

logger = logging.getLogger(__name__)


def _enrich_characters_from_config(plan: StoryPlan, video_config: VideoConfig) -> None:
    """Merge spicy config traits/modifiers into plan characters (in-place).

    For each plan character whose name matches a config character, append
    spicy traits and global modifiers to their visual_description.
    """
    cfg_chars = {c.name.lower(): c for c in video_config.characters}
    modifiers = video_config.spicy_mode.enabled_modifiers

    for char in plan.characters:
        cfg_char = cfg_chars.get(char.name.lower())
        extras: list[str] = []
        if cfg_char and cfg_char.spicy_traits:
            extras.extend(cfg_char.spicy_traits)
            logger.info(
                "Enriching character %r with spicy traits: %s",
                char.name,
                cfg_char.spicy_traits,
            )
        if modifiers:
            extras.extend(modifiers)
        if extras:
            char.visual_description = f"{char.visual_description}, {', '.join(extras)}"
            logger.debug(
                "Enriched visual_description for %r (%d chars)",
                char.name,
                len(char.visual_description),
            )


def _save_state(state: PipelineState) -> None:
    """Persist pipeline state to output/state.json."""
    os.makedirs("output", exist_ok=True)
    path = "output/state.json"
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
    character_refs: dict[str, str],
    characters: list[Character],
    dry_run: bool = False,
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

    if dry_run:
        logger.info("Dry-run: skipping LLM fallback for ref matching")
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
    config: PipelineConfig | None = None,
    script_plan: StoryPlan | None = None,
    video_config: VideoConfig | None = None,
    # Deprecated kwargs — kept for backward compat (web.py, tests)
    debug: bool = False,
    max_duration: int = 15,
) -> str:
    """End-to-end video generation pipeline.

    Takes a concept string and produces a final assembled video.
    """
    if config is None:
        config = PipelineConfig(debug=debug, max_duration=max_duration)
    if observer is None:
        observer = NullObserver()
    if character_refs is None:
        character_refs = {}

    logger.info("Pipeline started — concept=%r, refs=%d", concept, len(character_refs))
    if video_config is not None:
        logger.info(
            "Spicy mode active — v%s, intensity=%s, %d config characters, "
            "%d modifiers",
            video_config.version,
            video_config.spicy_mode.intensity,
            len(video_config.characters),
            len(video_config.spicy_mode.enabled_modifiers),
        )
        print(
            f"=== SPICY MODE: intensity={video_config.spicy_mode.intensity}, "
            f"characters={len(video_config.characters)} ==="
        )

        # Resolve config character images and merge into character_refs
        from grok_spicy.config import resolve_character_images

        resolved_images = resolve_character_images(video_config)
        for cfg_char in video_config.characters:
            imgs = resolved_images.get(cfg_char.id, [])
            if imgs and cfg_char.name not in character_refs:
                # Use the first image as the reference for this character
                first_img = imgs[0]
                if not first_img.startswith(("http://", "https://")):
                    character_refs[cfg_char.name] = first_img
                    logger.info(
                        "Spicy config: added local ref image for %r: %s",
                        cfg_char.name,
                        first_img,
                    )
                elif not config.dry_run:
                    # Download URL to local cache (skip in dry-run)
                    safe = cfg_char.name.replace(" ", "_")
                    dest = f"output/references/{safe}_config.jpg"
                    try:
                        download(first_img, dest)
                        character_refs[cfg_char.name] = dest
                        logger.info(
                            "Spicy config: downloaded ref image for %r: %s",
                            cfg_char.name,
                            dest,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to download config image for %r: %s",
                            cfg_char.name,
                            first_img,
                            exc_info=True,
                        )

    run_id = observer.on_run_start(concept)
    logger.info("Run ID assigned: %d", run_id)

    try:
        if script_plan is not None:
            # ═══ SCRIPT MODE: skip ideation, use pre-built plan ═══
            logger.info("SCRIPT MODE: using pre-built plan, skipping ideation")
            print("=== SCRIPT MODE: Using provided plan (ideation skipped) ===")
            plan = script_plan
            matched_refs: dict[str, str] = {}
            print(
                f"-> {plan.title}: {len(plan.characters)} chars, "
                f"{len(plan.scenes)} scenes"
            )
            _notify(observer, "on_plan", run_id, plan)
        else:
            # ═══ PRE-IDEATION: ANALYZE REFERENCE IMAGES ═══
            ref_descriptions: dict[str, str] | None = None
            if character_refs:
                logger.info(
                    "Pre-ideation: analyzing %d reference images",
                    len(character_refs),
                )
                print("=== Pre-ideation: Analyzing reference images ===")
                desc_futures = [
                    describe_reference_image.submit(name, path, config=config)
                    for name, path in character_refs.items()
                ]
                ref_descriptions = {}
                for fut in desc_futures:
                    desc = fut.result()
                    ref_descriptions[desc.name] = desc.visual_description
                    logger.info(
                        "Reference described: %s (%d words)",
                        desc.name,
                        len(desc.visual_description.split()),
                    )
                    print(f"  {desc.name}: description extracted")

            # ═══ STEP 1: IDEATION ═══
            logger.info("STEP 1: Ideation — generating story plan")
            print("=== STEP 1: Planning story ===")

            # When spicy mode is active, augment the concept with config context
            ideation_concept = concept
            if video_config is not None:
                from grok_spicy.prompt_builder import build_spicy_prompt

                spicy_prompt = build_spicy_prompt(video_config)
                ideation_concept = f"{concept}\n\nSpicy mode context: {spicy_prompt}"
                logger.info("Augmented concept with spicy prompt for ideation")

            plan = plan_story(
                ideation_concept, ref_descriptions=ref_descriptions, config=config
            )
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
            matched_refs = _match_character_refs(
                character_refs, plan.characters, dry_run=config.dry_run
            )
            if matched_refs:
                print(f"  Ref images matched: {list(matched_refs.keys())}")

            # Override visual descriptions with ref-extracted ones (bulletproof —
            # the LLM may have ignored the VERBATIM instruction and padded them).
            # ref_descriptions is keyed by ref labels (e.g. "women1") but
            # characters are named by the LLM (e.g. "Woman1"). Use matched_refs
            # (char_name → file_path) + character_refs (ref_label → file_path)
            # to bridge the gap.
            if ref_descriptions and matched_refs:
                # Build reverse map: file_path → ref_label
                path_to_label = {path: label for label, path in character_refs.items()}
                for char in plan.characters:
                    if char.name not in matched_refs:
                        continue
                    # matched_refs[char.name] is the file path for this character
                    ref_label = path_to_label.get(matched_refs[char.name])
                    if ref_label and ref_label in ref_descriptions:
                        old_len = len(char.visual_description)
                        char.visual_description = ref_descriptions[ref_label]
                        logger.info(
                            "Overrode visual_description for %r (via ref label %r): "
                            "%d chars → %d chars (from ref photo)",
                            char.name,
                            ref_label,
                            old_len,
                            len(char.visual_description),
                        )

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

        # ═══ SPICY: Enrich plan characters with config traits ═══
        if video_config is not None:
            _enrich_characters_from_config(plan, video_config)

        # ═══ STEP 2: CHARACTER SHEETS (parallel) ═══
        logger.info("STEP 2: Character sheets — generating %d", len(plan.characters))
        print("=== STEP 2: Character sheets ===")
        char_futures = [
            generate_character_sheet.submit(
                c,
                plan.style,
                plan.aspect_ratio,
                reference_image_path=matched_refs.get(c.name),
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

            from grok_spicy.dry_run import DRY_RUN_DIR, write_summary

            prompt_files = sorted(
                globmod.glob(os.path.join(DRY_RUN_DIR, "**", "*.md"), recursive=True)
            )
            summary_path = write_summary(prompt_files)
            logger.info("Dry-run summary written to %s", summary_path)
            print(f"-> Summary: {summary_path}")

            # Save state (with placeholder paths)
            state.videos = videos
            _save_state(state)

            _notify(observer, "on_complete", run_id, summary_path)
            return summary_path
        else:
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
