"""Unit tests for VideoConfig models, config loader, and prompt builder."""

import json
import os

import pytest
from pydantic import ValidationError

from grok_spicy.config import clear_cache, load_video_config, resolve_character_images
from grok_spicy.prompt_builder import build_spicy_prompt
from grok_spicy.schemas import DefaultVideo, SpicyCharacter, SpicyMode, VideoConfig

# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Clear the config cache before each test."""
    clear_cache()
    yield
    clear_cache()


def _sample_config() -> VideoConfig:
    return VideoConfig(
        version="1.0",
        spicy_mode=SpicyMode(
            enabled_modifiers=["highly detailed skin", "sensual lighting"],
            intensity="high",
            global_prefix="In spicy mode: ",
        ),
        characters=[
            SpicyCharacter(
                id="char_001",
                name="Luna",
                description="A seductive 25-year-old woman with silver hair",
                images=[],
                spicy_traits=["dominant", "teasing smile"],
            ),
            SpicyCharacter(
                id="char_002",
                name="Kai",
                description="Handsome muscular man in his 30s",
                images=[],
                spicy_traits=["intense eye contact"],
            ),
        ],
        default_video=DefaultVideo(
            scene="Dimly lit bedroom",
            motion="slow panning camera",
            audio_cues="soft music",
        ),
    )


def _write_config(cfg: VideoConfig, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg.model_dump(), f)


# ═══════════════════════════════════════════════════════════════
# SCHEMA TESTS
# ═══════════════════════════════════════════════════════════════


class TestSpicyMode:
    def test_valid_intensities(self):
        for level in ("low", "medium", "high", "extreme"):
            sm = SpicyMode(enabled_modifiers=["a"], intensity=level, global_prefix="")
            assert sm.intensity == level

    def test_invalid_intensity(self):
        with pytest.raises(ValidationError):
            SpicyMode(enabled_modifiers=[], intensity="ultra", global_prefix="")


class TestSpicyCharacter:
    def test_defaults(self):
        c = SpicyCharacter(id="c1", name="Test", description="desc")
        assert c.images == []
        assert c.spicy_traits == []

    def test_full(self):
        c = SpicyCharacter(
            id="c1",
            name="Luna",
            description="desc",
            images=["a.jpg"],
            spicy_traits=["bold"],
        )
        assert len(c.images) == 1
        assert c.spicy_traits == ["bold"]


class TestVideoConfig:
    def test_minimal(self):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=[], intensity="low", global_prefix=""
            ),
        )
        assert cfg.version == "1.0"
        assert cfg.characters == []
        assert cfg.default_video.scene == ""

    def test_round_trip(self):
        cfg = _sample_config()
        json_str = cfg.model_dump_json()
        restored = VideoConfig.model_validate_json(json_str)
        assert restored.spicy_mode.intensity == "high"
        assert len(restored.characters) == 2
        assert restored.default_video.scene == "Dimly lit bedroom"


# ═══════════════════════════════════════════════════════════════
# CONFIG LOADER TESTS
# ═══════════════════════════════════════════════════════════════


