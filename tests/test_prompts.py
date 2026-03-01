"""Unit tests for prompt builder functions."""

from grok_spicy.prompt_builder import build_spicy_prompt
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
from grok_spicy.schemas import (
    Character,
    DefaultVideo,
    NarrativeCore,
    Scene,
    SpicyMode,
    VideoConfig,
)

# ─── Forbidden hardcoded content ──────────────────────────

FORBIDDEN_HARDCODED = [
    "Smooth cinematic motion",
    "even studio lighting",
    "Sharp details",
    "Professional character design reference sheet style",
    "extreme detail, maximum realism",
    "elegant evening wear",
    "fashionable outfits",
    "No sudden scene changes",
    "No freeze frames",
    "No unrelated motion",
]


# ─── Helpers ──────────────────────────────────────────────


def _make_video_config(style_directive: str = "") -> VideoConfig:
    return VideoConfig(
        spicy_mode=SpicyMode(
            enabled=True,
            enabled_modifiers=["modifier_a"],
            intensity="high",
            global_prefix="PREFIX: ",
        ),
        narrative_core=NarrativeCore(
            restraint_rule="test rule",
            escalation_arc="test arc",
            style_directive=style_directive,
        ),
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
    char = Character(
        id="char1",
        name="Test Character",
        role="protagonist",
        personality_cues=["brave"],
        visual_description="red hair, blue eyes",
        spicy_traits=["scars"],
    )
    result = character_vision_stylize_prompt(char)
    assert "likeness" in result
    assert "red hair, blue eyes" in result
    assert "scars" in result


def test_character_vision_generate_prompt():
    char = Character(
        id="char1",
        name="Test Character",
        role="antagonist",
        personality_cues=["cunning"],
        visual_description="tall, dark cloak",
        spicy_traits=["hooded"],
    )
    result = character_vision_generate_prompt(char)
    assert "matches the description" in result
    assert "tall, dark cloak" in result
    assert "hooded" in result


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
    assert "medium shot" in result
    assert "Fox jumps" in result
    assert "warm golden" in result
    assert "Pixar 3D" in result
    # Must NOT contain hardcoded content
    assert "Smooth cinematic motion" not in result
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
    scene = Scene(
        scene_id=1,
        title="Test Scene",
        description="A scene for testing.",
        characters_present=["char1"],
        setting="A test setting.",
        camera="close-up",
        mood="dramatic",
        action="A test action.",
        prompt_summary="A test summary.",
        duration_seconds=5,
    )
    result = keyframe_vision_prompt(scene)
    assert "Image 1 is a scene" in result
    assert "surgical fix prompt" in result
    assert "A test action" in result


def test_video_vision_prompt():
    scene = Scene(
        scene_id=1,
        title="Test Scene",
        description="A scene for testing.",
        characters_present=["char1"],
        setting="A test setting.",
        camera="close-up",
        mood="dramatic",
        action="A test action.",
        prompt_summary="A test summary.",
        duration_seconds=5,
    )
    result = video_vision_prompt(scene)
    assert "last frame" in result
    assert "drifted" in result
    assert "A test action" in result


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


# ═══════════════════════════════════════════════════════════════
# NEW: No hardcoded content leak tests
# ═══════════════════════════════════════════════════════════════


def test_build_video_prompt_no_hardcoded_content():
    """Video prompts must not contain any hardcoded scene/motion/style content."""
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=8,
    )
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


def test_build_video_prompt_extended_no_hardcoded_content():
    """Extended video prompts must not contain any hardcoded content."""
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps; Fox lands",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=12,
    )
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


def test_character_stylize_prompt_no_hardcoded_content():
    """Character stylize prompts must not inject hardcoded aesthetics."""
    result = character_stylize_prompt("Dark cinematic", "red hair, blue eyes")
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


def test_character_generate_prompt_no_hardcoded_content():
    """Character generate prompts must not inject hardcoded aesthetics."""
    result = character_generate_prompt("Anime cel-shaded", "tall, dark cloak")
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


# ═══════════════════════════════════════════════════════════════
# NEW: Prompt composability — only user inputs appear in output
# ═══════════════════════════════════════════════════════════════


def test_build_video_prompt_only_contains_inputs():
    """Every content word in the output must originate from an input parameter."""
    result = build_video_prompt(
        prompt_summary="ALPHA_SUMMARY",
        camera="BETA_CAMERA",
        action="GAMMA_ACTION",
        mood="DELTA_MOOD",
        style="EPSILON_STYLE",
        duration_seconds=6,
    )
    assert "ALPHA_SUMMARY" in result
    assert "BETA_CAMERA" in result
    assert "GAMMA_ACTION" in result
    assert "DELTA_MOOD" in result
    assert "EPSILON_STYLE" in result


def test_character_generate_prompt_only_contains_inputs():
    """Character prompt output must only contain the style and description passed in."""
    result = character_generate_prompt("STYLE_TOKEN", "DESCRIPTION_TOKEN")
    assert "STYLE_TOKEN" in result
    assert "DESCRIPTION_TOKEN" in result


def test_character_stylize_prompt_only_contains_inputs():
    """Character stylize prompt must only contain the style and description passed in."""
    result = character_stylize_prompt("STYLE_TOKEN", "DESCRIPTION_TOKEN")
    assert "STYLE_TOKEN" in result
    assert "DESCRIPTION_TOKEN" in result


# ═══════════════════════════════════════════════════════════════
# NEW: style_directive injection from config
# ═══════════════════════════════════════════════════════════════


