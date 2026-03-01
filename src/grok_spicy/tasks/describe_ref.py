"""Pre-ideation: extract visual descriptions from reference photos."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import MODEL_REASONING, get_client, to_base64
from grok_spicy.prompts import describe_ref_user_prompt
from grok_spicy.schemas import CharacterDescription, PipelineConfig

logger = logging.getLogger(__name__)

DESCRIBE_PROMPT = (
    "You are a precise visual analyst. The user has provided a reference photo "
    "of a character. Describe ONLY what you see in the photo — do not invent "
    "or embellish details that are not visible.\n\n"
    "Your visual_description must be at least 80 words and include:\n"
    "- Age range, gender, ethnicity/skin tone\n"
    "- Hair: color, style, length\n"
    "- Eye color (if visible)\n"
    "- Facial features: nose shape, jawline, face shape\n"
    "- Body build\n"
    "- Exact clothing: colors, materials, accessories\n"
    "- Any distinguishing marks: scars, tattoos, glasses, jewelry\n\n"
    "Use the same format as a character visual_description field — "
    "this text will be used verbatim in image generation prompts."
)


@task(name="describe-reference-image", retries=2, retry_delay_seconds=10)
def describe_reference_image(
    name: str,
    image_path: str,
    config: PipelineConfig | None = None,
) -> CharacterDescription:
    """Send a reference photo to vision model and extract a factual description."""
    if config is None:
        config = PipelineConfig()

    logger.info("Describing reference image: name=%r, path=%s", name, image_path)

    user_prompt = describe_ref_user_prompt(name)

    # ── DRY-RUN: write prompts, return mock ──
    if config.dry_run:
        from grok_spicy.dry_run import write_prompt

        write_prompt(
            "step0_describe_ref",
            name,
            model=MODEL_REASONING,
            system_prompt=DESCRIBE_PROMPT,
            user_message=user_prompt,
            image_refs=[image_path],
            run_dir=config.run_dir,
        )
        logger.info("Dry-run: wrote describe_ref prompt for %r", name)
        return CharacterDescription(
            name=name,
            visual_description=(
                f"[DRY-RUN] Placeholder visual description for {name} "
                f"(source: {image_path}). In a real run, the vision model would "
                f"extract an 80+ word description from the reference photo."
            ),
        )

    from xai_sdk.chat import image, system, user

    client = get_client()
    ref_b64 = f"data:image/jpeg;base64,{to_base64(image_path)}"

    chat = client.chat.create(model=MODEL_REASONING)
    chat.append(system(DESCRIBE_PROMPT))
    chat.append(
        user(
            user_prompt,
            image(ref_b64),
        )
    )

    _, description = chat.parse(CharacterDescription)
    result: CharacterDescription = description

    logger.info(
        "Reference description extracted: name=%r, desc_len=%d words",
        result.name,
        len(result.visual_description.split()),
    )
    logger.debug(
        "Extracted description for %r: %s",
        name,
        result.visual_description[:200],
    )

    return result
