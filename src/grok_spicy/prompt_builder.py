"""Spicy-mode prompt composer — builds prompts from VideoConfig."""

from __future__ import annotations

import logging

from grok_spicy.schemas import VideoConfig

logger = logging.getLogger(__name__)

# Modifier counts per intensity level
_INTENSITY_MODIFIER_LIMIT: dict[str, int | None] = {
    "low": 1,
    "medium": 2,
    "high": None,  # all modifiers
    "extreme": None,  # all modifiers + extra emphasis
}


def build_spicy_prompt(
    config: VideoConfig,
    character_ids: list[str] | None = None,
    scene_override: str | None = None,
) -> str:
    """Compose a full spicy-mode prompt from the VideoConfig.

    Character count logic:
    - 0 characters → scene/video defaults + global modifiers only
    - 1 character  → single-focus prompt with description + traits
    - 2+ characters → interaction-focused prompt combining descriptions

    Args:
        config: The loaded VideoConfig.
        character_ids: List of character IDs to include. ``None`` or
            empty list means "use all characters from config".
        scene_override: Override the default scene description.

    Returns:
        Fully composed prompt string ready for API calls.
    """
    spicy = config.spicy_mode

    # Select modifiers based on intensity
    limit = _INTENSITY_MODIFIER_LIMIT.get(spicy.intensity)
    modifiers = spicy.enabled_modifiers[:limit] if limit else spicy.enabled_modifiers

    # Resolve characters
    char_map = {c.id: c for c in config.characters}
    if character_ids:
        selected = [char_map[cid] for cid in character_ids if cid in char_map]
    else:
        selected = list(config.characters)

    # Scene
    scene = scene_override or config.default_video.scene

    # Build prompt parts
    parts: list[str] = []

    # Global prefix
    if spicy.global_prefix:
        parts.append(spicy.global_prefix)

    if len(selected) == 0:
        # No characters — pure scene/style prompt
        logger.debug("Spicy prompt: 0 characters (scene-only)")
        if scene:
            parts.append(scene)
        if config.default_video.motion:
            parts.append(config.default_video.motion)
    elif len(selected) == 1:
        # Single character focus
        char = selected[0]
        logger.debug("Spicy prompt: 1 character (%s)", char.name)
        parts.append(char.description)
        if char.spicy_traits:
            parts.append(", ".join(char.spicy_traits))
        if scene:
            parts.append(f"Setting: {scene}")
        if config.default_video.motion:
            parts.append(config.default_video.motion)
    else:
        # Multi-character interaction
        logger.debug(
            "Spicy prompt: %d characters (%s)",
            len(selected),
            ", ".join(c.name for c in selected),
        )
        char_descs = []
        all_traits: list[str] = []
        for char in selected:
            char_descs.append(f"{char.name}: {char.description}")
            all_traits.extend(char.spicy_traits)
        parts.append(" interacting with ".join(char_descs))
        if all_traits:
            parts.append(", ".join(all_traits))
        if scene:
            parts.append(f"Setting: {scene}")
        if config.default_video.motion:
            parts.append(config.default_video.motion)

    # Append modifiers
    if modifiers:
        parts.append(", ".join(modifiers))

    # Extreme intensity: add emphasis wrapper from config
    if spicy.intensity == "extreme" and modifiers and spicy.extreme_emphasis:
        parts.append(spicy.extreme_emphasis)

    prompt = ". ".join(p.rstrip(". ") for p in parts if p) + "."
    logger.info(
        "Built spicy prompt (%d chars, %d characters, intensity=%s): %.200s",
        len(prompt),
        len(selected),
        spicy.intensity,
        prompt,
    )
    return prompt
