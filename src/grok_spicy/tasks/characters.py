"""Step 2: Character sheet generation with vision verification loop."""

from __future__ import annotations

from prefect import task

from grok_spicy.client import (
    CONSISTENCY_THRESHOLD,
    MAX_CHAR_ATTEMPTS,
    MODEL_IMAGE,
    MODEL_REASONING,
    download,
    get_client,
)
from grok_spicy.schemas import Character, CharacterAsset, ConsistencyScore


@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)
def generate_character_sheet(
    character: Character, style: str, aspect_ratio: str
) -> CharacterAsset:
    """Generate a verified character reference portrait.

    Loop: generate portrait → vision verify → retry if score < threshold.
    Keeps the best result across all attempts.
    """
    from xai_sdk.chat import image, user

    client = get_client()
    best: dict = {"score": 0.0, "url": "", "path": ""}
    attempt = 0

    for attempt in range(1, MAX_CHAR_ATTEMPTS + 1):
        # 2a: Generate portrait
        prompt = (
            f"{style}. Full body character portrait of "
            f"{character.visual_description}. "
            f"Standing in a neutral three-quarter pose against a plain "
            f"light gray background. Professional character design "
            f"reference sheet style. Sharp details, even studio lighting, "
            f"no background clutter, no text or labels."
        )
        img = client.image.sample(
            prompt=prompt,
            model=MODEL_IMAGE,
            aspect_ratio=aspect_ratio,
        )
        path = download(
            img.url,
            f"output/character_sheets/{character.name}_v{attempt}.jpg",
        )

        # 2b: Vision verify
        chat = client.chat.create(model=MODEL_REASONING)
        chat.append(
            user(
                f"Score how well this portrait matches the description. "
                f"Be strict on: hair color/style, eye color, clothing "
                f"colors and style, build, distinguishing features.\n\n"
                f"Description: {character.visual_description}",
                image(img.url),
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

    return CharacterAsset(
        name=character.name,
        portrait_url=best["url"],
        portrait_path=best["path"],
        visual_description=character.visual_description,
        consistency_score=best["score"],
        generation_attempts=attempt,
    )
