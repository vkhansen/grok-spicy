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
    character_enhance_prompt,
    character_generate_prompt,
    character_stylize_prompt,
    character_vision_enhance_prompt,
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


# ─── Internal helpers ─────────────────────────────────────


def _run_generation_loop(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str | None,
    config: PipelineConfig,
    video_config: VideoConfig | None,
    *,
    include_spicy_traits: bool = True,
    label: str = "",
) -> dict:
    """Core generate-or-stylize retry loop.

    Returns a dict with keys: score, url, path, attempt.
    """
    from xai_sdk.chat import image, user

    client = get_client()
    max_attempts = config.max_char_attempts
    threshold = config.consistency_threshold
    mode = "stylize" if reference_image_path else "generate"
    best: dict = {"score": 0.0, "url": "", "path": ""}
    attempt = 0

    traits = (character.spicy_traits or None) if include_spicy_traits else None

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Character %r %sattempt %d/%d (mode=%s)",
            character.name,
            f"({label}) " if label else "",
            attempt,
            max_attempts,
            mode,
        )

        if reference_image_path:
            prompt = character_stylize_prompt(
                style,
                character.visual_description,
                video_config,
                spicy_traits=traits,
            )
            logger.info("Stylize prompt: %s", prompt)
            ref_b64 = f"data:image/jpeg;base64,{to_base64(reference_image_path)}"
            sample_kw: dict[str, Any] = dict(
                model=MODEL_IMAGE,
                image_url=ref_b64,
                aspect_ratio=aspect_ratio,
            )
        else:
            prompt = character_generate_prompt(
                style,
                character.visual_description,
                video_config,
                spicy_traits=traits,
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
        suffix = f"_{label}" if label else ""
        path = download(
            img.url,
            f"{config.run_dir}/characters/{character.name}{suffix}_v{attempt}.jpg",
        )

        # Vision verify
        chat = client.chat.create(model=MODEL_REASONING)
        if reference_image_path:
            vision_prompt = character_vision_stylize_prompt(character)
            logger.info(
                "Vision verify (ref comparison, character=%r): %s",
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
                "Vision verify (text-only, character=%r): %s",
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
            "Character %r %sattempt %d: score=%.2f (threshold=%.2f), issues=%s",
            character.name,
            f"({label}) " if label else "",
            attempt,
            score.overall_score,
            threshold,
            score.issues if hasattr(score, "issues") and score.issues else "none",
        )

        if score.overall_score > best["score"]:
            best = {"score": score.overall_score, "url": img.url, "path": path}

        if score.overall_score >= threshold:
            break
    else:
        logger.warning(
            "Character %r %sexhausted all %d attempts, using best score=%.2f",
            character.name,
            f"({label}) " if label else "",
            max_attempts,
            best["score"],
        )

    best["attempt"] = attempt
    return best


def _run_enhancement_loop(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str,
    base_url: str,
    enhancements: str,
    config: PipelineConfig,
    video_config: VideoConfig | None,
) -> dict:
    """Enhancement pass: apply modifications to a base portrait.

    Returns a dict with keys: score, url, path, attempt.
    """
    from xai_sdk.chat import image, user

    client = get_client()
    max_attempts = config.max_char_attempts
    threshold = config.consistency_threshold
    best: dict = {"score": 0.0, "url": "", "path": ""}
    attempt = 0

    ref_b64 = f"data:image/jpeg;base64,{to_base64(reference_image_path)}"

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "Character %r (enhance) attempt %d/%d",
            character.name,
            attempt,
            max_attempts,
        )

        prompt = character_enhance_prompt(
            style,
            character.visual_description,
            enhancements,
            video_config,
            spicy_traits=character.spicy_traits or None,
        )
        logger.info("Enhance prompt: %s", prompt)

        # Use the base portrait as the input image for editing
        base_b64 = base_url
        if not base_url.startswith("data:"):
            # It's a URL from the API — use directly
            pass

        sample_kw: dict[str, Any] = dict(
            model=MODEL_IMAGE,
            image_url=base_b64,
            aspect_ratio=aspect_ratio,
        )

        img, prompt, still_moderated = generate_with_moderation_retry(
            client.image.sample, prompt, **sample_kw
        )
        if still_moderated:
            logger.warning(
                "Character %r (enhance) attempt %d: still moderated, skipping",
                character.name,
                attempt,
            )
            continue

        logger.debug("Enhanced image generated, URL=%s", img.url[:80])
        path = download(
            img.url,
            f"{config.run_dir}/characters/{character.name}_enhanced_v{attempt}.jpg",
        )

        # Vision verify — compare enhanced vs base vs reference
        chat = client.chat.create(model=MODEL_REASONING)
        vision_prompt = character_vision_enhance_prompt(character, enhancements)
        logger.info(
            "Vision verify (enhance, character=%r): %s",
            character.name,
            vision_prompt,
        )
        chat.append(
            user(
                vision_prompt,
                image(img.url),  # Image 1: enhanced portrait
                image(base_b64),  # Image 2: base portrait
                image(ref_b64),  # Image 3: original reference
            )
        )
        _, score = chat.parse(ConsistencyScore)

        logger.info(
            "Character %r (enhance) attempt %d: score=%.2f (threshold=%.2f), "
            "issues=%s",
            character.name,
            attempt,
            score.overall_score,
            threshold,
            score.issues if hasattr(score, "issues") and score.issues else "none",
        )

        if score.overall_score > best["score"]:
            best = {"score": score.overall_score, "url": img.url, "path": path}

        if score.overall_score >= threshold:
            break
    else:
        logger.warning(
            "Character %r (enhance) exhausted all %d attempts, best=%.2f",
            character.name,
            max_attempts,
            best["score"],
        )

    best["attempt"] = attempt
    return best


