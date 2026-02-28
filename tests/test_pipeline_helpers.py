"""Unit tests for pipeline helper functions (_notify, _match_character_refs)."""

from unittest.mock import MagicMock

from grok_spicy.pipeline import _match_character_refs, _notify
from grok_spicy.schemas import Character

# ─── _notify ──────────────────────────────────────────────────


def test_notify_calls_method():
    observer = MagicMock()
    _notify(observer, "on_plan", 1, "plan_data")
    observer.on_plan.assert_called_once_with(1, "plan_data")


def test_notify_swallows_exceptions():
    observer = MagicMock()
    observer.on_plan.side_effect = RuntimeError("boom")
    _notify(observer, "on_plan", 1, "data")  # should not raise


def test_notify_swallows_attribute_error():
    observer = MagicMock(spec=[])  # no methods
    _notify(observer, "nonexistent", 1)  # should not raise


# ─── _match_character_refs ────────────────────────────────────


def _make_chars(*names):
    return [
        Character(
            name=n,
            role="protagonist",
            visual_description="A " * 40,
            personality_cues=["brave"],
        )
        for n in names
    ]


def test_match_empty_refs():
    chars = _make_chars("Fox", "Owl")
    assert _match_character_refs({}, chars) == {}


def test_match_exact_case_insensitive():
    chars = _make_chars("Fox", "Owl")
    refs = {"fox": "/path/fox.jpg", "OWL": "/path/owl.jpg"}
    matched = _match_character_refs(refs, chars)
    assert matched == {"Fox": "/path/fox.jpg", "Owl": "/path/owl.jpg"}


def test_match_exact_same_case():
    chars = _make_chars("Fox")
    refs = {"Fox": "/path/fox.jpg"}
    matched = _match_character_refs(refs, chars)
    assert matched == {"Fox": "/path/fox.jpg"}


def test_match_partial_only_matched_returned():
    chars = _make_chars("Fox", "Owl")
    refs = {"Fox": "/path/fox.jpg", "Unknown": "/path/x.jpg"}
    matched = _match_character_refs(refs, chars)
    # Fox matched directly. "Unknown" would go to LLM fallback.
    # Since we can't test LLM fallback without mocking the client,
    # we just verify the exact match part works.
    assert "Fox" in matched
    assert matched["Fox"] == "/path/fox.jpg"


def test_match_no_characters():
    refs = {"Fox": "/path/fox.jpg"}
    matched = _match_character_refs(refs, [])
    assert matched == {}
