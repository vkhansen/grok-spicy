"""Unit tests for CLI entry point."""

import json
import sys

from grok_spicy.__main__ import main


def _write_minimal_config(tmp_path) -> str:
    """Write a minimal valid video.json and return its path."""
    cfg = {
        "version": "1.0",
        "spicy_mode": {
            "enabled": True,
            "enabled_modifiers": [],
            "intensity": "low",
            "global_prefix": "",
        },
        "story_plan": {
            "title": "Test Story",
            "style": "cinematic realism",
            "color_palette": "warm ambers",
            "characters": [
                {
                    "name": "Fox",
                    "role": "protagonist",
                    "visual_description": "A " * 40,
                    "personality_cues": ["brave"],
                }
            ],
            "scenes": [
                {
                    "scene_id": 1,
                    "title": "Scene One",
                    "description": "Fox enters.",
                    "characters_present": ["Fox"],
                    "setting": "forest",
                    "camera": "wide",
                    "mood": "warm",
                    "action": "Fox walks",
                    "prompt_summary": "Fox walks through the forest.",
                    "duration_seconds": 8,
                }
            ],
        },
    }
    path = tmp_path / "video.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def test_config_only_pipeline(monkeypatch, tmp_path):
    """CLI loads video.json and runs pipeline without concept arg."""
    cfg_path = _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["grok-spicy", "--config", cfg_path]
    )

    captured = []

    def fake_pipeline(video_config, **kwargs):
        captured.append(video_config.story_plan.title)
        return "ok"

    monkeypatch.setenv("GROK_API_KEY", "test-key")
    monkeypatch.setattr("grok_spicy.pipeline.video_pipeline", fake_pipeline)
    main()
    assert captured == ["Test Story"]


def test_missing_story_plan_exits(monkeypatch, tmp_path):
    """CLI exits with error if video.json has no story_plan."""
    cfg = {
        "version": "1.0",
        "spicy_mode": {
            "enabled": True,
            "enabled_modifiers": [],
            "intensity": "low",
            "global_prefix": "",
        },
    }
    path = tmp_path / "video.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["grok-spicy", "--config", str(path)]
    )
    try:
        main()
        raise AssertionError("Should have called sys.exit")
    except SystemExit as exc:
        assert exc.code == 1


def test_dry_run_flag(monkeypatch, tmp_path):
    """--dry-run skips API key check and passes dry_run to config."""
    cfg_path = _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["grok-spicy", "--config", cfg_path, "--dry-run"]
    )

    captured_config = []

    def fake_pipeline(video_config, **kwargs):
        captured_config.append(kwargs.get("config"))
        return "ok"

    monkeypatch.setattr("grok_spicy.pipeline.video_pipeline", fake_pipeline)
    main()
    assert captured_config[0].dry_run is True


def test_no_args_loads_default_config(monkeypatch, tmp_path):
    """Running with no args tries to load ./video.json."""
    cfg_path = _write_minimal_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["grok-spicy"])

    captured = []

    def fake_pipeline(video_config, **kwargs):
        captured.append(video_config.story_plan.title)
        return "ok"

    monkeypatch.setenv("GROK_API_KEY", "test-key")
    monkeypatch.setattr("grok_spicy.pipeline.video_pipeline", fake_pipeline)
    main()
    assert captured == ["Test Story"]
