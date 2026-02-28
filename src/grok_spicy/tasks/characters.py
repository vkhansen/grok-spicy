"""Step 2: Character sheet generation with vision verification loop."""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)
def generate_character_sheet(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str | None = None,
) -> CharacterAsset:
    """Generate a verified character reference portrait.

    Loop: generate portrait -> vision verify -> retry if score < threshold.
    Keeps the best result across all attempts.

    If reference_image_path is provided, uses single-image edit (stylize mode)
    to transform the reference photo into the art style while preserving likeness.
    """
    from xai_sdk.chat import image, user

    mode = "stylize" if reference_image_path else "generate"
    logger.info(
        "Character sheet starting: name=%r, mode=%s, max_attempts=%d, threshold=%.2f",
        character.name,
        mode,
        MAX_CHAR_ATTEMPTS,
        CONSISTENCY_THRESHOLD,
    )
    if reference_image_path:
        logger.debug("Reference image path: %s", reference_image_path)

    client = get_client()
    best: dict = {"score": 0.0, "url": "", "path": ""}
    attempt = 0

    for attempt in range(1, MAX_CHAR_ATTEMPTS + 1):
        logger.info(
            "Character %r attempt %d/%d (mode=%s)",
            character.name,
            attempt,
            MAX_CHAR_ATTEMPTS,
            mode,
        )

        if reference_image_path:
            # STYLIZE MODE: edit the reference photo into the art style
            prompt = (
                f"{style}. Transform this photo into a full body character "
                f"portrait while preserving the person's exact facial features, "
                f"face shape, and likeness. {character.visual_description}. "
                f"Standing in a neutral three-quarter pose against a plain "
                f"light gray background. Professional character design "
                f"reference sheet style. Sharp details, even studio lighting, "
                f"no background clutter, no text or labels."
            )
            logger.debug("Stylize prompt (len=%d): %s", len(prompt), prompt[:200])
            img = client.image.sample(
                prompt=prompt,
                model=MODEL_IMAGE,
                image_url=reference_image_path,
                aspect_ratio=aspect_ratio,
            )
        else:
            # GENERATE MODE: text-to-image from scratch
            prompt = (
                f"{style}. Full body character portrait of "
                f"{character.visual_description}. "
                f"Standing in a neutral three-quarter pose against a plain "
                f"light gray background. Professional character design "
                f"reference sheet style. Sharp details, even studio lighting, "
                f"no background clutter, no text or labels."
            )
            logger.debug("Generate prompt (len=%d): %s", len(prompt), prompt[:200])
            img = client.image.sample(
                prompt=prompt,
                model=MODEL_IMAGE,
                aspect_ratio=aspect_ratio,
            )

        logger.debug("Image generated, URL=%s", img.url[:80])
        path = download(
            img.url,
            f"output/character_sheets/{character.name}_v{attempt}.jpg",
        )

        # Vision verify
        logger.debug(
            "Vision verify: model=%s, character=%r", MODEL_REASONING, character.name
        )
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

        logger.info(
            "Character %r attempt %d: score=%.2f (threshold=%.2f), issues=%s",
            character.name,
            attempt,
            score.overall_score,
            CONSISTENCY_THRESHOLD,
            score.issues if hasattr(score, "issues") and score.issues else "none",
        )

        if score.overall_score > best["score"]:
            logger.debug(
                "New best for %r: %.2f → %.2f",
                character.name,
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
                "Character %r passed threshold at attempt %d (score=%.2f >= %.2f)",
                character.name,
                attempt,
                score.overall_score,
                CONSISTENCY_THRESHOLD,
            )
            break
    else:
        logger.warning(
            "Character %r exhausted all %d attempts, using best score=%.2f",
            character.name,
            MAX_CHAR_ATTEMPTS,
            best["score"],
        )

    logger.info(
        "Character sheet done: name=%r, final_score=%.2f, attempts=%d, path=%s",
        character.name,
        best["score"],
        attempt,
        best["path"],
    )

    return CharacterAsset(
        name=character.name,
        portrait_url=best["url"],
        portrait_path=best["path"],
        visual_description=character.visual_description,
        consistency_score=best["score"],
        generation_attempts=attempt,
    )