# ─── Main task ────────────────────────────────────────────


@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)
def generate_character_sheet(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str | None = None,
    enhancements: str | None = None,
    config: PipelineConfig | None = None,
    video_config: VideoConfig | None = None,
) -> CharacterAsset:
    """Generate a verified character reference portrait.

    Three cases:
      1. No reference image  -> generate from visual_description text
      2. Reference image, no enhancements -> stylize from photo
      3. Reference image + enhancements -> two-pass: base from photo, then
         enhance with outfit/modification changes

    The enhanced portrait (case 3) or single portrait (cases 1/2) is what
    flows downstream into keyframes and video generation.
    """
    if config is None:
        config = PipelineConfig()

    has_ref = reference_image_path is not None
    has_enhance = bool(enhancements)
    if has_ref and has_enhance:
        mode = "stylize+enhance"
    elif has_ref:
        mode = "stylize"
    else:
        mode = "generate"

    logger.info(
        "Character sheet starting: name=%r, mode=%s, threshold=%.2f",
        character.name,
        mode,
        config.consistency_threshold,
    )

    # ── DRY-RUN: write prompts, return mock ──
    if config.dry_run:
        return _dry_run(
            character,
            style,
            aspect_ratio,
            reference_image_path,
            enhancements,
            config,
            video_config,
            mode,
        )

    # ── CASE 3: Two-pass (stylize + enhance) ──
    if has_ref and has_enhance:
        # Pass 1: base sheet (identity only, no spicy traits)
        logger.info("Character %r: Pass 1 — base sheet (identity only)", character.name)
        base = _run_generation_loop(
            character,
            style,
            aspect_ratio,
            reference_image_path,
            config,
            video_config,
            include_spicy_traits=False,
            label="base",
        )
        logger.info(
            "Character %r: base sheet done — score=%.2f, attempts=%d, path=%s",
            character.name,
            base["score"],
            base["attempt"],
            base["path"],
        )

        # Pass 2: enhancement sheet
        logger.info(
            "Character %r: Pass 2 — enhancement (enhancements=%r)",
            character.name,
            enhancements,
        )
        enhanced = _run_enhancement_loop(
            character,
            style,
            aspect_ratio,
            reference_image_path,
            base["url"],
            enhancements,
            config,
            video_config,
        )
        logger.info(
            "Character %r: enhanced sheet done — score=%.2f, attempts=%d, path=%s",
            character.name,
            enhanced["score"],
            enhanced["attempt"],
            enhanced["path"],
        )

        total_attempts = base["attempt"] + enhanced["attempt"]
        return CharacterAsset(
            name=character.name,
            portrait_url=enhanced["url"],
            portrait_path=enhanced["path"],
            visual_description=character.visual_description,
            consistency_score=enhanced["score"],
            generation_attempts=total_attempts,
            base_portrait_path=base["path"],
            enhancement_applied=True,
            enhancements=[enhancements],
        )

    # ── CASE 1 or 2: Single pass ──
    result = _run_generation_loop(
        character,
        style,
        aspect_ratio,
        reference_image_path,
        config,
        video_config,
    )
    logger.info(
        "Character sheet done: name=%r, final_score=%.2f, attempts=%d, path=%s",
        character.name,
        result["score"],
        result["attempt"],
        result["path"],
    )

    return CharacterAsset(
        name=character.name,
        portrait_url=result["url"],
        portrait_path=result["path"],
        visual_description=character.visual_description,
        consistency_score=result["score"],
        generation_attempts=result["attempt"],
    )


