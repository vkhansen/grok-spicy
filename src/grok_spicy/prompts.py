"""Prompt builders -- pure functions, one per pipeline prompt."""

from __future__ import annotations

# ─── Step 2: Character sheets ───────────────────────────────


def character_stylize_prompt(style: str, visual_description: str) -> str:
    return (
        f"{style}. Transform this photo into a full body character "
        f"portrait while preserving the person's exact facial features, "
        f"face shape, and likeness. Keep the following appearance details "
        f"accurate: {visual_description}. "
        f"Standing in a neutral three-quarter pose against a plain "
        f"light gray background. Professional character design "
        f"reference sheet style. Sharp details, even studio lighting, "
        f"no background clutter, no text or labels."
    )


def character_generate_prompt(style: str, visual_description: str) -> str:
    return (
        f"{style}. Full body character portrait of "
        f"{visual_description}. "
        f"Standing in a neutral three-quarter pose against a plain "
        f"light gray background. Professional character design "
        f"reference sheet style. Sharp details, even studio lighting, "
        f"no background clutter, no text or labels."
    )


def character_vision_stylize_prompt(visual_description: str) -> str:
    return (
        f"Score how well the first image (generated portrait) preserves "
        f"the person's likeness from the second image (reference photo). "
        f"Be strict on: facial features, face shape, hair color/style, "
        f"eye color, skin tone, build, distinguishing marks.\n\n"
        f"Also check these appearance details: "
        f"{visual_description}"
    )


def character_vision_generate_prompt(visual_description: str) -> str:
    return (
        f"Score how well this portrait matches the description. "
        f"Be strict on: hair color/style, eye color, clothing "
        f"colors and style, build, distinguishing features.\n\n"
        f"Description: {visual_description}"
    )


# ─── Step 3: Keyframes ─────────────────────────────────────


def keyframe_compose_prompt(
    plan_style: str,
    scene_title: str,
    scene_prompt_summary: str,
    scene_setting: str,
    scene_mood: str,
    scene_action: str,
    scene_camera: str,
    color_palette: str,
    char_lines: list[str],
) -> str:
    return (
        f"{plan_style}. "
        f"Scene: {scene_title} — {scene_prompt_summary} "
        f"Setting: {scene_setting}. {scene_mood}. "
        f"{'. '.join(char_lines)}. "
        f"Action: {scene_action}. "
        f"Camera: {scene_camera}. "
        f"Color palette: {color_palette}. "
        f"Maintain exact character appearances from the reference images."
    )


def build_video_prompt(
    prompt_summary: str,
    camera: str,
    action: str,
    mood: str,
    style: str,
    duration_seconds: int,
) -> str:
    base = (
        f"{prompt_summary} "
        f"{camera}. {action}. "
        f"{mood}. {style}. "
        f"Smooth cinematic motion."
    )
    if duration_seconds <= 8:
        return base

    mid = duration_seconds // 2
    parts = action.split(";", 1)
    if len(parts) == 2:
        phase1 = parts[0].strip()
        phase2 = parts[1].strip()
    else:
        phase1 = action
        phase2 = prompt_summary

    return (
        f"{style}. "
        f"Phase 1 (0-{mid}s): {phase1}. "
        f"Phase 2 ({mid}-{duration_seconds}s): {phase2}. "
        f"{camera}. {mood}. "
        f"Smooth cinematic motion throughout. "
        f"Maintain: {action}. "
        f"No sudden scene changes. No freeze frames. No unrelated motion."
    )


def keyframe_vision_prompt() -> str:
    return (
        "Image 1 is a scene. Images 2+ are character references. "
        "Score how well characters in the scene match their refs. "
        "If issues, provide a surgical fix prompt."
    )


def video_vision_prompt() -> str:
    return (
        "Image 1 is a video's last frame. Images 2+ are character "
        "refs. Has the character drifted? Score consistency."
    )


# ─── Fix / retry prompts ───────────────────────────────────


def fix_prompt_from_issues(issues: list[str], fix_text: str | None) -> str:
    if fix_text:
        return fix_text
    return f"Fix ONLY these issues, keep everything else identical: {'; '.join(issues)}"


def video_fix_prompt(issues: list[str], fix_text: str | None) -> str:
    if fix_text:
        return fix_text
    return f"Fix: {'; '.join(issues)}"


def extended_retry_prompt(base_prompt: str, issues: list[str]) -> str:
    if issues:
        return f"{base_prompt} Fix: {'; '.join(issues)}"
    return base_prompt


# ─── Negative prompt utility ───────────────────────────────


def append_negative_prompt(prompt: str, negative: str | None) -> str:
    if not negative:
        return prompt
    return f"{prompt} Avoid: {negative}"


# ─── Step 1: Ideation ──────────────────────────────────────


def ideation_user_message(
    concept: str,
    ref_descriptions: dict[str, str] | None = None,
) -> str:
    msg = f"Create a visual story plan for: {concept}"
    if ref_descriptions:
        desc_block = "\n".join(
            f"- {name}: {desc}" for name, desc in ref_descriptions.items()
        )
        msg += (
            f"\n\nThe following visual descriptions were extracted from the "
            f"user's reference photos. Copy each one verbatim into the "
            f"visual_description field for the corresponding character:\n"
            f"{desc_block}\n\n"
            f"IMPORTANT: Character appearance is already fully defined above. "
            f"Your scene descriptions must focus ENTIRELY on narrative events, "
            f"actions, emotions, and story progression — do NOT describe what "
            f"characters look like in scene text."
        )
    return msg


# ─── Pre-ideation: Describe reference ──────────────────────


def describe_ref_user_prompt(name: str) -> str:
    return (
        f"Describe the person in this reference photo. "
        f"The character's name is '{name}'."
    )