def test_build_video_prompt_with_style_directive():
    """style_directive from config must appear in video prompt output."""
    cfg = _make_video_config(style_directive="harsh rim lighting, cold blue palette")
    result = build_video_prompt(
        prompt_summary="summary",
        camera="tracking shot",
        action="action",
        mood="tense",
        style="cinematic",
        duration_seconds=6,
        video_config=cfg,
    )
    assert "harsh rim lighting, cold blue palette" in result


def test_character_generate_prompt_with_style_directive():
    """style_directive from config must appear in character prompt output."""
    cfg = _make_video_config(style_directive="dramatic shadows, crimson accents")
    result = character_generate_prompt("cinematic", "tall figure", video_config=cfg)
    assert "dramatic shadows, crimson accents" in result


def test_character_stylize_prompt_with_style_directive():
    """style_directive from config must appear in character stylize prompt output."""
    cfg = _make_video_config(style_directive="noir lighting")
    result = character_stylize_prompt("cinematic", "blue eyes", video_config=cfg)
    assert "noir lighting" in result


# ═══════════════════════════════════════════════════════════════
# NEW: extreme_emphasis from config (not hardcoded)
# ═══════════════════════════════════════════════════════════════


def test_extreme_emphasis_from_config():
    """Extreme emphasis text must come from config, not be hardcoded."""
    cfg = VideoConfig(
        spicy_mode=SpicyMode(
            enabled=True,
            enabled_modifiers=["modifier_a"],
            intensity="extreme",
            global_prefix="",
            extreme_emphasis="(CUSTOM EMPHASIS FROM CONFIG)",
        ),
        default_video=DefaultVideo(),
    )
    result = build_spicy_prompt(cfg)
    assert "(CUSTOM EMPHASIS FROM CONFIG)" in result
    assert "(extreme detail, maximum realism)" not in result


def test_extreme_no_emphasis_when_field_empty():
    """No emphasis appended when extreme_emphasis is empty."""
    cfg = VideoConfig(
        spicy_mode=SpicyMode(
            enabled=True,
            enabled_modifiers=["modifier_a"],
            intensity="extreme",
            global_prefix="",
            extreme_emphasis="",
        ),
        default_video=DefaultVideo(),
    )
    result = build_spicy_prompt(cfg)
    assert "(extreme detail, maximum realism)" not in result


# ═══════════════════════════════════════════════════════════════
# NEW: video.json field loading validation
# ═══════════════════════════════════════════════════════════════


def test_video_config_loads_all_fields(tmp_path):
    """video.json must load all fields into the correct Pydantic model fields."""
    import json

    from grok_spicy.config import clear_cache, load_video_config

    clear_cache()
    config_path = tmp_path / "video.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "spicy_mode": {
                    "enabled": True,
                    "enabled_modifiers": ["modifier_one", "modifier_two"],
                    "intensity": "high",
                    "global_prefix": "test prefix: ",
                    "extreme_emphasis": "",
                },
                "characters": [
                    {
                        "id": "char_1",
                        "name": "TestChar",
                        "description": "test description",
                        "images": ["path/to/img.jpg"],
                        "spicy_traits": ["trait_a"],
                    }
                ],
                "default_video": {
                    "scene": "test environment",
                    "motion": "test motion directive",
                    "audio_cues": "test audio",
                },
                "narrative_core": {
                    "restraint_rule": "test rule",
                    "escalation_arc": "test arc",
                    "style_directive": "test style directive",
                },
            }
        )
    )

    cfg = load_video_config(config_path)

    # spicy_mode fields
    assert cfg.spicy_mode.enabled is True
    assert cfg.spicy_mode.enabled_modifiers == ["modifier_one", "modifier_two"]
    assert cfg.spicy_mode.intensity == "high"
    assert cfg.spicy_mode.global_prefix == "test prefix: "

    # characters
    assert len(cfg.characters) == 1
    assert cfg.characters[0].name == "TestChar"
    assert cfg.characters[0].images == ["path/to/img.jpg"]

    # default_video — these MUST NOT be empty
    assert cfg.default_video.scene == "test environment"
    assert cfg.default_video.motion == "test motion directive"
    assert cfg.default_video.audio_cues == "test audio"

    # narrative_core
    assert cfg.narrative_core is not None
    assert cfg.narrative_core.restraint_rule == "test rule"
    assert cfg.narrative_core.escalation_arc == "test arc"
    assert cfg.narrative_core.style_directive == "test style directive"

    clear_cache()


# ═══════════════════════════════════════════════════════════════
# NEW: pipeline passes video_config to character sheet
# ═══════════════════════════════════════════════════════════════


def test_pipeline_passes_video_config_to_character_sheet():
    """Pipeline must pass video_config to generate_character_sheet().

    Code inspection test — verify the call site in pipeline.py includes
    video_config in the arguments to generate_character_sheet.submit().
    """
    from pathlib import Path

    source = Path("src/grok_spicy/pipeline.py").read_text(encoding="utf-8")

    # Find the generate_character_sheet.submit block
    assert (
        "generate_character_sheet.submit(" in source
    ), "Could not find generate_character_sheet.submit() call in pipeline.py"

    # Extract the block from .submit( to the matching closing )
    start = source.index("generate_character_sheet.submit(")
    # Find the end of the call — look for the list comprehension closing
    block = source[start : start + 500]
    assert (
        "video_config=video_config" in block
    ), "generate_character_sheet.submit() is missing video_config=video_config kwarg"
