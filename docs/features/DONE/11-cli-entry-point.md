# Feature 11: CLI Entry Point

**Priority:** P2 — Polish
**Depends on:** Card 10 (Pipeline flow)
**Blocks:** Nothing

---

## Goal

Implement the CLI entry point in `src/grok_spicy/__main__.py` so the pipeline can be invoked from the command line with a concept string.

## Deliverables

### `src/grok_spicy/__main__.py`

**Usage:**
```bash
# Via module
python -m grok_spicy "A fox and owl discover a crystal in an autumn forest"

# Via installed script
grok-spicy "A fox and owl discover a crystal in an autumn forest"
```

### Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `concept` | positional | required | Story concept (1-2 sentences) |
| `--output-dir` | optional | `output/` | Directory for all generated assets |

### Implementation

```python
import argparse
import sys
from grok_spicy.pipeline import video_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Generate a multi-scene video from a text concept using Grok APIs"
    )
    parser.add_argument("concept", help="Story concept (1-2 sentences)")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()

    result = video_pipeline(args.concept)
    print(f"\nDone: {result}")


if __name__ == "__main__":
    main()
```

### Environment validation

Before calling the pipeline, verify:
1. `XAI_API_KEY` is set (or `.env` file exists)
2. `ffmpeg` is available on PATH

Print clear error messages if either is missing.

## Acceptance Criteria

- [ ] `python -m grok_spicy "concept"` invokes the full pipeline
- [ ] `grok-spicy "concept"` works after `pip install -e .`
- [ ] Missing API key produces a helpful error message
- [ ] Missing FFmpeg produces a helpful error message
- [ ] Returns exit code 0 on success, 1 on failure
