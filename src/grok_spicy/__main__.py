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

    - File handler: DEBUG level → ``{log_dir}/grok_spicy.log`` (always)
    - Console handler: DEBUG level (if *verbose*) or INFO level → stderr

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


def _parse_refs(raw_refs: list[str]) -> dict[str, str]:
    """Parse --ref NAME=PATH args into {name: dest_path} dict."""
    character_refs: dict[str, str] = {}
    for ref in raw_refs:
        name, _, path = ref.partition("=")
        name = name.strip()
        path = path.strip()
        if not path or not os.path.isfile(path):
            print(f"Warning: reference image not found: {path}", file=sys.stderr)
            continue
        safe_name = name.replace(" ", "_")
        dest = f"output/references/{safe_name}.jpg"
        os.makedirs("output/references", exist_ok=True)
        shutil.copy2(path, dest)
        character_refs[name] = dest
    return character_refs


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="grok-spicy",
        description="Generate a multi-scene video from a text concept using Grok APIs",
    )
    parser.add_argument("concept", nargs="?", help="Story concept (1-2 sentences)")
    parser.add_argument(
        "--prompt-file",
        metavar="FILE",
        help="Read concepts from a text file (blocks separated by blank lines; "
        "lines starting with # are comments)",
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
        "--ref",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Character reference image: NAME=PATH (repeatable)",
    )
    parser.add_argument(
        "--script",
        metavar="FILE",
        help="Path to a JSON file matching the StoryPlan schema. "
        "Skips ideation — the plan is used verbatim.",
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
        help="Replace the LLM-generated plan.style with this string",
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

    # Re-configure logging now that we know the verbosity flag
    setup_logging(verbose=args.verbose)

    # ─── --script mode: load pre-built StoryPlan ──────────────
    script_plan = None
    if args.script:
        if not os.path.isfile(args.script):
            print(f"Error: script file not found: {args.script}", file=sys.stderr)
            sys.exit(1)
        from grok_spicy.schemas import StoryPlan

        with open(args.script, encoding="utf-8") as f:
            raw = f.read()
        try:
            script_plan = StoryPlan.model_validate_json(raw)
        except Exception as exc:
            print(f"Error: invalid script file: {exc}", file=sys.stderr)
            sys.exit(1)
        logger.info(
            "Loaded script plan: title=%r, %d characters, %d scenes",
            script_plan.title,
            len(script_plan.characters),
            len(script_plan.scenes),
        )

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

    # Build list of concepts to run
    concepts: list[str] = []
    if args.prompt_file:
        path = args.prompt_file
        if not os.path.isfile(path):
            print(f"Error: prompt file not found: {path}", file=sys.stderr)
            sys.exit(1)
        # Parse prompt file: blank lines separate concepts, # lines are comments.
        # Consecutive non-blank lines are joined with spaces into one concept.
        with open(path, encoding="utf-8") as f:
            raw_lines = f.readlines()
        current_block: list[str] = []
        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                # Blank line = concept separator
                if current_block:
                    concepts.append(" ".join(current_block))
                    current_block = []
            elif not stripped.startswith("#"):
                current_block.append(stripped)
        if current_block:
            concepts.append(" ".join(current_block))
        if not concepts:
            print(f"Error: no prompts found in {path}", file=sys.stderr)
            sys.exit(1)
        logger.info("Loaded %d concept(s) from %s", len(concepts), path)
        for idx, c in enumerate(concepts, 1):
            logger.debug("  Concept %d (%d chars): %.200s", idx, len(c), c)
    elif args.concept:
        concepts.append(args.concept)
    elif script_plan:
        # --script mode: concept not needed, use plan title as placeholder
        concepts.append(script_plan.title)
    else:
        parser.print_help()
        sys.exit(0)

    logger.info(
        "Concepts to process: %d, serve=%s, refs=%d",
        len(concepts),
        args.serve,
        len(args.ref),
    )

    # Environment validation
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

    # Parse reference images
    character_refs = _parse_refs(args.ref) if args.ref else None
    if character_refs:
        logger.info("Parsed reference images: %s", list(character_refs.keys()))

    total = len(concepts)

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

        # Print AFTER Prefect import so it appears below Prefect's
        # "Starting temporary server on http://127.0.0.1:XXXX" message.
        # That Prefect URL is NOT the dashboard — this one is.
        print()
        print("=" * 60)
        print(f"  DASHBOARD: http://localhost:{args.port}")
        print(f"  (ignore the Prefect server URL above — that is internal)")
        print("=" * 60)
        print()

        for i, concept in enumerate(concepts, 1):
            if total > 1:
                print(f"\n{'='*60}")
                print(f"[{i}/{total}] {concept}")
                print(f"{'='*60}")
            observer = WebObserver(conn, event_bus)
            result = video_pipeline(
                concept,
                observer=observer,
                character_refs=character_refs,
                config=config,
                script_plan=script_plan,
            )
            print(f"\nDone: {result}")

        print()
        print("=" * 60)
        print(f"  All {total} run(s) complete.")
        print(f"  DASHBOARD: http://localhost:{args.port}")
        print(f"  Press Ctrl+C to stop the server.")
        print("=" * 60)
        server_thread.join()
    else:
        # ─── Default: pipeline only ──────────────────────────
        from grok_spicy.pipeline import video_pipeline

        # Prefect's import triggers dictConfig which clobbers our logger config;
        # re-apply so our handlers and propagate=False survive.
        setup_logging(verbose=args.verbose)

        for i, concept in enumerate(concepts, 1):
            if total > 1:
                print(f"\n{'='*60}")
                print(f"[{i}/{total}] {concept}")
                print(f"{'='*60}")
            result = video_pipeline(
                concept,
                character_refs=character_refs,
                config=config,
                script_plan=script_plan,
            )
            print(f"\nDone: {result}")

        if total > 1:
            print(f"\nAll {total} runs complete.")


if __name__ == "__main__":
    main()
