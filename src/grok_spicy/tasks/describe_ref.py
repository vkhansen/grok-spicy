"""Pre-ideation: extract visual descriptions from reference photos."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import MODEL_REASONING, get_client, to_base64
from grok_spicy.schemas import CharacterDescription

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
def describe_reference_image(name: str, image_path: str) -> CharacterDescription:
    """Send a reference photo to vision model and extract a factual description."""
    from xai_sdk.chat import image, system, user

    logger.info("Describing reference image: name=%r, path=%s", name, image_path)

    client = get_client()
    ref_b64 = f"data:image/jpeg;base64,{to_base64(image_path)}"

    chat = client.chat.create(model=MODEL_REASONING)
    chat.append(system(DESCRIBE_PROMPT))
    chat.append(
        user(
            f"Describe the person in this reference photo. "
            f"The character's name is '{name}'.",
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
