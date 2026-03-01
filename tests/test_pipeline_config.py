"""Unit tests for PipelineConfig."""

import pytest
from pydantic import ValidationError

from grok_spicy.schemas import PipelineConfig


def test_defaults():
    cfg = PipelineConfig()
    assert cfg.negative_prompt is None
    assert cfg.style_override is None
    assert cfg.consistency_threshold == 0.80
    assert cfg.max_retries is None
    assert cfg.max_duration == 15
    assert cfg.debug is False
    assert cfg.dry_run is False


def test_effective_style_default():
    cfg = PipelineConfig()
    assert cfg.effective_style("Pixar 3D") == "Pixar 3D"


def test_effective_style_override():
    cfg = PipelineConfig(style_override="Anime cel-shading")
    assert cfg.effective_style("Pixar 3D") == "Anime cel-shading"


def test_max_char_attempts_default():
    from grok_spicy.client import MAX_CHAR_ATTEMPTS

    cfg = PipelineConfig()
    assert cfg.max_char_attempts == MAX_CHAR_ATTEMPTS


def test_max_char_attempts_override():
    cfg = PipelineConfig(max_retries=5)
    assert cfg.max_char_attempts == 5


def test_max_keyframe_iters_default():
    from grok_spicy.client import MAX_KEYFRAME_ITERS

    cfg = PipelineConfig()
    assert cfg.max_keyframe_iters == MAX_KEYFRAME_ITERS


def test_max_keyframe_iters_override():
    cfg = PipelineConfig(max_retries=7)
    assert cfg.max_keyframe_iters == 7


def test_max_video_corrections_default():
    from grok_spicy.client import MAX_VIDEO_CORRECTIONS

    cfg = PipelineConfig()
    assert cfg.max_video_corrections == MAX_VIDEO_CORRECTIONS


def test_max_video_corrections_override():
    cfg = PipelineConfig(max_retries=4)
    assert cfg.max_video_corrections == 4


def test_consistency_threshold_bounds():
    with pytest.raises(ValidationError):
        PipelineConfig(consistency_threshold=1.5)
    with pytest.raises(ValidationError):
        PipelineConfig(consistency_threshold=-0.1)


def test_max_duration_bounds():
    with pytest.raises(ValidationError):
        PipelineConfig(max_duration=2)
    with pytest.raises(ValidationError):
        PipelineConfig(max_duration=16)


def test_max_retries_bounds():
    with pytest.raises(ValidationError):
        PipelineConfig(max_retries=0)


def test_dry_run_flag():
    cfg = PipelineConfig(dry_run=True)
    assert cfg.dry_run is True


def test_round_trip():
    cfg = PipelineConfig(
        negative_prompt="No zoom",
        style_override="Anime",
        consistency_threshold=0.9,
        max_retries=5,
        max_duration=8,
        debug=True,
        dry_run=True,
    )
    json_str = cfg.model_dump_json()
    restored = PipelineConfig.model_validate_json(json_str)
    assert restored.negative_prompt == "No zoom"
    assert restored.style_override == "Anime"
    assert restored.consistency_threshold == 0.9
    assert restored.max_retries == 5
    assert restored.max_duration == 8
    assert restored.debug is True
    assert restored.dry_run is True
