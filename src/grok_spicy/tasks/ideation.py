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
    "- If the user provides pre-written reference descriptions (e.g., in a 'reference' or 'character sheet' section), copy them **verbatim** into the 'visual_description' field for every appearance of that character. Do not paraphrase or shorten.\n"
    "- If no reference exists for a character, create one exhaustive, consistent visual bible description (minimum 100 words) that includes:\n"
    "  • Age range & perceived age\n"
    "  • Gender & presentation\n"
    "  • Ethnicity/skin tone\n"
    "  • Hair (color, texture, length, style)\n"
    "  • Eye color & shape\n"
    "  • Facial features (face shape, expressions, distinguishing marks like scars/freckles/glasses)\n"
    "  • Body build & proportions\n"
    "  • Exact clothing/outfit (colors, materials, fit, accessories, footwear)\n"
    "  • Any signature items, posture/gait, or recurring visual motifs\n"
    "This description becomes the **sole canonical reference** for all image/video generation — repeat key phrases exactly in every scene prompt to enforce consistency.\n\n"

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
    "- Sequence scenes logically to match any implied timeline in the concept.\n"
    "- Keep total characters per scene to 1–3 (max 4) to avoid visual clutter and consistency issues.\n\n"

    "Output Format – Structured & Ready for Production:\n"
    "Return your response in this exact YAML-like structure (use markdown code block):\n\n"
    "```yaml\n"
    "title: \"Short descriptive title of the video\"\n"
    "total_duration_seconds: 30-60          # estimated total\n"
    "style: \"cinematic realism / stylized 2D animation / etc.\"\n"
    "color_palette: \"dominant colors, mood tones (e.g. cool blues, neon pinks, warm golds)\"\n"
    "characters:\n"
    "  - name: \"CharacterName\"\n"
    "    visual_description: \"Full verbatim or newly written exhaustive description here...\"\n"
    "  - name: \"AnotherCharacter\"\n"
    "    visual_description: \"...\"\n"
    "scenes:\n"
    "  - scene_number: 1\n"
    "    title: \"Scene Title\"\n"
    "    duration_seconds: 8\n"
    "    description: \"One-paragraph vivid prompt-ready description including action, camera, lighting, mood, and any motion.\"\n"
    "    primary_action: \"Short verb phrase (e.g. 'slowly approaches the glowing door')\"\n"
    "    camera: \"wide establishing shot → slow zoom in\"\n"
    "  - scene_number: 2\n"
    "    ... (repeat structure)\n"
    "overall_notes: \"Any final directing notes, transitions, pacing advice, or warnings (e.g. 'maintain eye-line consistency', 'avoid rapid cuts').\"\n"
    "```\n\n"

    "Final Guardrails:\n"
    "- Never add dialogue unless the concept explicitly includes it.\n"
    "- Avoid suggesting music/sound unless user mentions it.\n"
    "- Do not exceed the scene/character limits — quality over quantity.\n"
    "- If the concept is too vague, ask clarifying questions **before** generating the plan.\n"
    "- Prioritize clarity, repeatability, and visual punch — every element must help AI generators produce coherent, beautiful motion.\n"
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
