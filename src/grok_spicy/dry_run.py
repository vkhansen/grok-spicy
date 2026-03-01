"""Dry-run helpers — write prompts to structured markdown files."""

from __future__ import annotations

import os
from typing import Any

# Legacy constant kept for backward compatibility (tests that monkeypatch it)
DRY_RUN_DIR = "output/dry_run"


def _prompts_dir(run_dir: str | None = None) -> str:
    """Return the prompts base directory for a given run_dir."""
    if run_dir is not None:
        return os.path.join(run_dir, "prompts")
    return DRY_RUN_DIR


def write_prompt(
    step: str,
    label: str,
    *,
    model: str,
    prompt: str | None = None,
    system_prompt: str | None = None,
    user_message: str | None = None,
    image_refs: list[str] | None = None,
    api_params: dict[str, Any] | None = None,
    run_dir: str | None = None,
) -> str:
    """Write a structured markdown file describing a prompt that would be sent.

    Returns the path to the written file.
    """
    base = _prompts_dir(run_dir)
    dir_path = os.path.join(base, step)
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, f"{label}.md")

    lines: list[str] = []
    lines.append(f"# {step} / {label}")
    lines.append("")
    lines.append(f"**Model:** `{model}`")
    lines.append("")

    if system_prompt:
        lines.append("## System Prompt")
        lines.append("")
        lines.append("```")
        lines.append(system_prompt)
        lines.append("```")
        lines.append("")

    if user_message:
        lines.append("## User Message")
        lines.append("")
        lines.append("```")
        lines.append(user_message)
        lines.append("```")
        lines.append("")

    if prompt:
        lines.append("## Prompt")
        lines.append("")
        lines.append("```")
        lines.append(prompt)
        lines.append("```")
        lines.append("")

    if image_refs:
        lines.append("## Image References")
        lines.append("")
        for ref in image_refs:
            lines.append(f"- `{ref}`")
        lines.append("")

    if api_params:
        lines.append("## API Parameters")
        lines.append("")
        for k, v in api_params.items():
            lines.append(f"- **{k}:** `{v}`")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path


def write_summary(prompt_files: list[str], run_dir: str | None = None) -> str:
    """Write a summary markdown listing all prompt files generated."""
    base = _prompts_dir(run_dir)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "summary.md")

    lines: list[str] = []
    lines.append("# Dry-Run Summary")
    lines.append("")
    lines.append(f"Total prompt files: {len(prompt_files)}")
    lines.append("")
    lines.append("## Generated Files")
    lines.append("")
    for pf in prompt_files:
        # Show path relative to prompts dir
        rel = os.path.relpath(pf, base)
        lines.append(f"- `{rel}`")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return path
