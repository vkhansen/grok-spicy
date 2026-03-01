"""Unit tests for CLI helpers."""

import os
import sys
import tempfile

from grok_spicy.__main__ import _parse_refs, main


def test_parse_refs_valid():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
        f.write(b"fake image")
        tmp = f.name

    try:
        refs = _parse_refs([f"Fox={tmp}"])
        assert "Fox" in refs
        assert refs["Fox"].endswith(".jpg")
        assert os.path.isfile(refs["Fox"])
    finally:
        os.unlink(tmp)
        # Clean up the copy
        for v in refs.values():
            if os.path.isfile(v):
                os.unlink(v)


def test_parse_refs_missing_file(capsys):
    refs = _parse_refs(["Fox=/nonexistent/path.jpg"])
    assert refs == {}
    captured = capsys.readouterr()
    assert "Warning" in captured.err


def test_parse_refs_spaces_in_name():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
        f.write(b"fake image")
        tmp = f.name

    try:
        refs = _parse_refs([f"Fox Lady={tmp}"])
        assert "Fox Lady" in refs
        # Dest path should have underscores
        assert "Fox_Lady" in refs["Fox Lady"]
    finally:
        os.unlink(tmp)
        for v in refs.values():
            if os.path.isfile(v):
                os.unlink(v)


def test_parse_refs_empty():
    assert _parse_refs([]) == {}


# ─── --prompt-file tests ──────────────────────────────────


def test_prompt_file_reads_lines(monkeypatch, tmp_path):
    """--prompt-file parses --- separated blocks into concepts."""
    pf = tmp_path / "prompts.txt"
    pf.write_text("A fox adventure\n---\n# comment\nAn owl story\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["grok-spicy", "--prompt-file", str(pf)])
    # Will exit(1) because no API key — but we can check concept parsing
    # by intercepting before env validation. Patch sys.exit and pipeline import.
    captured_concepts: list[str] = []

    def fake_pipeline(concept, **kwargs):
        captured_concepts.append(concept)
        return "ok"

    monkeypatch.setenv("GROK_API_KEY", "test-key")
    monkeypatch.setattr("grok_spicy.pipeline.video_pipeline", fake_pipeline)
    main()
    assert captured_concepts == ["A fox adventure", "An owl story"]


def test_prompt_file_single_concept(monkeypatch, tmp_path):
    """--prompt-file without --- treats entire file as one concept."""
    pf = tmp_path / "prompts.txt"
    pf.write_text("Scene 1: Fox enters\n\nScene 2: Owl watches\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["grok-spicy", "--prompt-file", str(pf)])
    captured_concepts: list[str] = []

    def fake_pipeline(concept, **kwargs):
        captured_concepts.append(concept)
        return "ok"

    monkeypatch.setenv("GROK_API_KEY", "test-key")
    monkeypatch.setattr("grok_spicy.pipeline.video_pipeline", fake_pipeline)
    main()
    assert len(captured_concepts) == 1
    assert "Scene 1" in captured_concepts[0]
    assert "Scene 2" in captured_concepts[0]


def test_prompt_file_missing_exits(monkeypatch):
    """--prompt-file with a nonexistent path exits with code 1."""
    monkeypatch.setattr(
        sys, "argv", ["grok-spicy", "--prompt-file", "/no/such/file.txt"]
    )
    try:
        main()
        raise AssertionError("Should have called sys.exit")
    except SystemExit as exc:
        assert exc.code == 1


def test_prompt_file_empty_exits(monkeypatch, tmp_path):
    """--prompt-file with an all-blank/comment file exits with code 1."""
    pf = tmp_path / "empty.txt"
    pf.write_text("# just a comment\n\n  \n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["grok-spicy", "--prompt-file", str(pf)])
    try:
        main()
        raise AssertionError("Should have called sys.exit")
    except SystemExit as exc:
        assert exc.code == 1


def test_prompt_file_overrides_positional(monkeypatch, tmp_path):
    """--prompt-file takes priority when both positional and file are given."""
    pf = tmp_path / "prompts.txt"
    pf.write_text("From file\n", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        ["grok-spicy", "From positional", "--prompt-file", str(pf)],
    )

    captured: list[str] = []

    def fake_pipeline(concept, **kwargs):
        captured.append(concept)
        return "ok"

    monkeypatch.setenv("GROK_API_KEY", "test-key")
    monkeypatch.setattr("grok_spicy.pipeline.video_pipeline", fake_pipeline)
    main()
    assert captured == ["From file"]


def test_parse_refs_multiple():
    files = []
    try:
        for name in ["Fox", "Owl"]:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                f.write(b"fake image")
            files.append((name, f.name))

        raw = [f"{name}={path}" for name, path in files]
        refs = _parse_refs(raw)
        assert len(refs) == 2
        assert "Fox" in refs
        assert "Owl" in refs
    finally:
        for _, path in files:
            if os.path.isfile(path):
                os.unlink(path)
        for v in refs.values():
            if os.path.isfile(v):
                os.unlink(v)
