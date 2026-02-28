"""Step 3: Keyframe composition via multi-image edit with consistency checks."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import (
    CONSISTENCY_THRESHOLD,
    MAX_KEYFRAME_ITERS,
    MODEL_IMAGE,
    MODEL_REASONING,
    download,
    get_client,
)
from grok_spicy.schemas import (
    CharacterAsset,
    ConsistencyScore,
    KeyframeAsset,
    Scene,
    StoryPlan,
)

logger = logging.getLogger(__name__)


@task(name="compose-keyframe", retries=1, retry_delay_seconds=20)
def compose_keyframe(
    scene: Scene,
    plan: StoryPlan,
    char_map: dict[str, CharacterAsset],
    prev_last_frame_url: str | None,
) -> KeyframeAsset:
    """Compose a keyframe image for a scene using multi-image editing.

    Uses character reference sheets as input images so Grok maintains
    character appearance. Includes a compose → vision-check → fix loop.
    """
    from xai_sdk.chat import image, user

    logger.info(
        "Keyframe starting: scene=%d, title=%r, max_iters=%d, threshold=%.2f",
        scene.scene_id,
        scene.title,
        MAX_KEYFRAME_ITERS,
        CONSISTENCY_THRESHOLD,
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

    # Build composition prompt
    char_lines = []
    for i, c in enumerate(scene_chars[:2]):
        pos = ["left side", "right side"][i] if len(scene_chars) > 1 else "center"
        brief = c.visual_description[:250]
        char_lines.append(
            f"{c.name} from reference image {i + 1}: {brief}, "
            f"positioned on the {pos}"
        )

    compose_prompt = (
        f"{plan.style}. "
        f"Setting: {scene.setting}. {scene.mood}. "
        f"{'. '.join(char_lines)}. "
        f"Action: {scene.action}. "
        f"Camera: {scene.camera}. "
        f"Color palette: {plan.color_palette}. "
        f"Maintain exact character appearances from the reference images."
    )
    logger.debug(
        "Compose prompt (len=%d): %s", len(compose_prompt), compose_prompt[:200]
    )

    # Motion-only video prompt for Step 5
    video_prompt = (
        f"{scene.camera}. {scene.action}. "
        f"{scene.mood}. {plan.style}. "
        f"Smooth cinematic motion."
    )
    logger.debug("Video prompt: %s", video_prompt)

    best: dict = {"score": 0.0, "url": "", "path": ""}
    fix_prompt = None
    iteration = 0

    for iteration in range(1, MAX_KEYFRAME_ITERS + 1):
        if iteration == 1:
            # 3a: Multi-image composition
            logger.info(
                "Scene %d iteration %d/%d: initial composition (model=%s)",
                scene.scene_id,
                iteration,
                MAX_KEYFRAME_ITERS,
                MODEL_IMAGE,
            )
            img = client.image.sample(
                prompt=compose_prompt,
                model=MODEL_IMAGE,
                image_urls=ref_urls,
                aspect_ratio=plan.aspect_ratio,
            )
        else:
            # 3c: Targeted single-image edit
            logger.info(
                "Scene %d iteration %d/%d: fix edit — %s",
                scene.scene_id,
                iteration,
                MAX_KEYFRAME_ITERS,
                (fix_prompt or "")[:100],
            )
            img = client.image.sample(
                prompt=fix_prompt,
                model=MODEL_IMAGE,
                image_url=best["url"],
            )

        path = download(
            img.url,
            f"output/keyframes/scene_{scene.scene_id}_v{iteration}.jpg",
        )

        # 3b: Vision consistency check
        logger.debug(
            "Scene %d vision check: model=%s, %d ref images",
            scene.scene_id,
            MODEL_REASONING,
            len(scene_chars[:2]),
        )
        vision_imgs = [image(img.url)]
        for c in scene_chars[:2]:
            vision_imgs.append(image(c.portrait_url))

        chat = client.chat.create(model=MODEL_REASONING)
        chat.append(
            user(
                "Image 1 is a scene. Images 2+ are character references. "
                "Score how well characters in the scene match their refs. "
                "If issues, provide a surgical fix prompt.",
                *vision_imgs,
            )
        )
        _, score = chat.parse(ConsistencyScore)

        logger.info(
            "Scene %d iteration %d: score=%.2f (threshold=%.2f), issues=%s",
            scene.scene_id,
            iteration,
            score.overall_score,
            CONSISTENCY_THRESHOLD,
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

        if score.overall_score >= CONSISTENCY_THRESHOLD:
            logger.info(
                "Scene %d passed threshold at iteration %d (score=%.2f >= %.2f)",
                scene.scene_id,
                iteration,
                score.overall_score,
                CONSISTENCY_THRESHOLD,
            )
            break

        fix_prompt = score.fix_prompt or (
            f"Fix ONLY these issues, keep everything else identical: "
            f"{'; '.join(score.issues)}"
        )
        logger.debug("Scene %d fix prompt: %s", scene.scene_id, fix_prompt[:150])
    else:
        logger.warning(
            "Scene %d exhausted all %d iterations, using best score=%.2f",
            scene.scene_id,
            MAX_KEYFRAME_ITERS,
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
