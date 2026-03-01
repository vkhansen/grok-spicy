"""Step 2: Character sheet generation with vision verification loop."""

from __future__ import annotations

import logging
from typing import Any

from prefect import task

from grok_spicy.client import (
    MODEL_IMAGE,
    MODEL_REASONING,
    download,
    generate_with_moderation_retry,
    get_client,
    to_base64,
)
from grok_spicy.prompts import (
    character_generate_prompt,
    character_stylize_prompt,
    character_vision_generate_prompt,
    character_vision_stylize_prompt,
)
from grok_spicy.schemas import (
    Character,
    CharacterAsset,
    ConsistencyScore,
    PipelineConfig,
    VideoConfig,
)

logger = logging.getLogger(__name__)


@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)
def generate_character_sheet(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str | None = None,
    config: PipelineConfig | None = None,
    video_config: VideoConfig | None = None,
) -> CharacterAsset:
    """Generate a verified character reference portrait.

    Loop: generate portrait -> vision verify -> retry if score < threshold.
    Keeps the best result across all attempts.

    If reference_image_path is provided, uses single-image edit (stylize mode)
    to transform the reference photo into the art style while preserving likeness.
    """
    from xai_sdk.chat import image, user

    if config is None:
        config = PipelineConfig()

    mode = "stylize" if reference_image_path else "generate"
    max_attempts = config.max_char_attempts
    threshold = config.consistency_threshold
    logger.info(
        "Character sheet starting: name=%r, mode=%s, max_attempts=%d, threshold=%.2f",
        character.name,
        mode,
        max_attempts,
        threshold,
    )
    if reference_image_path:
        logger.debug("Reference image path: %s", reference_image_path)

    # ── DRY-RUN: write prompts, return mock ──
    if config.dry_run:
        from grok_spicy.dry_run import write_prompt

        if reference_image_path:
            gen_prompt = character_stylize_prompt(
                style, character.visual_description, video_config
            )
            vision_prompt = character_vision_stylize_prompt(character)
            write_prompt(
                "step2_characters",
                f"{character.name}_stylize",
                model=MODEL_IMAGE,
                prompt=gen_prompt,
                image_refs=[reference_image_path],
                api_params={"aspect_ratio": aspect_ratio},
            )
        else:
            gen_prompt = character_generate_prompt(
                style, character.visual_description, video_config
            )
            vision_prompt = character_vision_generate_prompt(character)
            write_prompt(
                "step2_characters",
                f"{character.name}_generate",
                model=MODEL_IMAGE,
                prompt=gen_prompt,
                api_params={"aspect_ratio": aspect_ratio},
            )
        write_prompt(
            "step2_characters",
            f"{character.name}_vision_check",
            model=MODEL_REASONING,
            prompt=vision_prompt,
        )
        logger.info("Dry-run: wrote character prompts for %r", character.name)
        return CharacterAsset(
            name=character.name,
            portrait_url="dry-run://placeholder",
            portrait_path=f"output/character_sheets/{character.name}_dry_run.jpg",
            visual_description=character.visual_description,
            consistency_score=1.0,
            generation_attempts=0,
        )

    client = get_client()
    best: dict = {"score": 0.0, "url": "", "path": ""}
    attempt = 0

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Character %r attempt %d/%d (mode=%s)",
            character.name,
            attempt,
            max_attempts,
            mode,
        )

        if reference_image_path:
            prompt = character_stylize_prompt(
                style, character.visual_description, video_config
            )
            logger.info("Stylize prompt: %s", prompt)
            ref_b64 = f"data:image/jpeg;base64,{to_base64(reference_image_path)}"
            logger.debug("Encoded reference image to base64 data URI")
            sample_kw: dict[str, Any] = dict(
                model=MODEL_IMAGE,
                image_url=ref_b64,
                aspect_ratio=aspect_ratio,
            )
        else:
            prompt = character_generate_prompt(
                style, character.visual_description, video_config
            )
            logger.info("Generate prompt: %s", prompt)
            sample_kw = dict(model=MODEL_IMAGE, aspect_ratio=aspect_ratio)

        img, prompt, still_moderated = generate_with_moderation_retry(
            client.image.sample, prompt, **sample_kw
        )
        if still_moderated:
            logger.warning(
                "Character %r attempt %d: still moderated after rewords, "
                "skipping attempt",
                character.name,
                attempt,
            )
            continue

        logger.debug("Image generated, URL=%s", img.url[:80])
        path = download(
            img.url,
            f"output/character_sheets/{character.name}_v{attempt}.jpg",
        )

        # Vision verify
        chat = client.chat.create(model=MODEL_REASONING)
        if reference_image_path:
            vision_prompt = character_vision_stylize_prompt(character)
            logger.info(
                "Vision verify (ref comparison, model=%s, character=%r): %s",
                MODEL_REASONING,
                character.name,
                vision_prompt,
            )
            chat.append(
                user(
                    vision_prompt,
                    image(img.url),
                    image(ref_b64),
                )
            )
        else:
            vision_prompt = character_vision_generate_prompt(character)
            logger.info(
                "Vision verify (text-only, model=%s, character=%r): %s",
                MODEL_REASONING,
                character.name,
                vision_prompt,
            )
            chat.append(
                user(
                    vision_prompt,
                    image(img.url),
                )
            )
        _, score = chat.parse(ConsistencyScore)

        logger.info(
            "Character %r attempt %d: score=%.2f (threshold=%.2f), issues=%s",
            character.name,
            attempt,
            score.overall_score,
            threshold,
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

        if score.overall_score >= threshold:
            logger.info(
                "Character %r passed threshold at attempt %d (score=%.2f >= %.2f)",
                character.name,
                attempt,
                score.overall_score,
                threshold,
            )
            break
    else:
        logger.warning(
            "Character %r exhausted all %d attempts, using best score=%.2f",
            character.name,
            max_attempts,
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
