"""Unit tests for prompt builder functions."""

from grok_spicy.prompts import (
    append_negative_prompt,
    build_video_prompt,
    character_generate_prompt,
    character_stylize_prompt,
    character_vision_generate_prompt,
    character_vision_stylize_prompt,
    describe_ref_user_prompt,
    extended_retry_prompt,
    fix_prompt_from_issues,
    ideation_user_message,
    keyframe_compose_prompt,
    keyframe_vision_prompt,
    video_fix_prompt,
    video_vision_prompt,
)

# ─── Character prompts ─────────────────────────────────────


def test_character_stylize_prompt():
    result = character_stylize_prompt("Pixar 3D", "red hair, blue eyes")
    assert "Pixar 3D" in result
    assert "red hair, blue eyes" in result
    assert "Transform this photo" in result


def test_character_generate_prompt():
    result = character_generate_prompt("Anime", "tall, dark cloak")
    assert "Anime" in result
    assert "tall, dark cloak" in result
    assert "Full body character portrait" in result


def test_character_vision_stylize_prompt():
    result = character_vision_stylize_prompt("red hair, blue eyes")
    assert "likeness" in result
    assert "red hair, blue eyes" in result


def test_character_vision_generate_prompt():
    result = character_vision_generate_prompt("tall, dark cloak")
    assert "matches the description" in result
    assert "tall, dark cloak" in result


# ─── Keyframe prompts ──────────────────────────────────────


def test_keyframe_compose_prompt():
    result = keyframe_compose_prompt(
        plan_style="Pixar 3D",
        scene_title="Forest Chase",
        scene_prompt_summary="Fox runs through trees",
        scene_setting="Dense forest, dusk",
        scene_mood="Tense, blue shadows",
        scene_action="Fox sprints between oaks",
        scene_camera="tracking shot",
        color_palette="deep greens, amber",
        char_lines=["Fox (reference image 1), positioned on the center"],
    )
    assert "Pixar 3D" in result
    assert "Forest Chase" in result
    assert "Fox runs through trees" in result
    assert "deep greens, amber" in result


def test_build_video_prompt_standard():
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=8,
    )
    assert "Fox leaps" in result
    assert "Smooth cinematic motion" in result
    # Standard tier: no phases
    assert "Phase 1" not in result


def test_build_video_prompt_extended():
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps; Fox lands",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=12,
    )
    assert "Phase 1" in result
    assert "Phase 2" in result
    assert "Fox jumps" in result
    assert "Fox lands" in result


def test_build_video_prompt_extended_no_semicolon():
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps over log",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=10,
    )
    assert "Phase 1" in result
    # phase2 falls back to prompt_summary
    assert "Fox leaps" in result


def test_keyframe_vision_prompt():
    result = keyframe_vision_prompt()
    assert "Image 1 is a scene" in result
    assert "surgical fix prompt" in result


def test_video_vision_prompt():
    result = video_vision_prompt()
    assert "last frame" in result
    assert "drifted" in result


# ─── Fix / retry prompts ───────────────────────────────────


def test_fix_prompt_from_issues_with_fix_text():
    result = fix_prompt_from_issues(["hair wrong"], "Fix the hair color")
    assert result == "Fix the hair color"


def test_fix_prompt_from_issues_fallback():
    result = fix_prompt_from_issues(["hair wrong", "eyes wrong"], None)
    assert "Fix ONLY" in result
    assert "hair wrong" in result
    assert "eyes wrong" in result


def test_video_fix_prompt_with_fix_text():
    result = video_fix_prompt(["drift"], "Correct character drift")
    assert result == "Correct character drift"


def test_video_fix_prompt_fallback():
    result = video_fix_prompt(["drift", "color shift"], None)
    assert "Fix:" in result
    assert "drift" in result


def test_extended_retry_prompt_with_issues():
    result = extended_retry_prompt("base prompt", ["issue1"])
    assert result == "base prompt Fix: issue1"


def test_extended_retry_prompt_no_issues():
    result = extended_retry_prompt("base prompt", [])
    assert result == "base prompt"


# ─── Negative prompt ───────────────────────────────────────


def test_append_negative_prompt_with_value():
    result = append_negative_prompt("generate a scene", "No zoom")
    assert result == "generate a scene Avoid: No zoom"


def test_append_negative_prompt_none():
    result = append_negative_prompt("generate a scene", None)
    assert result == "generate a scene"


def test_append_negative_prompt_empty():
    result = append_negative_prompt("generate a scene", "")
    assert result == "generate a scene"


# ─── Ideation ──────────────────────────────────────────────


def test_ideation_user_message_basic():
    result = ideation_user_message("A fox adventure")
    assert "Create a visual story plan for: A fox adventure" in result
    assert "reference photos" not in result


def test_ideation_user_message_with_refs():
    result = ideation_user_message(
        "A fox adventure",
        ref_descriptions={"Fox": "orange fur, bushy tail"},
    )
    assert "A fox adventure" in result
    assert "Fox: orange fur, bushy tail" in result
    assert "verbatim" in result


# ─── Describe ref ──────────────────────────────────────────


def test_describe_ref_user_prompt():
    result = describe_ref_user_prompt("Alex")
    assert "Alex" in result
    assert "reference photo" in result
