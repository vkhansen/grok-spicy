"""Step 6: Video assembly — FFmpeg normalize and concatenate."""

from __future__ import annotations

import os
import shutil
import subprocess

from prefect import task

from grok_spicy.schemas import VideoAsset


@task(name="assemble-video")
def assemble_final_video(videos: list[VideoAsset]) -> str:
    """Normalize all scene clips and concatenate into final_video.mp4."""
    sorted_vids = sorted(videos, key=lambda v: v.scene_id)
    os.makedirs("output", exist_ok=True)
    final = "output/final_video.mp4"

    if not shutil.which("ffmpeg"):
        raise FileNotFoundError(
            "FFmpeg not found on PATH. Install it: https://ffmpeg.org/download.html"
        )

    if len(sorted_vids) == 1:
        shutil.copy2(sorted_vids[0].video_path, final)
        return final

    # Normalize each clip
    norm_paths = []
    for v in sorted_vids:
        norm = v.video_path.replace(".mp4", "_norm.mp4")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                v.video_path,
                "-vf",
                "fps=24,scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:-1:-1:color=black",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                norm,
            ],
            capture_output=True,
            check=True,
        )
        norm_paths.append(norm)

    # Write concat file
    concat_file = "output/concat.txt"
    with open(concat_file, "w") as f:
        for p in norm_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    # Concatenate
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            final,
        ],
        capture_output=True,
        check=True,
    )
    return final
