"""Step 5: Video generation from keyframes with drift correction."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import (
    CONSISTENCY_THRESHOLD,
    MAX_REWORD_ATTEMPTS,
    MAX_VIDEO_CORRECTIONS,
    MODEL_REASONING,
    MODEL_VIDEO,
    RESOLUTION,
    download,
    extract_frame,
    get_client,
    is_moderated,
    reword_prompt,
    to_base64,
)
from grok_spicy.schemas import (
    CharacterAsset,
    ConsistencyScore,
    KeyframeAsset,
    Scene,
    VideoAsset,
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
) -> VideoAsset:
    """Generate a video clip from a keyframe image, with drift correction.

    Flow: image→video → extract frames → vision check → correction loop.
    """
    from xai_sdk.chat import image, user

    logger.info(
        "Video generation starting: scene=%d, duration=%ds, model=%s, resolution=%s",
        scene.scene_id,
        scene.duration_seconds,
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
    vid_kw = dict(
        model=MODEL_VIDEO,
        image_url=keyframe.keyframe_url,
        duration=scene.duration_seconds,
        aspect_ratio="16:9",
        resolution=RESOLUTION,
    )
    vid = client.video.generate(prompt=vid_prompt, **vid_kw)

    # Moderation soft-fail: reword prompt and retry
    for _rw in range(MAX_REWORD_ATTEMPTS):
        if not is_moderated(vid.url):
            break
        logger.warning(
            "Scene %d: video moderation hit (reword %d/%d)",
            scene.scene_id,
            _rw + 1,
            MAX_REWORD_ATTEMPTS,
        )
        vid_prompt = reword_prompt(vid_prompt)
        vid = client.video.generate(prompt=vid_prompt, **vid_kw)
    if is_moderated(vid.url):
        raise RuntimeError(
            f"Scene {scene.scene_id}: video still moderated after "
            f"{MAX_REWORD_ATTEMPTS} rewords"
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

    vision_prompt = (
        "Image 1 is a video's last frame. Images 2+ are character "
        "refs. Has the character drifted? Score consistency."
    )

    def _check_consistency() -> ConsistencyScore:
        logger.info(
            "Scene %d consistency check (model=%s): %s",
            scene.scene_id,
            MODEL_REASONING,
            vision_prompt,
        )
        chat = client.chat.create(model=MODEL_REASONING)
        imgs = [image(f"data:image/jpeg;base64,{to_base64(last_frame)}")]
        for c in scene_chars[:2]:
            imgs.append(image(c.portrait_url))
        chat.append(
            user(
                vision_prompt,
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
        CONSISTENCY_THRESHOLD,
        score.issues if hasattr(score, "issues") and score.issues else "none",
    )

    # 5d: Correction loop (only for clips ≤ 8s, API limit 8.7s)
    correction_eligible = scene.duration_seconds <= 8
    if not correction_eligible:
        logger.info(
            "Scene %d: correction ineligible (duration=%ds > 8s limit)",
            scene.scene_id,
            scene.duration_seconds,
        )

    while (
        score.overall_score < CONSISTENCY_THRESHOLD
        and corrections < MAX_VIDEO_CORRECTIONS
        and correction_eligible
    ):
        corrections += 1
        fix = score.fix_prompt or f"Fix: {'; '.join(score.issues)}"
        logger.info(
            "Scene %d correction %d/%d: score=%.2f < %.2f, fix prompt: %s",
            scene.scene_id,
            corrections,
            MAX_VIDEO_CORRECTIONS,
            score.overall_score,
            CONSISTENCY_THRESHOLD,
            fix,
        )

        vid = client.video.generate(
            prompt=fix,
            model=MODEL_VIDEO,
            video_url=current_url,
        )

        # Moderation soft-fail on correction: reword and retry
        for _rw in range(MAX_REWORD_ATTEMPTS):
            if not is_moderated(vid.url):
                break
            logger.warning(
                "Scene %d correction %d: moderation hit (reword %d/%d)",
                scene.scene_id,
                corrections,
                _rw + 1,
                MAX_REWORD_ATTEMPTS,
            )
            fix = reword_prompt(fix)
            vid = client.video.generate(
                prompt=fix,
                model=MODEL_VIDEO,
                video_url=current_url,
            )
        if is_moderated(vid.url):
            logger.warning(
                "Scene %d correction %d: still moderated after %d rewords, "
                "stopping corrections",
                scene.scene_id,
                corrections,
                MAX_REWORD_ATTEMPTS,
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
    if score.overall_score >= CONSISTENCY_THRESHOLD:
        logger.info(
            "Scene %d: passed threshold (score=%.2f >= %.2f) after %d corrections",
            scene.scene_id,
            score.overall_score,
            CONSISTENCY_THRESHOLD,
            corrections,
        )
    elif corrections >= MAX_VIDEO_CORRECTIONS:
        logger.warning(
            "Scene %d: exhausted %d corrections, using best score=%.2f",
            scene.scene_id,
            MAX_VIDEO_CORRECTIONS,
            score.overall_score,
        )
    elif not correction_eligible:
        logger.info(
            "Scene %d: no corrections attempted (duration > 8s), score=%.2f",
            scene.scene_id,
            score.overall_score,
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
