"""xAI SDK wrapper and helper functions."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess

import requests
from dotenv import load_dotenv

# ─── Constants ────────────────────────────────────────────────

CONSISTENCY_THRESHOLD = 0.80
MAX_CHAR_ATTEMPTS = 3
MAX_KEYFRAME_ITERS = 3
MAX_VIDEO_CORRECTIONS = 2
DEFAULT_DURATION = 8
RESOLUTION = "720p"

MODEL_IMAGE = "grok-imagine-image"
MODEL_VIDEO = "grok-imagine-video"
MODEL_REASONING = "grok-4-1-fast-reasoning"
MODEL_STRUCTURED = "grok-4-1-fast-non-reasoning"


# ─── Client factory ──────────────────────────────────────────


def get_client():
    """Return a configured xai_sdk.Client.

    Reads GROK_API_KEY from .env / environment and passes it
    to the SDK (which natively expects XAI_API_KEY).
    """
    from xai_sdk import Client

    load_dotenv()
    api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set GROK_API_KEY in .env or environment."
        )
    return Client(api_key=api_key)


# ─── Download helper ─────────────────────────────────────────


def download(url: str, path: str) -> str:
    """Download a URL to a local file. Returns the path.

    Critical: Grok image/video URLs are temporary — call immediately.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = requests.get(url)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    return path


# ─── Base64 helper ───────────────────────────────────────────


def to_base64(path: str) -> str:
    """Read a local file and return its base64-encoded contents."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# ─── Frame extraction ────────────────────────────────────────


def extract_frame(video_path: str, output_path: str, position: str = "first") -> str:
    """Extract a single frame from a video file using FFmpeg.

    Args:
        video_path: Path to the input video.
        output_path: Where to write the extracted frame.
        position: "first" or "last".

    Returns:
        The output_path.

    Raises:
        FileNotFoundError: If FFmpeg is not on PATH.
        subprocess.CalledProcessError: If FFmpeg fails.
    """
    if not shutil.which("ffmpeg"):
        raise FileNotFoundError(
            "FFmpeg not found on PATH. Install it: https://ffmpeg.org/download.html"
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if position == "first":
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "select=eq(n\\,0)", "-vframes", "1",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
            "-vframes", "1",
            output_path,
        ]

    subprocess.run(cmd, capture_output=True, check=True)
    return output_path
