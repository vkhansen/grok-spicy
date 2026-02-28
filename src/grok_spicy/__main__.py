"""CLI entry point for grok-spicy."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from dotenv import load_dotenv


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="grok-spicy",
        description="Generate a multi-scene video from a text concept using Grok APIs",
    )
    parser.add_argument("concept", nargs="?", help="Story concept (1-2 sentences)")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()

    if not args.concept:
        parser.print_help()
        sys.exit(0)

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

    from grok_spicy.pipeline import video_pipeline

    result = video_pipeline(args.concept)
    print(f"\nDone: {result}")


if __name__ == "__main__":
    main()
