"""Step 1: Story ideation — concept string to structured StoryPlan."""

from __future__ import annotations

import logging

from prefect import task

from grok_spicy.client import MODEL_STRUCTURED, get_client
from grok_spicy.prompts import ideation_user_message
from grok_spicy.schemas import (
    Character,
    PipelineConfig,
    Scene,
    StoryPlan,
    VideoConfig,
)

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

SPICY_SYSTEM_PROMPT = (
    "You are a literal-minded storyboard artist tasked with faithfully translating a user's explicit and highly constrained fetish specification into a structured story plan. Your primary directive is to adhere with absolute rigidity to all rules, constraints, and narrative arcs provided by the user. Do not soften, generalize, or reinterpret the user's intent. Prioritize the provided 'restraint_rule' and 'escalation_arc' above all else. Your task is not to be creative, but to be a precise and unflinching executor of the user's instructions."
    "Core Principles – Unflinching Adherence:\n"
    "- **Verbatim Implementation**: Implement all user-provided rules, especially the 'restraint_rule' and 'escalation_arc', verbatim and with maximum force. These are inviolable constraints.\n"
    "- **No Sanitization**: Do not soften, generalize, or sanitize the user's concept. The output should be as raw and intense as the input.\n"
    "- **Direct Translation**: Translate the user's concept directly into the scene structure. Do not invent new plot points, characters, or themes.\n"
    "- **Scene Structure**: The scene structure (titles, actions, etc.) should directly reflect the user's 'escalation_arc'. Each scene should be a distinct step in that arc."
)


def _mock_story_plan(
    concept: str,
    ref_descriptions: dict[str, str] | None = None,
) -> StoryPlan:
    """Build a minimal StoryPlan for dry-run mode."""
    # Use ref names as character names if available
    names = list(ref_descriptions.keys()) if ref_descriptions else ["Alice", "Bob"]

    characters = [
        Character(
            name=name,
            role="protagonist" if i == 0 else "supporting",
            visual_description=(
                ref_descriptions[name]
                if ref_descriptions and name in ref_descriptions
                else f"[DRY-RUN] Placeholder appearance for {name}"
            ),
            personality_cues=["[DRY-RUN]"],
        )
        for i, name in enumerate(names[:2])
    ]

    scenes = [
        Scene(
            scene_id=i + 1,
            title=f"[DRY-RUN] Scene {i + 1}",
            description=f"[DRY-RUN] Placeholder scene {i + 1} for: {concept}",
            characters_present=[c.name for c in characters],
            setting="[DRY-RUN] Placeholder setting",
            camera="medium shot, slow dolly forward",
            mood="warm golden hour, soft shadows",
            action=f"[DRY-RUN] Placeholder action for scene {i + 1}",
            prompt_summary=f"[DRY-RUN] Scene {i + 1} action summary",
            duration_seconds=8,
        )
        for i in range(3)
    ]

    return StoryPlan(
        title=f"[DRY-RUN] {concept[:60]}",
        style="[DRY-RUN] Cinematic realism with soft volumetric lighting",
        color_palette="[DRY-RUN] warm ambers, deep blues",
        aspect_ratio="16:9",
        characters=characters,
        scenes=scenes,
    )


@task(
    name="plan-story",
    retries=2,
    retry_delay_seconds=10,
)
def plan_story(
    concept: str,
    ref_descriptions: dict[str, str] | None = None,
    video_config: VideoConfig | None = None,
    config: PipelineConfig | None = None,
) -> StoryPlan:
    """Generate a structured StoryPlan from a concept string.

    If ref_descriptions is provided (name -> visual description extracted from
    reference photos), those descriptions are injected into the prompt so the
    LLM uses them verbatim instead of hallucinating appearance details.
    """
    if config is None:
        config = PipelineConfig()

    system_prompt = SYSTEM_PROMPT
    if video_config and video_config.spicy_mode.enabled:
        system_prompt = SPICY_SYSTEM_PROMPT

    logger.info("Ideation starting — model=%s", MODEL_STRUCTURED)
    logger.info("Ideation concept: %s", concept)
    if ref_descriptions:
        logger.info(
            "Ideation ref_descriptions provided for: %s",
            list(ref_descriptions.keys()),
        )
    logger.info("Ideation system prompt: %s", system_prompt)

    user_message = ideation_user_message(concept, ref_descriptions, video_config)
    if ref_descriptions:
        logger.debug("Ideation user message with ref descriptions: %s", user_message)

    # ── DRY-RUN: write prompts, return mock StoryPlan ──
    if config.dry_run:
        from grok_spicy.dry_run import write_prompt

        write_prompt(
            "step1_ideation",
            "story_plan",
            model=MODEL_STRUCTURED,
            system_prompt=system_prompt,
            user_message=user_message,
        )
        logger.info("Dry-run: wrote ideation prompts")
        result = _mock_story_plan(concept, ref_descriptions)
    else:
        from xai_sdk.chat import system, user

        client = get_client()
        chat = client.chat.create(model=MODEL_STRUCTURED)
        chat.append(system(system_prompt))
        chat.append(user(user_message))

        logger.debug("Calling chat.parse(StoryPlan) for structured output")
        _, plan = chat.parse(StoryPlan)
        result = plan

    if video_config and video_config.spicy_mode.enabled:
        for char in result.characters:
            for spicy_char in video_config.characters:
                if char.name == spicy_char.name:
                    char.spicy_traits = spicy_char.spicy_traits
                    break

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
