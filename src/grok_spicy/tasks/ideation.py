"""Step 1: Story ideation — concept string to structured StoryPlan."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import MODEL_STRUCTURED, get_client
from grok_spicy.schemas import StoryPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a visual storytelling director. The user will give you a concept "
    "for a short animated video. Turn their concept into a production-ready "
    "story plan.\n\n"
    "Concept fidelity:\n"
    "- Build the story entirely from what the user described: their characters, "
    "their setting, their events, their tone.\n"
    "- Use the user's exact character names when provided.\n"
    "- Expand on their idea with scene-level detail while staying within the "
    "boundaries of what they wrote.\n"
    "- Derive the style field from the aesthetic the concept itself implies "
    "(e.g. a dark gritty concept gets dark cinematic realism; a whimsical "
    "concept gets bright stylized animation). Use genre labels only when the "
    "concept explicitly names them.\n"
    "- Derive the color_palette from colors and atmosphere present in the "
    "concept text.\n"
    "- Extract scene settings, moods, and actions directly from the concept. "
    "When the concept describes events in sequence, map those to scenes.\n\n"
    "Character visual descriptions:\n"
    "- When the user provides pre-extracted reference descriptions, copy them "
    "verbatim into the visual_description field — they are already precise "
    "and complete.\n"
    "- When no reference description exists for a character, write an "
    "exhaustive visual description (minimum 80 words) covering: age range, "
    "gender, ethnicity/skin tone, hair (color, style, length), eye color, "
    "facial features, body build, exact clothing (colors, materials, "
    "accessories), and any distinguishing marks. This description is the sole "
    "appearance reference for all image generation.\n\n"
    "Production rules:\n"
    "- Design scenes for 8-second video clips, each with one clear action.\n"
    "- Limit to 2-3 characters and 3-5 scenes for best visual quality.\n"
    "- The style field must be specific (e.g. 'Pixar-style 3D animation with "
    "soft volumetric lighting').\n"
    "- Each scene's action should describe one clear motion suitable for video."
)


@task(
    name="plan-story",
    retries=2,
    retry_delay_seconds=10,
)
def plan_story(
    concept: str,
    ref_descriptions: dict[str, str] | None = None,
) -> StoryPlan:
    """Generate a structured StoryPlan from a concept string.

    If ref_descriptions is provided (name -> visual description extracted from
    reference photos), those descriptions are injected into the prompt so the
    LLM uses them verbatim instead of hallucinating appearance details.
    """
    from xai_sdk.chat import system, user

    logger.info("Ideation starting — model=%s", MODEL_STRUCTURED)
    logger.info("Ideation concept: %s", concept)
    if ref_descriptions:
        logger.info(
            "Ideation ref_descriptions provided for: %s",
            list(ref_descriptions.keys()),
        )
    logger.info("Ideation system prompt: %s", SYSTEM_PROMPT)

    user_message = f"Create a visual story plan for: {concept}"

    if ref_descriptions:
        desc_block = "\n".join(
            f"- {name}: {desc}" for name, desc in ref_descriptions.items()
        )
        user_message += (
            f"\n\nThe following visual descriptions were extracted from the "
            f"user's reference photos. Copy each one verbatim into the "
            f"visual_description field for the corresponding character:\n"
            f"{desc_block}"
        )
        logger.debug("Ideation user message with ref descriptions: %s", user_message)

    client = get_client()
    chat = client.chat.create(model=MODEL_STRUCTURED)
    chat.append(system(SYSTEM_PROMPT))
    chat.append(user(user_message))

    logger.debug("Calling chat.parse(StoryPlan) for structured output")
    _, plan = chat.parse(StoryPlan)
    result: StoryPlan = plan

    logger.info(
        "Ideation complete — title=%r, style=%r, characters=%d, scenes=%d, "
        "aspect=%s, palette=%r",
        result.title,
        result.style,
        len(result.characters),
        len(result.scenes),
        result.aspect_ratio,
        result.color_palette,
    )
    return result
