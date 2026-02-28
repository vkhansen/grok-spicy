"""Loader for video.json — centralized spicy mode configuration."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from grok_spicy.schemas import VideoConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("video.json")

_cached_config: VideoConfig | None = None
_cached_path: str | None = None


def load_video_config(path: Path | None = None) -> VideoConfig:
    """Load and validate video.json, returning a VideoConfig.

    Results are cached — subsequent calls with the same path return
    the cached instance without re-reading the file.

    Args:
        path: Path to video.json.  Defaults to ``./video.json``.

    Returns:
        Parsed VideoConfig.  Falls back to a minimal default if the
        file is missing or contains invalid JSON/schema.
    """
    global _cached_config, _cached_path

    resolved = str(path or DEFAULT_CONFIG_PATH)

    if _cached_config is not None and _cached_path == resolved:
        logger.debug("Returning cached VideoConfig from %s", resolved)
        return _cached_config

    if not os.path.isfile(resolved):
        logger.warning("Config file not found: %s — using built-in defaults", resolved)
        cfg = _default_config()
        _cached_config = cfg
        _cached_path = resolved
        return cfg

    try:
        with open(resolved, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Failed to read config %s (%s) — using built-in defaults",
            resolved,
            exc,
        )
        cfg = _default_config()
        _cached_config = cfg
        _cached_path = resolved
        return cfg

    try:
        cfg = VideoConfig.model_validate(raw)
    except Exception as exc:
        logger.warning(
            "Invalid config schema in %s (%s) — using built-in defaults",
            resolved,
            exc,
        )
        cfg = _default_config()
        _cached_config = cfg
        _cached_path = resolved
        return cfg

    logger.info(
        "Loaded video config v%s from %s — intensity=%s, characters=%d, modifiers=%d",
        cfg.version,
        resolved,
        cfg.spicy_mode.intensity,
        len(cfg.characters),
        len(cfg.spicy_mode.enabled_modifiers),
    )
    _cached_config = cfg
    _cached_path = resolved
    return cfg


def clear_cache() -> None:
    """Reset the cached config (useful for testing or hot-reload)."""
    global _cached_config, _cached_path
    _cached_config = None
    _cached_path = None


def _default_config() -> VideoConfig:
    """Minimal built-in default when no video.json is available."""
    from grok_spicy.schemas import DefaultVideo, SpicyMode

    return VideoConfig(
        spicy_mode=SpicyMode(
            enabled_modifiers=[],
            intensity="medium",
            global_prefix="",
        ),
        characters=[],
        default_video=DefaultVideo(),
    )


def resolve_character_images(
    cfg: VideoConfig, project_root: Path | None = None
) -> dict[str, list[str]]:
    """Resolve character image paths (URLs stay as-is, local paths made absolute).

    Returns ``{character_id: [resolved_path_or_url, ...]}``.
    """
    root = project_root or Path(".")
    result: dict[str, list[str]] = {}
    for char in cfg.characters:
        resolved: list[str] = []
        for img in char.images:
            if img.startswith(("http://", "https://")):
                resolved.append(img)
            else:
                abs_path = str((root / img).resolve())
                if os.path.isfile(abs_path):
                    resolved.append(abs_path)
                else:
                    logger.warning(
                        "Character %r image not found: %s (resolved: %s)",
                        char.name,
                        img,
                        abs_path,
                    )
        result[char.id] = resolved
    return result