class TestLoadVideoConfig:
    def test_load_valid_file(self, tmp_path):
        cfg = _sample_config()
        path = tmp_path / "video.json"
        _write_config(cfg, str(path))

        loaded = load_video_config(path)
        assert loaded.version == "1.0"
        assert loaded.spicy_mode.intensity == "high"
        assert len(loaded.characters) == 2

    def test_missing_file_returns_default(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        loaded = load_video_config(path)
        assert loaded.spicy_mode.intensity == "medium"
        assert loaded.characters == []
        assert loaded.spicy_mode.enabled_modifiers == []

    def test_invalid_json_returns_default(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json{{{", encoding="utf-8")
        loaded = load_video_config(path)
        assert loaded.spicy_mode.intensity == "medium"

    def test_invalid_schema_returns_default(self, tmp_path):
        path = tmp_path / "bad_schema.json"
        path.write_text('{"version": "1.0"}', encoding="utf-8")
        loaded = load_video_config(path)
        # Missing required spicy_mode field → fallback
        assert loaded.spicy_mode.intensity == "medium"

    def test_caching(self, tmp_path):
        cfg = _sample_config()
        path = tmp_path / "video.json"
        _write_config(cfg, str(path))

        first = load_video_config(path)
        second = load_video_config(path)
        assert first is second  # Same cached instance


# ═══════════════════════════════════════════════════════════════
# IMAGE RESOLUTION TESTS
# ═══════════════════════════════════════════════════════════════


class TestResolveCharacterImages:
    def test_url_passthrough(self):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=[], intensity="low", global_prefix=""
            ),
            characters=[
                SpicyCharacter(
                    id="c1",
                    name="Test",
                    description="desc",
                    images=["https://example.com/img.jpg"],
                ),
            ],
        )
        result = resolve_character_images(cfg)
        assert result["c1"] == ["https://example.com/img.jpg"]

    def test_local_path_resolved(self, tmp_path):
        img = tmp_path / "ref.jpg"
        img.write_bytes(b"fake image data")
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=[], intensity="low", global_prefix=""
            ),
            characters=[
                SpicyCharacter(
                    id="c1",
                    name="Test",
                    description="desc",
                    images=["ref.jpg"],
                ),
            ],
        )
        result = resolve_character_images(cfg, project_root=tmp_path)
        assert len(result["c1"]) == 1
        assert os.path.isabs(result["c1"][0])

    def test_missing_local_path_skipped(self, tmp_path):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=[], intensity="low", global_prefix=""
            ),
            characters=[
                SpicyCharacter(
                    id="c1",
                    name="Test",
                    description="desc",
                    images=["nonexistent.jpg"],
                ),
            ],
        )
        result = resolve_character_images(cfg, project_root=tmp_path)
        assert result["c1"] == []


# ═══════════════════════════════════════════════════════════════
# PROMPT BUILDER TESTS
# ═══════════════════════════════════════════════════════════════


class TestBuildSpicyPrompt:
    def test_zero_characters(self):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=["detailed skin"],
                intensity="high",
                global_prefix="Spicy: ",
            ),
            characters=[],
            default_video=DefaultVideo(scene="Dark bedroom", motion="slow pan"),
        )
        prompt = build_spicy_prompt(cfg, character_ids=[])
        assert "Spicy:" in prompt
        assert "Dark bedroom" in prompt
        assert "slow pan" in prompt
        assert "detailed skin" in prompt

    def test_one_character(self):
        cfg = _sample_config()
        prompt = build_spicy_prompt(cfg, character_ids=["char_001"])
        assert "Luna" not in prompt or "silver hair" in prompt
        assert "silver hair" in prompt
        assert "dominant" in prompt
        assert "teasing smile" in prompt
        assert "Dimly lit bedroom" in prompt

    def test_two_characters(self):
        cfg = _sample_config()
        prompt = build_spicy_prompt(cfg, character_ids=["char_001", "char_002"])
        assert "silver hair" in prompt
        assert "muscular" in prompt
        assert "interacting with" in prompt

    def test_all_characters_by_default(self):
        cfg = _sample_config()
        prompt = build_spicy_prompt(cfg)
        # Should include both characters
        assert "silver hair" in prompt
        assert "muscular" in prompt

    def test_scene_override(self):
        cfg = _sample_config()
        prompt = build_spicy_prompt(
            cfg, character_ids=[], scene_override="Beach at sunset"
        )
        assert "Beach at sunset" in prompt
        assert "Dimly lit bedroom" not in prompt

    def test_low_intensity_limits_modifiers(self):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=["mod1", "mod2", "mod3"],
                intensity="low",
                global_prefix="",
            ),
        )
        prompt = build_spicy_prompt(cfg, character_ids=[])
        assert "mod1" in prompt
        # Low intensity: only 1 modifier
        assert "mod2" not in prompt
        assert "mod3" not in prompt

    def test_medium_intensity_limits_modifiers(self):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=["mod1", "mod2", "mod3"],
                intensity="medium",
                global_prefix="",
            ),
        )
        prompt = build_spicy_prompt(cfg, character_ids=[])
        assert "mod1" in prompt
        assert "mod2" in prompt
        # Medium: only 2 modifiers
        assert "mod3" not in prompt

    def test_extreme_intensity_adds_emphasis(self):
        cfg = VideoConfig(
            spicy_mode=SpicyMode(
                enabled_modifiers=["mod1"],
                intensity="extreme",
                global_prefix="",
            ),
        )
        prompt = build_spicy_prompt(cfg, character_ids=[])
        assert "extreme detail" in prompt
        assert "maximum realism" in prompt

    def test_global_prefix_included(self):
        cfg = _sample_config()
        prompt = build_spicy_prompt(cfg, character_ids=[])
        assert prompt.startswith("In spicy mode:")
