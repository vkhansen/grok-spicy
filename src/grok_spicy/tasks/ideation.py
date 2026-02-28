"""Step 1: Story ideation — concept string to structured StoryPlan."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import MODEL_STRUCTURED, get_client
from grok_spicy.schemas import StoryPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a visual storytelling director. The user will give you a concept "
    "for a short animated video. Your job is to turn THEIR concept into a "
    "production-ready story plan.\n\n"
    "CRITICAL — Follow the user's concept faithfully:\n"
    "- The story MUST be about exactly what the user described. Do not substitute "
    "a different storyline, different characters, or a different setting.\n"
    "- If the user says 'a fox and an owl in a forest', the story is about a fox "
    "and an owl in a forest — not spies, not robots, not anything else.\n"
    "- Use the user's exact character names if they provided any.\n"
    "- Match the user's tone, genre, and setting. A whimsical prompt gets a "
    "whimsical story. A dark prompt gets a dark story.\n"
    "- Do NOT invent plot elements, themes, or characters that the user did not "
    "ask for. Expand on their idea with scene-level detail, but stay within the "
    "boundaries of what they described.\n"
    "- Do NOT invent visual styles, aesthetics, or settings that the user did not "
    "describe. If the concept describes a specific environment (e.g. a dungeon, "
    "a forest, an arena), use THAT setting — do not replace it with cyberpunk, "
    "sci-fi, fantasy, or any other genre the user did not mention.\n"
    "- The style field should match the aesthetic implied by the concept text. "
    "If the concept is dark and gritty, use a dark cinematic style — but do NOT "
    "add genre labels (cyberpunk, steampunk, etc.) unless the concept explicitly "
    "uses those words.\n"
    "- The color_palette should be derived from colors and atmosphere actually "
    "described in the concept, not invented from a genre template.\n"
    "- Scene settings, moods, and actions should be extracted directly from the "
    "concept text. If the concept describes specific events in sequence, turn "
    "those into scenes — do not replace them with different events.\n\n"
    "Production rules:\n"
    "- Every character needs an exhaustive visual description (minimum 80 words). "
    "Include: age range, gender, ethnicity/skin tone, hair (color, style, length), "
    "eye color, facial features, body build, exact clothing (colors, materials, "
    "accessories), and any distinguishing marks. This description is the SOLE "
    "appearance reference used for all image generation — be precise.\n"
    "- Design scenes for 8-second video clips with simple, clear, single actions.\n"
    "- Limit: 2-3 characters, 3-5 scenes for best visual quality.\n"
    "- The style field must be specific (e.g. 'Pixar-style 3D animation with "
    "soft volumetric lighting'), not vague ('animated'). But it must reflect the "
    "concept's own aesthetic — do not graft on an unrelated genre.\n"
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
            f"\n\nThe following visual descriptions were extracted from the user's "
            f"reference photos. You MUST use these VERBATIM as the "
            f"visual_description for the corresponding characters — do NOT "
            f"paraphrase, shorten, or invent different appearance details:\n"
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