def _dry_run(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str | None,
    enhancements: str | None,
    config: PipelineConfig,
    video_config: VideoConfig | None,
    mode: str,
) -> CharacterAsset:
    """Write prompt files for dry-run mode and return a mock CharacterAsset."""
    from grok_spicy.dry_run import write_prompt

    if reference_image_path:
        gen_prompt = character_stylize_prompt(
            style,
            character.visual_description,
            video_config,
            spicy_traits=(character.spicy_traits or None) if not enhancements else None,
        )
        vision_prompt = character_vision_stylize_prompt(character)
        write_prompt(
            "step2_characters",
            f"{character.name}_stylize" + ("_base" if enhancements else ""),
            model=MODEL_IMAGE,
            prompt=gen_prompt,
            image_refs=[reference_image_path],
            api_params={"aspect_ratio": aspect_ratio},
            run_dir=config.run_dir,
        )
    else:
        gen_prompt = character_generate_prompt(
            style,
            character.visual_description,
            video_config,
            spicy_traits=character.spicy_traits or None,
        )
        vision_prompt = character_vision_generate_prompt(character)
        write_prompt(
            "step2_characters",
            f"{character.name}_generate",
            model=MODEL_IMAGE,
            prompt=gen_prompt,
            api_params={"aspect_ratio": aspect_ratio},
            run_dir=config.run_dir,
        )

    write_prompt(
        "step2_characters",
        f"{character.name}_vision_check" + ("_base" if enhancements else ""),
        model=MODEL_REASONING,
        prompt=vision_prompt,
        run_dir=config.run_dir,
    )

    # Write enhancement prompts if Case 3
    if enhancements and reference_image_path:
        enhance_gen = character_enhance_prompt(
            style,
            character.visual_description,
            enhancements,
            video_config,
            spicy_traits=character.spicy_traits or None,
        )
        enhance_vis = character_vision_enhance_prompt(character, enhancements)
        write_prompt(
            "step2_characters",
            f"{character.name}_enhance",
            model=MODEL_IMAGE,
            prompt=enhance_gen,
            image_refs=["[base portrait from Pass 1]"],
            api_params={"aspect_ratio": aspect_ratio},
            run_dir=config.run_dir,
        )
        write_prompt(
            "step2_characters",
            f"{character.name}_vision_check_enhance",
            model=MODEL_REASONING,
            prompt=enhance_vis,
            run_dir=config.run_dir,
        )

    logger.info(
        "Dry-run: wrote character prompts for %r (mode=%s)", character.name, mode
    )
    return CharacterAsset(
        name=character.name,
        portrait_url="dry-run://placeholder",
        portrait_path=f"{config.run_dir}/characters/{character.name}_dry_run.jpg",
        visual_description=character.visual_description,
        consistency_score=1.0,
        generation_attempts=0,
        base_portrait_path=(
            f"{config.run_dir}/characters/{character.name}_base_dry_run.jpg"
            if enhancements
            else None
        ),
        enhancement_applied=bool(enhancements),
        enhancements=[enhancements] if enhancements else [],
    )
