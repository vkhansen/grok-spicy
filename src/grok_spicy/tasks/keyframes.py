"""Step 3: Keyframe composition via multi-image edit with consistency checks."""

from __future__ import annotations

import logging
from typing import Any

from prefect import task

from grok_spicy.client import (
    MODEL_IMAGE,
    MODEL_REASONING,
    MODEL_VIDEO,
    download,
    generate_with_moderation_retry,
    get_client,
)
from grok_spicy.prompts import (
    append_negative_prompt,
    build_video_prompt,
    fix_prompt_from_issues,
    keyframe_compose_prompt,
    keyframe_vision_prompt,
)
from grok_spicy.schemas import (
    CharacterAsset,
    ConsistencyScore,
    KeyframeAsset,
    PipelineConfig,
    Scene,
    StoryPlan,
    VideoConfig,
)

logger = logging.getLogger(__name__)


@task(name="compose-keyframe", retries=1, retry_delay_seconds=20)
def compose_keyframe(
    scene: Scene,
    plan: StoryPlan,
    char_map: dict[str, CharacterAsset],
    prev_last_frame_url: str | None,
    config: PipelineConfig | None = None,
    video_config: VideoConfig | None = None,
) -> KeyframeAsset:
    """Compose a keyframe image for a scene using multi-image editing.

    Uses character reference sheets as input images so Grok maintains
    character appearance. Includes a compose → vision-check → fix loop.
    """
    from xai_sdk.chat import image, user

    if config is None:
        config = PipelineConfig()

    max_iters = config.max_keyframe_iters
    threshold = config.consistency_threshold

    logger.info(
        "Keyframe starting: scene=%d, title=%r, max_iters=%d, threshold=%.2f",
        scene.scene_id,
        scene.title,
        max_iters,
        threshold,
    )

    client = get_client()
    scene_chars = [char_map[n] for n in scene.characters_present if n in char_map]
    logger.debug(
        "Scene %d characters: %s (from %s)",
        scene.scene_id,
        [c.name for c in scene_chars],
        scene.characters_present,
    )

    # Build reference URLs (max 3 slots)
    ref_urls = [c.portrait_url for c in scene_chars[:2]]
    if prev_last_frame_url and len(ref_urls) < 3:
        ref_urls.append(prev_last_frame_url)
    logger.info(
        "Scene %d ref slots: %d character(s) + %s prev_frame = %d total",
        scene.scene_id,
        len(scene_chars[:2]),
        "1" if prev_last_frame_url and len(ref_urls) <= 3 else "0",
        len(ref_urls),
    )

    # Build composition prompt — character appearance comes from the reference
    # images passed via image_urls, so we only need name + position here.
    char_lines = []
    for i, c in enumerate(scene_chars[:2]):
        pos = ["left side", "right side"][i] if len(scene_chars) > 1 else "center"
        char_lines.append(
            f"{c.name} (reference image {i + 1}), positioned on the {pos}"
        )

    compose_prompt = keyframe_compose_prompt(
        plan_style=plan.style,
        scene_title=scene.title,
        scene_prompt_summary=scene.prompt_summary,
        scene_setting=scene.setting,
        scene_mood=scene.mood,
        scene_action=scene.action,
        scene_camera=scene.camera,
        color_palette=plan.color_palette,
        char_lines=char_lines,
        video_config=video_config,
    )

    logger.info("Compose prompt: %s", compose_prompt)

    # Video prompt for Step 5 — tier-aware construction
    video_prompt = build_video_prompt(
        prompt_summary=scene.prompt_summary,
        camera=scene.camera,
        action=scene.action,
        mood=scene.mood,
        style=plan.style,
        duration_seconds=scene.duration_seconds,
        video_config=video_config,
    )

    video_prompt = append_negative_prompt(video_prompt, config.negative_prompt)
    tier = (
        "standard (correction eligible)"
        if scene.duration_seconds <= 8
        else "extended (no correction)"
    )
    logger.info("Video prompt [%s]: %s", tier, video_prompt)

    # ── DRY-RUN: write prompts, return mock ──
    if config.dry_run:
        from grok_spicy.dry_run import write_prompt

        ref_labels = [f"{c.name} portrait ({c.portrait_url})" for c in scene_chars[:2]]
        if prev_last_frame_url:
            ref_labels.append(f"prev_frame ({prev_last_frame_url})")
        write_prompt(
            "step3_keyframes",
            f"scene_{scene.scene_id}_compose",
            model=MODEL_IMAGE,
            prompt=compose_prompt,
            image_refs=ref_labels,
            api_params={"aspect_ratio": plan.aspect_ratio},
        )
        write_prompt(
            "step3_keyframes",
            f"scene_{scene.scene_id}_video_prompt",
            model=MODEL_VIDEO,
            prompt=video_prompt,
            api_params={
                "duration": scene.duration_seconds,
                "tier": tier,
            },
        )
        v_prompt = keyframe_vision_prompt(scene, video_config)
        write_prompt(
            "step3_keyframes",
            f"scene_{scene.scene_id}_vision_check",
            model=MODEL_REASONING,
            prompt=v_prompt,
            image_refs=[f"{c.name} portrait" for c in scene_chars[:2]],
        )
        logger.info("Dry-run: wrote keyframe prompts for scene %d", scene.scene_id)
        return KeyframeAsset(
            scene_id=scene.scene_id,
            keyframe_url="dry-run://placeholder",
            keyframe_path=f"output/keyframes/scene_{scene.scene_id}_dry_run.jpg",
            consistency_score=1.0,
            generation_attempts=0,
            edit_passes=0,
            video_prompt=video_prompt,
        )

    best: dict = {"score": 0.0, "url": "", "path": ""}
    fix_text = None
    iteration = 0
    score: ConsistencyScore | None = None

    for iteration in range(1, max_iters + 1):
        if iteration == 1:
            # 3a: Multi-image composition
            logger.info(
                "Scene %d iteration %d/%d: initial composition (model=%s)",
                scene.scene_id,
                iteration,
                max_iters,
                MODEL_IMAGE,
            )
            current_prompt = compose_prompt
            sample_kw: dict[str, Any] = dict(
                model=MODEL_IMAGE,
                image_urls=ref_urls,
                aspect_ratio=plan.aspect_ratio,
            )
        else:
            # 3c: Targeted single-image edit
            current_prompt = fix_prompt_from_issues(
                score.issues if score else [], fix_text
            )
            logger.info(
                "Scene %d iteration %d/%d: fix edit prompt: %s",
                scene.scene_id,
                iteration,
                max_iters,
                current_prompt,
            )
            sample_kw = dict(model=MODEL_IMAGE, image_url=best["url"])

        img, current_prompt, still_moderated = generate_with_moderation_retry(
            client.image.sample, current_prompt, **sample_kw
        )
        if still_moderated:
            logger.warning(
                "Scene %d iteration %d: still moderated after rewords, "
                "skipping iteration",
                scene.scene_id,
                iteration,
            )
            continue

        path = download(
            img.url,
            f"output/keyframes/scene_{scene.scene_id}_v{iteration}.jpg",
        )

        # 3b: Vision consistency check
        v_prompt = keyframe_vision_prompt(scene, video_config)
        logger.info(
            "Scene %d vision check (model=%s, %d ref images): %s",
            scene.scene_id,
            MODEL_REASONING,
            len(scene_chars[:2]),
            v_prompt,
        )
        vision_imgs = [image(img.url)]
        for c in scene_chars[:2]:
            vision_imgs.append(image(c.portrait_url))

        chat = client.chat.create(model=MODEL_REASONING)
        chat.append(
            user(
                v_prompt,
                *vision_imgs,
            )
        )
        _, score = chat.parse(ConsistencyScore)

        logger.info(
            "Scene %d iteration %d: score=%.2f (threshold=%.2f), issues=%s",
            scene.scene_id,
            iteration,
            score.overall_score,
            threshold,
            score.issues if hasattr(score, "issues") and score.issues else "none",
        )

        if score.overall_score > best["score"]:
            logger.debug(
                "Scene %d new best: %.2f → %.2f",
                scene.scene_id,
                best["score"],
                score.overall_score,
            )
            best = {
                "score": score.overall_score,
                "url": img.url,
                "path": path,
            }

        if score.overall_score >= threshold:
            logger.info(
                "Scene %d passed threshold at iteration %d (score=%.2f >= %.2f)",
                scene.scene_id,
                iteration,
                score.overall_score,
                threshold,
            )
            break

        fix_text = score.fix_prompt
        logger.info(
            "Scene %d fix prompt: %s",
            scene.scene_id,
            fix_prompt_from_issues(score.issues, fix_text),
        )
    else:
        logger.warning(
            "Scene %d exhausted all %d iterations, using best score=%.2f",
            scene.scene_id,
            max_iters,
            best["score"],
        )

    logger.info(
        "Keyframe done: scene=%d, final_score=%.2f, edit_passes=%d, path=%s",
        scene.scene_id,
        best["score"],
        iteration - 1,
        best["path"],
    )

    return KeyframeAsset(
        scene_id=scene.scene_id,
        keyframe_url=best["url"],
        keyframe_path=best["path"],
        consistency_score=best["score"],
        generation_attempts=1,
        edit_passes=iteration - 1,
        video_prompt=video_prompt,
    )
