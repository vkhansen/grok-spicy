"""CLI entry point for grok-spicy."""

import argparse
import sys


def main():
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

    # Pipeline import deferred to Card 10
    print(f"grok-spicy v0.1.0")
    print(f"Concept: {args.concept}")
    print(f"Output:  {args.output_dir}")
    print("Pipeline not yet implemented — see docs/features/ for build plan.")


if __name__ == "__main__":
    main()
