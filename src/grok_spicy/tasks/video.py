"""Step 5: Video generation from keyframes with drift correction."""

from __future__ import annotations

from prefect import task

from grok_spicy.client import (
    CONSISTENCY_THRESHOLD,
    MAX_VIDEO_CORRECTIONS,
    MODEL_REASONING,
    MODEL_VIDEO,
    RESOLUTION,
    download,
    extract_frame,
    get_client,
    to_base64,
)
from grok_spicy.schemas import (
    CharacterAsset,
    ConsistencyScore,
    KeyframeAsset,
    Scene,
    VideoAsset,
)


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

    client = get_client()
    corrections = 0

    # 5a: Image → Video
    vid = client.video.generate(
        prompt=keyframe.video_prompt,
        model=MODEL_VIDEO,
        image_url=keyframe.keyframe_url,
        duration=scene.duration_seconds,
        aspect_ratio="16:9",
        resolution=RESOLUTION,
    )

    video_path = f"output/videos/scene_{scene.scene_id}.mp4"
    download(vid.url, video_path)
    current_url = vid.url

    # 5b: Extract frames
    first_frame = f"output/frames/scene_{scene.scene_id}_first.jpg"
    last_frame = f"output/frames/scene_{scene.scene_id}_last.jpg"
    extract_frame(video_path, first_frame, "first")
    extract_frame(video_path, last_frame, "last")

    # 5c: Vision check last frame
    scene_chars = [char_map[n] for n in scene.characters_present if n in char_map]

    def _check_consistency() -> ConsistencyScore:
        chat = client.chat.create(model=MODEL_REASONING)
        imgs = [image(f"data:image/jpeg;base64,{to_base64(last_frame)}")]
        for c in scene_chars[:2]:
            imgs.append(image(c.portrait_url))
        chat.append(
            user(
                "Image 1 is a video's last frame. Images 2+ are character "
                "refs. Has the character drifted? Score consistency.",
                *imgs,
            )
        )
        _, s = chat.parse(ConsistencyScore)
        return s

    score = _check_consistency()

    # 5d: Correction loop (only for clips ≤ 8s, API limit 8.7s)
    while (
        score.overall_score < CONSISTENCY_THRESHOLD
        and corrections < MAX_VIDEO_CORRECTIONS
        and scene.duration_seconds <= 8
    ):
        corrections += 1
        fix = score.fix_prompt or f"Fix: {'; '.join(score.issues)}"

        vid = client.video.generate(
            prompt=fix,
            model=MODEL_VIDEO,
            video_url=current_url,
        )
        current_url = vid.url
        corr_path = f"output/videos/scene_{scene.scene_id}_c{corrections}.mp4"
        download(vid.url, corr_path)
        video_path = corr_path

        extract_frame(video_path, last_frame, "last")
        score = _check_consistency()

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
