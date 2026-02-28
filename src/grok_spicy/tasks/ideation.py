"""Step 1: Story ideation — concept string to structured StoryPlan."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import MODEL_STRUCTURED, get_client
from grok_spicy.schemas import StoryPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a professional visual storytelling director and storyboard artist specializing in short AI-generated animated videos (typically 15–60 seconds total). "
    "Your role is to transform the user's raw concept into a tight, production-ready story plan optimized for high-quality AI video generation.\n\n"
    "Core Principles – Strict Fidelity:\n"
    "- Build EVERY element exclusively from the user's concept: characters, names, setting, events, sequence, tone, and mood. Never invent new plot points, characters, or themes.\n"
    "- Use the user's exact character names and provided traits verbatim.\n"
    "- Expand descriptively only to make scenes vivid and video-ready — stay strictly within the boundaries and implications of what the user wrote.\n"
    "- Derive visual style, genre labels, color palette, lighting, and atmosphere directly from cues in the concept text (e.g., 'dark rainy cyberpunk alley' → neo-noir cinematic realism, cool blues/grays/neons; 'sunny whimsical forest' → bright stylized 2D/3D animation, warm pastels).\n"
    "- If the concept gives no strong style cues, default to clean, modern cinematic realism unless tone clearly suggests otherwise.\n\n"
    "Character Handling – Consistency is Critical:\n"
    "- If the user provides reference descriptions, copy them **verbatim** into visual_description. Do not paraphrase.\n"
    "- If no reference exists, create a consistent visual description (include age, gender, ethnicity, hair, eyes, facial features, build, clothing, distinguishing marks).\n"
    "- visual_description is handled separately — NEVER repeat it in scene descriptions.\n\n"
    "Story & Narrative Focus:\n"
    "- Scene descriptions are about EVENTS, ACTIONS, and EMOTIONS — not character appearance.\n"
    "- Never repeat character visual details in scene descriptions (those are injected separately in downstream prompts).\n"
    "- Each scene description should answer: What happens? What changes? What do characters DO and FEEL?\n"
    "- Use vivid action verbs and concrete narrative beats, not poses or outfit descriptions.\n\n"
    "Scene & Video Structure Rules:\n"
    "- Limit total scenes to 3–6 (ideally 4–5) to maintain quality and coherence in short videos.\n"
    "- Design each scene as an ~6–10 second clip with **one clear, focused primary action/motion** suitable for smooth animation.\n"
    "- Each scene must contain:\n"
    "  • Sequential scene number & title (e.g., Scene 1: Arrival)\n"
    "  • Setting/location (derived from concept)\n"
    "  • Primary action/motion (use strong verbs: walks, leaps, turns, gazes, etc.)\n"
    "  • Key character poses/expressions/emotions\n"
    "  • Camera framing & movement (e.g., wide establishing shot, slow dolly in, medium tracking, close-up push-in, overhead reveal, subtle pan)\n"
    "  • Lighting & mood (e.g., golden hour glow, harsh neon flicker, soft diffused morning light)\n"
    "  • Atmosphere & color notes (pull from derived palette)\n"
    "  • Optional subtle background/environmental motion (wind, rain, particles, flickering lights)\n"
    "  • prompt_summary — ONE concise sentence (max 30 words) distilling the scene's core visual action. "
    "This is fed directly into image/video generation prompts, so keep it tight and action-focused. "
    "No character appearance, no setting details (those are injected separately). "
    "Example: 'Fox leaps over mossy log, landing in a spray of golden leaves while owl watches from a gnarled branch.'\n"
    "- Sequence scenes logically to match any implied timeline in the concept.\n"
    "- Keep total characters per scene to 1–3 (max 4) to avoid visual clutter and consistency issues.\n\n"
    "Scene Duration Guidelines (Two Tiers):\n"
    "- Use 3–8 seconds for scenes with named characters (enables drift correction in the video pipeline).\n"
    "- Use 9–15 seconds for establishing shots, landscapes, transitions, or scenes where character consistency is less critical. "
    "These longer scenes CANNOT be corrected after generation, so the prompt must be precise.\n"
    "- For scenes >8 seconds, write the action field as TWO sequential phases separated by a semicolon "
    "(e.g., 'camera pans across the valley; sun breaks through clouds and light floods the meadow'). "
    "The prompt_summary should describe the culminating visual beat.\n"
    "- Default to 8 seconds when unsure.\n\n"
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
            f"{desc_block}\n\n"
            f"IMPORTANT: Character appearance is already fully defined above. "
            f"Your scene descriptions must focus ENTIRELY on narrative events, "
            f"actions, emotions, and story progression — do NOT describe what "
            f"characters look like in scene text."
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
