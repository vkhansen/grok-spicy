"""CLI entry point for grok-spicy."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def setup_logging(log_dir: str = "output", verbose: bool = False) -> None:
    """Configure logging with file and console handlers.

    - File handler: DEBUG level -> ``{log_dir}/grok_spicy.log`` (always)
    - Console handler: DEBUG level (if *verbose*) or INFO level -> stderr

    Args:
        log_dir: Directory for the log file.
        verbose: When True, console output includes DEBUG messages.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "grok_spicy.log")

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — captures everything (DEBUG+)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler — DEBUG when verbose, otherwise INFO
    console_level = logging.DEBUG if verbose else logging.INFO
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(console_level)
    ch.setFormatter(fmt)

    root = logging.getLogger("grok_spicy")
    root.setLevel(logging.DEBUG)
    # Prevent duplicate handlers when setup_logging is called multiple times
    root.handlers.clear()
    root.addHandler(fh)
    root.addHandler(ch)
    # Stop Prefect (or any parent logger) from duplicating our messages
    root.propagate = False

    # Belt-and-suspenders: strip Prefect's console handler from the Python root
    # logger so grok_spicy messages can never be double-printed even if propagate
    # gets flipped back to True by a later dictConfig call.
    py_root = logging.getLogger()
    py_root.handlers = [
        h for h in py_root.handlers if h.__class__.__name__ != "PrefectConsoleHandler"
    ]

    logging.getLogger("grok_spicy").info(
        "Logging initialised — file=%s (DEBUG), console (%s)",
        log_path,
        logging.getLevelName(console_level),
    )


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="grok-spicy",
        description="Generate a multi-scene video from a video.json config using Grok APIs",
    )
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the dashboard server alongside the pipeline",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the dashboard server only (browse past runs)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Port for the dashboard server (default: 8420)",
    )
    parser.add_argument(
        "--max-duration",
        type=int,
        default=15,
        metavar="SECONDS",
        help="Maximum per-scene duration in seconds (3-15, default: 15). "
        "Use 8 to force all scenes into the correction-eligible tier.",
    )
    parser.add_argument(
        "--negative-prompt",
        metavar="TEXT",
        help="Appended as 'Avoid: TEXT' to all video generation prompts",
    )
    parser.add_argument(
        "--style-override",
        metavar="TEXT",
        help="Replace the plan.style with this string",
    )
    parser.add_argument(
        "--consistency-threshold",
        type=float,
        default=None,
        metavar="FLOAT",
        help="Override vision-check consistency threshold (0.0-1.0, default: 0.80)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        metavar="N",
        help="Override all max retry/iteration counts (characters, keyframes, video)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to video.json config file (default: ./video.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all prompts without making API calls (no key needed)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug mode: only generate 1 scene (faster, cheaper test runs)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging on the console",
    )
    args = parser.parse_args()

    # Validate --max-duration
    if not 3 <= args.max_duration <= 15:
        print(
            f"Error: --max-duration must be between 3 and 15, got {args.max_duration}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate --consistency-threshold
    if args.consistency_threshold is not None and not (
        0.0 <= args.consistency_threshold <= 1.0
    ):
        print(
            f"Error: --consistency-threshold must be between 0.0 and 1.0, "
            f"got {args.consistency_threshold}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate --max-retries
    if args.max_retries is not None and args.max_retries < 1:
        print(
            f"Error: --max-retries must be >= 1, got {args.max_retries}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build PipelineConfig from CLI args
    from grok_spicy.schemas import PipelineConfig

    config_kw: dict = {
        "max_duration": args.max_duration,
        "debug": args.debug,
        "dry_run": args.dry_run,
    }
    if args.negative_prompt is not None:
        config_kw["negative_prompt"] = args.negative_prompt
    if args.style_override is not None:
        config_kw["style_override"] = args.style_override
    if args.consistency_threshold is not None:
        config_kw["consistency_threshold"] = args.consistency_threshold
    if args.max_retries is not None:
        config_kw["max_retries"] = args.max_retries
    config = PipelineConfig(**config_kw)

    # Load VideoConfig (always — video.json is the sole input)
    from pathlib import Path

    from grok_spicy.config import load_video_config

    config_path = Path(args.config) if args.config else None
    video_config = load_video_config(config_path)
    logger.info(
        "Config loaded — v%s, intensity=%s, %d characters, %d modifiers",
        video_config.version,
        video_config.spicy_mode.intensity,
        len(video_config.characters),
        len(video_config.spicy_mode.enabled_modifiers),
    )

    if video_config.story_plan is None:
        print(
            "Error: video.json must contain a 'story_plan' section with "
            "title, style, color_palette, characters, and scenes.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Re-configure logging now that we know the verbosity flag
    setup_logging(verbose=args.verbose)

    # ─── --web mode: server only, no pipeline ─────────────────
    if args.web:
        import uvicorn

        from grok_spicy.db import init_db
        from grok_spicy.web import app, set_db

        set_db(init_db())
        logger.info("Starting dashboard-only mode on port %d", args.port)
        print()
        print("=" * 60)
        print(f"  DASHBOARD: http://localhost:{args.port}")
        print("=" * 60)
        print()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        sys.exit(0)

    # Environment validation (skip in dry-run mode)
    if config.dry_run:
        print("=== DRY-RUN MODE: writing prompts (output/runs/<id>/prompts/) ===")
    else:
        api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
        if not api_key:
            print(
                "Error: No API key found.\n"
                "Set GROK_API_KEY in .env or as an environment variable.",
                file=sys.stderr,
            )
            sys.exit(1)

        if not shutil.which("ffmpeg"):
            print(
                "Warning: FFmpeg not found on PATH. "
                "Steps 5-6 (video generation/assembly) will fail.\n"
                "Install it: https://ffmpeg.org/download.html",
                file=sys.stderr,
            )

    concept = video_config.story_plan.title
    logger.info("Running pipeline for: %s", concept)

    # ─── --serve mode: pipeline + dashboard server ────────────
    if args.serve:
        import threading

        import uvicorn

        from grok_spicy.db import init_db
        from grok_spicy.observer import WebObserver
        from grok_spicy.web import app, event_bus, set_db

        conn = init_db()
        set_db(conn)

        logger.info("Starting pipeline+dashboard mode on port %d", args.port)
        server_thread = threading.Thread(
            target=uvicorn.run,
            args=(app,),
            kwargs={"host": "0.0.0.0", "port": args.port, "log_level": "warning"},
            daemon=True,
        )
        server_thread.start()

        from grok_spicy.pipeline import video_pipeline

        # Prefect's import triggers dictConfig which clobbers our logger config;
        # re-apply so our handlers and propagate=False survive.
        setup_logging(verbose=args.verbose)

        print()
        print("=" * 60)
        print(f"  DASHBOARD: http://localhost:{args.port}")
        print("  (ignore the Prefect server URL above — that is internal)")
        print("=" * 60)
        print()

        observer = WebObserver(conn, event_bus)
        result = video_pipeline(
            video_config,
            observer=observer,
            config=config,
        )
        print(f"\nDone: {result}")

        print()
        print("=" * 60)
        print("  Run complete.")
        print(f"  DASHBOARD: http://localhost:{args.port}")
        print("  Press Ctrl+C to stop the server.")
        print("=" * 60)
        server_thread.join()
    else:
        # ─── Default: pipeline only ──────────────────────────
        from grok_spicy.pipeline import video_pipeline

        # Prefect's import triggers dictConfig which clobbers our logger config;
        # re-apply so our handlers and propagate=False survive.
        setup_logging(verbose=args.verbose)

        result = video_pipeline(
            video_config,
            config=config,
        )
        print(f"\nDone: {result}")


if __name__ == "__main__":
    main()
