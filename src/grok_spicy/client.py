"""xAI SDK wrapper and helper functions."""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────

CONSISTENCY_THRESHOLD = 0.80
EXTENDED_RETRY_THRESHOLD = 0.50
MAX_CHAR_ATTEMPTS = 3
MAX_KEYFRAME_ITERS = 3
MAX_VIDEO_CORRECTIONS = 2
DEFAULT_DURATION = 8
RESOLUTION = "720p"
MODERATED_URL_SENTINEL = "moderated_content"
MAX_REWORD_ATTEMPTS = 2

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
        logger.error("No API key found in GROK_API_KEY or XAI_API_KEY")
        raise RuntimeError("No API key found. Set GROK_API_KEY in .env or environment.")
    source = "GROK_API_KEY" if os.environ.get("GROK_API_KEY") else "XAI_API_KEY"
    logger.debug("Creating xAI client (key source=%s)", source)
    return Client(api_key=api_key)


# ─── Download helper ─────────────────────────────────────────


DOWNLOAD_TIMEOUT = (10, 60)  # (connect, read) seconds
DOWNLOAD_RETRIES = 3


def download(url: str, path: str) -> str:
    """Download a URL to a local file. Returns the path.

    Critical: Grok image/video URLs are temporary — call immediately.
    Retries up to DOWNLOAD_RETRIES times on timeout or connection errors.
    """
    import time

    logger.debug("Downloading %s → %s", url[:80], path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    last_exc: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            r = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
            size_kb = len(r.content) / 1024
            logger.info("Downloaded %.1f KB → %s", size_kb, path)
            return path
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            last_exc = exc
            logger.warning(
                "Download attempt %d/%d failed (%s): %s",
                attempt,
                DOWNLOAD_RETRIES,
                type(exc).__name__,
                url[:80],
            )
            if attempt < DOWNLOAD_RETRIES:
                time.sleep(2 * attempt)
    raise RuntimeError(
        f"Download failed after {DOWNLOAD_RETRIES} attempts: {url[:80]}"
    ) from last_exc


# ─── Base64 helper ───────────────────────────────────────────


def to_base64(path: str) -> str:
    """Read a local file and return its base64-encoded contents."""
    logger.debug("Encoding %s to base64", path)
    with open(path, "rb") as f:
        data = f.read()
    logger.debug("Base64 encoded %d bytes from %s", len(data), path)
    return base64.b64encode(data).decode()


# ─── Moderation helpers ──────────────────────────────────────


def is_moderated(url: str) -> bool:
    """Check if a generation result URL indicates content was moderation-blocked."""
    return MODERATED_URL_SENTINEL in url


def reword_prompt(prompt: str) -> str:
    """Use Grok to rephrase a prompt that was blocked by content moderation.

    Returns a reworded version that preserves scene composition, character names,
    camera work, and style while toning down explicit content.
    """
    from pydantic import BaseModel
    from xai_sdk.chat import user as user_msg

    class _Reworded(BaseModel):
        reworded_prompt: str

    logger.info("Rewording moderated prompt (%d chars)", len(prompt))
    client = get_client()
    chat = client.chat.create(model=MODEL_STRUCTURED)
    chat.append(
        user_msg(
            "The following image/video generation prompt was blocked by content "
            "moderation. Rephrase it to pass moderation while preserving the "
            "scene composition, character names, positioning, camera angles, "
            "lighting, and artistic style. Replace any explicit, revealing, or "
            "NSFW clothing/body descriptions with tasteful, stylish alternatives "
            "(e.g. replace lingerie with elegant evening wear, replace nudity "
            "with fashionable outfits). Keep all other visual details intact. "
            "Return ONLY the reworded prompt text.\n\n"
            f"Blocked prompt:\n{prompt}"
        )
    )
    _, result = chat.parse(_Reworded)
    reworded: str = result.reworded_prompt
    logger.info(
        "Reworded prompt (%d chars): %.200s",
        len(reworded),
        reworded,
    )
    return reworded


def generate_with_moderation_retry(
    generate_fn: Callable[..., Any],
    prompt: str,
    *,
    max_rewords: int = MAX_REWORD_ATTEMPTS,
    **generate_kw: Any,
) -> tuple[Any, str, bool]:
    """Run *generate_fn(prompt=prompt, **generate_kw)* with moderation rewording.

    Returns ``(result, final_prompt, still_moderated)``.
    """
    result = generate_fn(prompt=prompt, **generate_kw)
    for _rw in range(max_rewords):
        if not is_moderated(result.url):
            return result, prompt, False
        logger.warning("Moderation hit (reword %d/%d)", _rw + 1, max_rewords)
        prompt = reword_prompt(prompt)
        result = generate_fn(prompt=prompt, **generate_kw)
    still_moderated = is_moderated(result.url)
    return result, prompt, still_moderated


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
        logger.error("FFmpeg not found on PATH")
        raise FileNotFoundError(
            "FFmpeg not found on PATH. Install it: https://ffmpeg.org/download.html"
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    logger.debug("Extracting %s frame: %s → %s", position, video_path, output_path)

    if position == "first":
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            "select=eq(n\\,0)",
            "-vframes",
            "1",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            video_path,
            "-vframes",
            "1",
            output_path,
        ]

    subprocess.run(cmd, capture_output=True, check=True)
    logger.info("Extracted %s frame → %s", position, output_path)
    return output_path
