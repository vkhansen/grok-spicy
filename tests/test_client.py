"""Unit tests for client helpers."""

import os
import tempfile

from grok_spicy.client import (
    CONSISTENCY_THRESHOLD,
    DEFAULT_DURATION,
    MAX_CHAR_ATTEMPTS,
    MAX_KEYFRAME_ITERS,
    MAX_VIDEO_CORRECTIONS,
    MODEL_IMAGE,
    MODEL_REASONING,
    MODEL_STRUCTURED,
    MODEL_VIDEO,
    RESOLUTION,
    to_base64,
)


def test_constants():
    assert CONSISTENCY_THRESHOLD == 0.80
    assert MAX_CHAR_ATTEMPTS == 3
    assert MAX_KEYFRAME_ITERS == 3
    assert MAX_VIDEO_CORRECTIONS == 2
    assert DEFAULT_DURATION == 8
    assert RESOLUTION == "720p"
    assert MODEL_IMAGE == "grok-imagine-image"
    assert MODEL_VIDEO == "grok-imagine-video"
    assert MODEL_REASONING == "grok-4-1-fast-reasoning"
    assert MODEL_STRUCTURED == "grok-4-1-fast-non-reasoning"


def test_to_base64():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(b"hello")
        f.flush()
        result = to_base64(f.name)
    os.unlink(f.name)
    assert result == "aGVsbG8="  # base64("hello")
