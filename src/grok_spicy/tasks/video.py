"""Step 5: Video generation from keyframes with drift correction."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import (
    EXTENDED_RETRY_THRESHOLD,
    MODEL_REASONING,
    MODEL_VIDEO,
    RESOLUTION,
    download,
    extract_frame,
    generate_with_moderation_retry,
    get_client,
    to_base64,
)
from grok_spicy.prompts import (
    append_negative_prompt,
    extended_retry_prompt,
    video_fix_prompt,
    video_vision_prompt,
)
from grok_spicy.schemas import (
    CharacterAsset,
    ConsistencyScore,
    KeyframeAsset,
    PipelineConfig,
    Scene,
    VideoAsset,
    VideoConfig,
)

logger = logging.getLogger(__name__)


@task(
    name="generate-video",
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=600,
)
def generate_scene_video(
    keyframe: KeyframeAsset,
    scene: Scene,
    char_map: dict[str, CharacterAsset],
    config: PipelineConfig | None = None,
    video_config: VideoConfig | None = None,
) -> VideoAsset:
    """Generate a video clip from a keyframe image, with drift correction.

    Flow: image→video → extract frames → vision check → correction loop.
    """
    from xai_sdk.chat import image, user

    if config is None:
        config = PipelineConfig()

    threshold = config.consistency_threshold
    max_corrections = config.max_video_corrections

    correction_eligible = scene.duration_seconds <= 8
    tier = (
        "standard (correction eligible)"
        if correction_eligible
        else "extended (no correction)"
    )
    logger.info(
        "Video generation starting: scene=%d, duration=%ds, tier=%s, model=%s, resolution=%s",
        scene.scene_id,
        scene.duration_seconds,
        tier,
        MODEL_VIDEO,
        RESOLUTION,
    )
    logger.info("Video prompt: %s", keyframe.video_prompt)

    client = get_client()
    corrections = 0

    # 5a: Image → Video
    logger.info(
        "Scene %d: generating initial video from keyframe (image→video)",
        scene.scene_id,
    )
    vid_prompt = keyframe.video_prompt

    # Inject spicy global prefix if active
    if video_config is not None and video_config.spicy_mode.global_prefix:
        vid_prompt = f"{video_config.spicy_mode.global_prefix}{vid_prompt}"
        logger.info("Spicy prefix injected into video prompt")
    vid_kw = dict(
        model=MODEL_VIDEO,
        image_url=keyframe.keyframe_url,
        duration=scene.duration_seconds,
        aspect_ratio="16:9",
        resolution=RESOLUTION,
    )
    vid, vid_prompt, still_moderated = generate_with_moderation_retry(
        client.video.generate, vid_prompt, **vid_kw
    )
    if still_moderated:
        raise RuntimeError(
            f"Scene {scene.scene_id}: video still moderated after rewords"
        )

    video_path = f"output/videos/scene_{scene.scene_id}.mp4"
    download(vid.url, video_path)
    current_url = vid.url
    logger.info("Scene %d: initial video downloaded → %s", scene.scene_id, video_path)

    # 5b: Extract frames
    first_frame = f"output/frames/scene_{scene.scene_id}_first.jpg"
    last_frame = f"output/frames/scene_{scene.scene_id}_last.jpg"
    logger.debug("Scene %d: extracting first and last frames", scene.scene_id)
    extract_frame(video_path, first_frame, "first")
    extract_frame(video_path, last_frame, "last")

    # 5c: Vision check last frame
    scene_chars = [char_map[n] for n in scene.characters_present if n in char_map]
    logger.debug(
        "Scene %d: vision check with %d character refs",
        scene.scene_id,
        len(scene_chars),
    )

    v_prompt = video_vision_prompt()

    def _check_consistency() -> ConsistencyScore:
        logger.info(
            "Scene %d consistency check (model=%s): %s",
            scene.scene_id,
            MODEL_REASONING,
            v_prompt,
        )
        chat = client.chat.create(model=MODEL_REASONING)
        imgs = [image(f"data:image/jpeg;base64,{to_base64(last_frame)}")]
        for c in scene_chars[:2]:
            imgs.append(image(c.portrait_url))
        chat.append(
            user(
                v_prompt,
                *imgs,
            )
        )
        _, s = chat.parse(ConsistencyScore)
        result: ConsistencyScore = s
        return result

    score = _check_consistency()
    logger.info(
        "Scene %d initial consistency: score=%.2f (threshold=%.2f), issues=%s",
        scene.scene_id,
        score.overall_score,
        threshold,
        score.issues if hasattr(score, "issues") and score.issues else "none",
    )

    # 5d: Correction loop (only for clips ≤ 8s, API limit 8.7s)
    if not correction_eligible:
        logger.info(
            "Scene %d: correction ineligible (duration=%ds > 8s limit)",
            scene.scene_id,
            scene.duration_seconds,
        )

    while (
        score.overall_score < threshold
        and corrections < max_corrections
        and correction_eligible
    ):
        corrections += 1
        fix = video_fix_prompt(score.issues, score.fix_prompt)
        logger.info(
            "Scene %d correction %d/%d: score=%.2f < %.2f, fix prompt: %s",
            scene.scene_id,
            corrections,
            max_corrections,
            score.overall_score,
            threshold,
            fix,
        )

        vid, fix, still_moderated = generate_with_moderation_retry(
            client.video.generate,
            fix,
            model=MODEL_VIDEO,
            video_url=current_url,
        )
        if still_moderated:
            logger.warning(
                "Scene %d correction %d: still moderated after rewords, "
                "stopping corrections",
                scene.scene_id,
                corrections,
            )
            break

        current_url = vid.url
        corr_path = f"output/videos/scene_{scene.scene_id}_c{corrections}.mp4"
        download(vid.url, corr_path)
        video_path = corr_path
        logger.debug(
            "Scene %d correction %d downloaded → %s",
            scene.scene_id,
            corrections,
            corr_path,
        )

        extract_frame(video_path, last_frame, "last")
        score = _check_consistency()
        logger.info(
            "Scene %d after correction %d: score=%.2f",
            scene.scene_id,
            corrections,
            score.overall_score,
        )

    # Log final decision
    if score.overall_score >= threshold:
        logger.info(
            "Scene %d: passed threshold (score=%.2f >= %.2f) after %d corrections",
            scene.scene_id,
            score.overall_score,
            threshold,
            corrections,
        )
    elif corrections >= max_corrections:
        logger.warning(
            "Scene %d: exhausted %d corrections, using best score=%.2f",
            scene.scene_id,
            max_corrections,
            score.overall_score,
        )
    elif not correction_eligible:
        logger.info(
            "Scene %d: no corrections attempted (duration > 8s), score=%.2f",
            scene.scene_id,
            score.overall_score,
        )

    # 5e: Extended-scene retry — regenerate from scratch if score is very low
    if not correction_eligible and score.overall_score < EXTENDED_RETRY_THRESHOLD:
        logger.warning(
            "Scene %d: extended scene scored %.2f < %.2f, regenerating from scratch",
            scene.scene_id,
            score.overall_score,
            EXTENDED_RETRY_THRESHOLD,
        )
        retry_prompt = extended_retry_prompt(keyframe.video_prompt, score.issues)
        retry_prompt = append_negative_prompt(retry_prompt, config.negative_prompt)
        vid, retry_prompt, still_moderated = generate_with_moderation_retry(
            client.video.generate, retry_prompt, **vid_kw
        )
        if not still_moderated:
            retry_path = f"output/videos/scene_{scene.scene_id}_retry.mp4"
            download(vid.url, retry_path)
            video_path = retry_path
            current_url = vid.url
            extract_frame(video_path, first_frame, "first")
            extract_frame(video_path, last_frame, "last")
            score = _check_consistency()
            logger.info(
                "Scene %d: extended retry score=%.2f (was %.2f)",
                scene.scene_id,
                score.overall_score,
                EXTENDED_RETRY_THRESHOLD,
            )

    logger.info(
        "Video done: scene=%d, final_score=%.2f, corrections=%d, path=%s",
        scene.scene_id,
        score.overall_score,
        corrections,
        video_path,
    )

    return VideoAsset(
        scene_id=scene.scene_id,
        video_url=current_url,
        video_path=video_path,
        duration=scene.duration_seconds,
        first_frame_path=first_frame,
        last_frame_path=last_frame,
        consistency_score=score.overall_score,
        correction_passes=corrections,
    )
