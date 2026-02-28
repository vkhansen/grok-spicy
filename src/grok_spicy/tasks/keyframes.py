"""Step 3: Keyframe composition via multi-image edit with consistency checks."""

from __future__ import annotations

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

    client = get_client()
    scene_chars = [char_map[n] for n in scene.characters_present if n in char_map]

    # Build reference URLs (max 3 slots)
    ref_urls = [c.portrait_url for c in scene_chars[:2]]
    if prev_last_frame_url and len(ref_urls) < 3:
        ref_urls.append(prev_last_frame_url)

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

    # Motion-only video prompt for Step 5
    video_prompt = (
        f"{scene.camera}. {scene.action}. "
        f"{scene.mood}. {plan.style}. "
        f"Smooth cinematic motion."
    )

    best: dict = {"score": 0.0, "url": "", "path": ""}
    fix_prompt = None
    iteration = 0

    for iteration in range(1, MAX_KEYFRAME_ITERS + 1):
        if iteration == 1:
            # 3a: Multi-image composition
            img = client.image.sample(
                prompt=compose_prompt,
                model=MODEL_IMAGE,
                image_urls=ref_urls,
                aspect_ratio=plan.aspect_ratio,
            )
        else:
            # 3c: Targeted single-image edit
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

        if score.overall_score > best["score"]:
            best = {
                "score": score.overall_score,
                "url": img.url,
                "path": path,
            }

        if score.overall_score >= CONSISTENCY_THRESHOLD:
            break

        fix_prompt = score.fix_prompt or (
            f"Fix ONLY these issues, keep everything else identical: "
            f"{'; '.join(score.issues)}"
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
