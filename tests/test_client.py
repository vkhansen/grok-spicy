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
    _is_result_moderated,
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


class _FakeResult:
    """Fake SDK result for testing _is_result_moderated."""

    def __init__(self, url=None, raise_on_access=False):
        self._url = url
        self._raise_on_access = raise_on_access

    @property
    def url(self):
        if self._raise_on_access:
            raise ValueError("Video did not respect moderation rules; URL is not available.")
        return self._url


def test_is_result_moderated_normal_url():
    result = _FakeResult(url="https://example.com/image.png")
    assert _is_result_moderated(result) is False


def test_is_result_moderated_moderated_url():
    result = _FakeResult(url="https://example.com/moderated_content/abc.png")
    assert _is_result_moderated(result) is True


def test_is_result_moderated_video_valueerror():
    """Video SDK raises ValueError on .url access when moderated."""
    result = _FakeResult(raise_on_access=True)
    assert _is_result_moderated(result) is True


def test_is_result_moderated_no_url_attribute():
    """AttributeError (e.g. result has no .url) is treated as moderated."""

    class _NoUrl:
        pass

    assert _is_result_moderated(_NoUrl()) is True
