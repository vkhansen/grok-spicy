"""Unit tests for the dry_run module."""

import os
from pathlib import Path

from grok_spicy.dry_run import write_prompt, write_summary


def test_write_prompt_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("grok_spicy.dry_run.DRY_RUN_DIR", str(tmp_path / "dry_run"))

    path = write_prompt(
        "step1_ideation",
        "story_plan",
        model="grok-4-1-fast-non-reasoning",
        system_prompt="You are a director.",
        user_message="Create a story about foxes.",
    )

    assert os.path.isfile(path)
    content = Path(path).read_text(encoding="utf-8")
    assert "step1_ideation / story_plan" in content
    assert "`grok-4-1-fast-non-reasoning`" in content
    assert "You are a director." in content
    assert "Create a story about foxes." in content


def test_write_prompt_with_image_refs(tmp_path, monkeypatch):
    monkeypatch.setattr("grok_spicy.dry_run.DRY_RUN_DIR", str(tmp_path / "dry_run"))

    path = write_prompt(
        "step2_characters",
        "Luna_generate",
        model="grok-imagine-image",
        prompt="Full body portrait of Luna.",
        image_refs=["portrait.jpg", "ref.jpg"],
        api_params={"aspect_ratio": "16:9"},
    )

    content = Path(path).read_text(encoding="utf-8")
    assert "portrait.jpg" in content
    assert "ref.jpg" in content
    assert "aspect_ratio" in content
    assert "16:9" in content


def test_write_prompt_minimal(tmp_path, monkeypatch):
    monkeypatch.setattr("grok_spicy.dry_run.DRY_RUN_DIR", str(tmp_path / "dry_run"))

    path = write_prompt(
        "step5_videos",
        "scene_1",
        model="grok-imagine-video",
        prompt="Fox leaps over log.",
    )

    assert os.path.isfile(path)
    content = Path(path).read_text(encoding="utf-8")
    assert "Fox leaps over log." in content


def test_write_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("grok_spicy.dry_run.DRY_RUN_DIR", str(tmp_path / "dry_run"))

    # Create a few fake prompt files
    step_dir = tmp_path / "dry_run" / "step1_ideation"
    step_dir.mkdir(parents=True)
    (step_dir / "story_plan.md").write_text("# test", encoding="utf-8")

    step2_dir = tmp_path / "dry_run" / "step2_characters"
    step2_dir.mkdir(parents=True)
    (step2_dir / "Luna_generate.md").write_text("# test", encoding="utf-8")

    prompt_files = [
        str(step_dir / "story_plan.md"),
        str(step2_dir / "Luna_generate.md"),
    ]

    path = write_summary(prompt_files)

    assert os.path.isfile(path)
    content = Path(path).read_text(encoding="utf-8")
    assert "Dry-Run Summary" in content
    assert "Total prompt files: 2" in content
    assert "story_plan.md" in content
    assert "Luna_generate.md" in content


def test_write_prompt_creates_nested_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("grok_spicy.dry_run.DRY_RUN_DIR", str(tmp_path / "dry_run"))

    path = write_prompt(
        "step0_describe_ref",
        "Alex",
        model="grok-4-1-fast-reasoning",
        system_prompt="Describe the person.",
        user_message="Character name is Alex.",
        image_refs=["photo.jpg"],
    )

    assert os.path.isfile(path)
    assert "step0_describe_ref" in path
