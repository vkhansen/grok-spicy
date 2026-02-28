"""Step 4: Script compilation — markdown storyboard and state.json."""

from __future__ import annotations

import os

from prefect import task

from grok_spicy.schemas import CharacterAsset, KeyframeAsset, StoryPlan


@task(name="compile-script")
def compile_script(
    plan: StoryPlan,
    characters: list[CharacterAsset],
    keyframes: list[KeyframeAsset],
) -> str:
    """Compile assets into a human-readable markdown storyboard.

    No API calls — pure Python. Returns the script file path.
    """
    lines = [
        f"# {plan.title}\n",
        f"**Style:** {plan.style}  ",
        f"**Aspect Ratio:** {plan.aspect_ratio}  ",
        f"**Color Palette:** {plan.color_palette}\n",
        "---\n",
        "## Characters\n",
    ]

    for c in characters:
        lines += [
            f"### {c.name}",
            f"**Score:** {c.consistency_score:.2f} | "
            f"**Attempts:** {c.generation_attempts}\n",
            f"> {c.visual_description}\n",
            f"![{c.name}]({c.portrait_path})\n",
        ]

    lines += ["---\n", "## Scenes\n"]

    for kf in sorted(keyframes, key=lambda k: k.scene_id):
        sc = next(s for s in plan.scenes if s.scene_id == kf.scene_id)
        lines += [
            f"### Scene {sc.scene_id}: {sc.title}\n",
            "| Property | Value |",
            "|---|---|",
            f"| Setting | {sc.setting} |",
            f"| Characters | {', '.join(sc.characters_present)} |",
            f"| Camera | {sc.camera} |",
            f"| Duration | {sc.duration_seconds}s |",
            f"| Transition | {sc.transition} |",
            f"| Consistency | {kf.consistency_score:.2f} (edits: {kf.edit_passes}) |\n",
            f"![Scene {sc.scene_id}]({kf.keyframe_path})\n",
            "**Video Prompt:**",
            f"> {kf.video_prompt}\n",
        ]

    path = "output/script.md"
    os.makedirs("output", exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path
