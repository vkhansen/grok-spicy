"""CLI entry point for grok-spicy."""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def setup_logging(log_dir: str = "output") -> None:
    """Configure logging with file and console handlers.

    - File handler: DEBUG level → ``{log_dir}/grok_spicy.log``
    - Console handler: INFO level → stderr
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

    # Console handler — user-visible messages (INFO+)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger("grok_spicy")
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    logging.getLogger("grok_spicy").info(
        "Logging initialised — file=%s (DEBUG), console (INFO)", log_path
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
    setup_logging()

    parser = argparse.ArgumentParser(
        prog="grok-spicy",
        description="Generate a multi-scene video from a text concept using Grok APIs",
    )
    parser.add_argument("concept", nargs="?", help="Story concept (1-2 sentences)")
    parser.add_argument(
        "--prompt-file",
        metavar="FILE",
        help="Read concept from a text file (one concept per line, blank lines ignored)",
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
    args = parser.parse_args()

    # ─── --web mode: server only, no pipeline ─────────────────
    if args.web:
        import uvicorn

        from grok_spicy.db import init_db
        from grok_spicy.web import app, set_db

        set_db(init_db())
        logger.info("Starting dashboard-only mode on port %d", args.port)
        print(f"Dashboard: http://localhost:{args.port}")
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        sys.exit(0)

    # Build list of concepts to run
    concepts: list[str] = []
    if args.prompt_file:
        path = args.prompt_file
        if not os.path.isfile(path):
            print(f"Error: prompt file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    concepts.append(stripped)
        if not concepts:
            print(f"Error: no prompts found in {path}", file=sys.stderr)
            sys.exit(1)
    elif args.concept:
        concepts.append(args.concept)
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
        print(f"Dashboard: http://localhost:{args.port}")

        from grok_spicy.pipeline import video_pipeline

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
            )
            print(f"\nDone: {result}")

        print(
            f"\nAll {total} run(s) complete. "
            f"Dashboard still running at http://localhost:{args.port} "
            f"— Ctrl+C to stop"
        )
        server_thread.join()
    else:
        # ─── Default: pipeline only ──────────────────────────
        from grok_spicy.pipeline import video_pipeline

        for i, concept in enumerate(concepts, 1):
            if total > 1:
                print(f"\n{'='*60}")
                print(f"[{i}/{total}] {concept}")
                print(f"{'='*60}")
            result = video_pipeline(
                concept,
                character_refs=character_refs,
            )
            print(f"\nDone: {result}")

        if total > 1:
            print(f"\nAll {total} runs complete.")


if __name__ == "__main__":
    main()
