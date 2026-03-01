"""Step 6: Video assembly — FFmpeg normalize and concatenate."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

from prefect import task

from grok_spicy.schemas import VideoAsset

logger = logging.getLogger(__name__)


@task(name="assemble-video")
def assemble_final_video(videos: list[VideoAsset], run_dir: str = "output") -> str:
    """Normalize all scene clips and concatenate into final.mp4."""
    sorted_vids = sorted(videos, key=lambda v: v.scene_id)
    os.makedirs(run_dir, exist_ok=True)
    final = f"{run_dir}/final.mp4"

    logger.info("Assembly starting: %d video clip(s)", len(sorted_vids))
    for v in sorted_vids:
        logger.debug(
            "  clip: scene=%d, path=%s, duration=%.1fs",
            v.scene_id,
            v.video_path,
            v.duration,
        )

    if not shutil.which("ffmpeg"):
        logger.error("FFmpeg not found on PATH — cannot assemble")
        raise FileNotFoundError(
            "FFmpeg not found on PATH. Install it: https://ffmpeg.org/download.html"
        )

    if len(sorted_vids) == 1:
        logger.info("Single clip — copying directly to %s", final)
        shutil.copy2(sorted_vids[0].video_path, final)
        return final

    # Normalize each clip
    logger.info("Normalizing %d clips (fps=24, 1280x720, libx264)", len(sorted_vids))
    norm_paths = []
    for v in sorted_vids:
        norm = v.video_path.replace(".mp4", "_norm.mp4")
        logger.debug("Normalizing scene %d: %s → %s", v.scene_id, v.video_path, norm)
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
        logger.debug("Normalized scene %d → %s", v.scene_id, norm)
        norm_paths.append(norm)

    # Write concat file
    concat_file = f"{run_dir}/concat.txt"
    with open(concat_file, "w") as f:
        for p in norm_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
    logger.debug(
        "Concat list written to %s with %d entries", concat_file, len(norm_paths)
    )

    # Concatenate
    logger.info("Concatenating %d normalized clips → %s", len(norm_paths), final)
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
    logger.info("Assembly complete → %s", final)
    return final
