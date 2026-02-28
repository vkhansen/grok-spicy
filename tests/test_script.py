"""Tests for script compilation (tasks/script.py)."""

from __future__ import annotations

import os

from grok_spicy.schemas import (
    Character,
    CharacterAsset,
    KeyframeAsset,
    Scene,
    StoryPlan,
)
from grok_spicy.tasks.script import compile_script


def _make_plan(**overrides) -> StoryPlan:
    defaults = dict(
        title="Test Video",
        style="cinematic realism",
        aspect_ratio="16:9",
        color_palette="cold grays, warm amber",
        characters=[
            Character(
                name="Alice",
                role="protagonist",
                visual_description="A " * 40,
                personality_cues=["brave"],
            ),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="Opening",
                description="Alice walks in.",
                characters_present=["Alice"],
                setting="forest clearing",
                camera="wide shot",
                mood="calm",
                action="walks forward",
                prompt_summary="Alice walks forward into the clearing.",
                duration_seconds=8,
                transition="cut",
            ),
        ],
    )
    defaults.update(overrides)
    return StoryPlan(**defaults)


def _make_character_asset(**overrides) -> CharacterAsset:
    defaults = dict(
        name="Alice",
        portrait_url="https://example.com/alice.jpg",
        portrait_path="output/character_sheets/Alice_v1.jpg",
        visual_description="A " * 40,
        consistency_score=0.95,
        generation_attempts=1,
    )
    defaults.update(overrides)
    return CharacterAsset(**defaults)


def _make_keyframe_asset(**overrides) -> KeyframeAsset:
    defaults = dict(
        scene_id=1,
        keyframe_url="https://example.com/kf1.jpg",
        keyframe_path="output/keyframes/scene_1_v1.jpg",
        consistency_score=0.90,
        generation_attempts=1,
        edit_passes=0,
        video_prompt="wide shot. walks forward. cinematic realism.",
    )
    defaults.update(overrides)
    return KeyframeAsset(**defaults)


def test_compile_script_writes_utf8(tmp_path, monkeypatch):
    """Script with unicode arrows (U+2192) writes successfully on any locale."""
    monkeypatch.chdir(tmp_path)

    plan = _make_plan(
        scenes=[
            Scene(
                scene_id=1,
                title="Collapse",
                description="Throats give way.",
                characters_present=["Alice"],
                setting="industrial void",
                camera="close-up on throats \u2192 pull back to wide",
                mood="grim",
                action="tracheas collapse",
                prompt_summary="Throats give way under crushing pressure.",
                duration_seconds=8,
                transition="fade to black",
            ),
        ],
    )
    characters = [_make_character_asset()]
    keyframes = [
        _make_keyframe_asset(
            video_prompt="close-up \u2192 pull back. cinematic realism.",
        ),
    ]

    path = compile_script.fn(plan, characters, keyframes)

    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "\u2192" in content
    assert "Collapse" in content


def test_compile_script_unicode_characters(tmp_path, monkeypatch):
    """Various unicode characters in prompts survive the write."""
    monkeypatch.chdir(tmp_path)

    plan = _make_plan(
        title="Caf\u00e9 \u2014 Night",
        style="neo-noir \u2013 moody",
        color_palette="deep blue \u00b7 amber \u00b7 slate",
        scenes=[
            Scene(
                scene_id=1,
                title="Entr\u00e9e",
                description="She enters.",
                characters_present=["Alice"],
                setting="caf\u00e9 terrace",
                camera="tracking \u2192 push-in",
                mood="tense",
                action="walks through doorway",
                prompt_summary="She enters the cafe terrace.",
                duration_seconds=8,
            ),
        ],
    )
    characters = [_make_character_asset()]
    keyframes = [_make_keyframe_asset()]

    path = compile_script.fn(plan, characters, keyframes)

    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "Caf\u00e9" in content
    assert "\u2014" in content
    assert "\u2192" in content


def test_compile_script_basic_output(tmp_path, monkeypatch):
    """Basic script compilation produces expected markdown structure."""
    monkeypatch.chdir(tmp_path)

    plan = _make_plan()
    characters = [_make_character_asset()]
    keyframes = [_make_keyframe_asset()]

    path = compile_script.fn(plan, characters, keyframes)

    assert path == "output/script.md"
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "# Test Video" in content
    assert "### Alice" in content
    assert "### Scene 1: Opening" in content
    assert "**Score:** 0.95" in content
    assert "Consistency | 0.90" in content
