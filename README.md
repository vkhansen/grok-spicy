# Grok Spicy

An automated video production pipeline that turns a short text concept into a multi-scene video with visually consistent characters. Powered entirely by xAI's Grok API family and orchestrated with Prefect.

**Input:** `"A curious fox meets a wise owl in an enchanted autumn forest"`
**Output:** A ~24-second assembled video at 720p with consistent characters across all scenes.

## Prerequisites

- **Python 3.12+**
- **FFmpeg** installed and on PATH ([download](https://ffmpeg.org/download.html))
- **Grok API key** from [xAI](https://x.ai/)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-org/grok-spicy.git
cd grok-spicy

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# 3. Install the package
pip install -e .

# 4. Set up your API key
cp .env.example .env
# Edit .env and add your GROK_API_KEY

# 5. Run the pipeline
python -m grok_spicy "A curious fox meets a wise owl in an enchanted autumn forest"
```

The pipeline takes ~5-6 minutes and costs ~$3.80 per run (2 characters, 3 scenes). Output lands in `output/final_video.mp4`.

## Pipeline Flow

The pipeline is a six-step process orchestrated as a Prefect flow (`src/grok_spicy/pipeline.py`). Each step is a Prefect task with automatic retries, caching, and observability.

```
  User Concept (1-2 sentences)
          |
          v
  ┌───────────────────────────────────────────────────────┐
  │ STEP 1: IDEATION                                      │
  │ Model: grok-4-1-fast-non-reasoning                    │
  │                                                       │
  │ Takes the concept and produces a structured StoryPlan │
  │ via chat.parse(). The StoryPlan contains:             │
  │   - Title, visual style, color palette                │
  │   - Characters (each with 80+ word frozen description)│
  │   - Scenes (setting, camera, action, duration)        │
  │                                                       │
  │ The visual_description on each character is the SOLE  │
  │ source of truth for appearance — used verbatim in     │
  │ every downstream image prompt.                        │
  └───────────────────┬───────────────────────────────────┘
                      v
  ┌───────────────────────────────────────────────────────┐
  │ STEP 2: CHARACTER SHEETS (parallel)                   │
  │ Models: grok-imagine-image + grok-4-1-fast-reasoning  │
  │                                                       │
  │ For each character, runs a generate-verify loop:      │
  │   1. Generate portrait from style + description       │
  │   2. Vision model scores it against the description   │
  │   3. If score < 0.80, retry (max 3 attempts)          │
  │                                                       │
  │ Characters are generated in parallel via Prefect      │
  │ .submit(). All attempts saved to disk for debugging.  │
  └───────────────────┬───────────────────────────────────┘
                      v
  ┌───────────────────────────────────────────────────────┐
  │ STEP 3: KEYFRAMES (sequential — frame chaining)       │
  │ Models: grok-imagine-image + grok-4-1-fast-reasoning  │
  │                                                       │
  │ For each scene, composes a keyframe using multi-image │
  │ editing with character sheets as reference inputs:     │
  │   - Slot 1-2: character reference portraits           │
  │   - Slot 3: previous scene's keyframe (continuity)    │
  │   (max 3 images per API limit)                        │
  │                                                       │
  │ Each keyframe goes through a vision consistency check  │
  │ and targeted edit loop (max 3 iterations).            │
  │                                                       │
  │ Sequential because each scene's keyframe feeds into   │
  │ the next scene for visual continuity.                 │
  └───────────────────┬───────────────────────────────────┘
                      v
  ┌───────────────────────────────────────────────────────┐
  │ STEP 4: SCRIPT COMPILATION (no API calls)             │
  │                                                       │
  │ Pure Python — compiles all assets into:               │
  │   - output/script.md   (human-readable storyboard)   │
  │   - output/state.json  (machine-readable state for   │
  │                         pipeline resumability)        │
  └───────────────────┬───────────────────────────────────┘
                      v
  ┌───────────────────────────────────────────────────────┐
  │ STEP 5: VIDEO GENERATION (sequential)                 │
  │ Models: grok-imagine-video + grok-4-1-fast-reasoning  │
  │                                                       │
  │ For each scene:                                       │
  │   1. Generate video from keyframe image               │
  │      (motion-only prompt — no appearance text)        │
  │   2. Extract first + last frame via FFmpeg            │
  │   3. Vision-check last frame for character drift      │
  │   4. If drift detected and clip ≤ 8s, run video edit │
  │      correction (max 2 passes)                        │
  │                                                       │
  │ Video prompts deliberately omit character appearance  │
  │ — the keyframe image carries the visual truth.        │
  │ Adding appearance text causes a tug-of-war that       │
  │ increases drift.                                      │
  └───────────────────┬───────────────────────────────────┘
                      v
  ┌───────────────────────────────────────────────────────┐
  │ STEP 6: ASSEMBLY                                      │
  │ Tool: FFmpeg                                          │
  │                                                       │
  │   1. Normalize all clips (24fps, 1280x720, H.264)    │
  │   2. Concatenate into output/final_video.mp4          │
  │   3. Save final pipeline state to state.json          │
  └───────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Frozen descriptions** — The `visual_description` from Step 1 is never paraphrased. The exact same string is used in every image prompt.
- **Multi-image anchoring** — Character sheets are always passed as `image_urls[]` references, never relying on text alone.
- **Last-frame chaining** — Each scene's keyframe references the previous scene's output for visual continuity.
- **Motion-only video prompts** — Step 5 prompts describe camera and action, not appearance. The keyframe carries appearance truth.
- **Vision-in-the-loop** — Every generated asset is checked by Grok Vision against reference sheets, with surgical fix prompts on failure.

## Output Structure

```
output/
├── character_sheets/
│   ├── Ember_v1.jpg, Ember_v2.jpg    # All attempts kept
│   └── Sage_v1.jpg
├── keyframes/
│   ├── scene_1_v1.jpg, scene_1_v2.jpg
│   └── scene_2_v1.jpg
├── frames/
│   ├── scene_1_first.jpg, scene_1_last.jpg
│   └── scene_2_first.jpg, scene_2_last.jpg
├── videos/
│   ├── scene_1.mp4, scene_1_c1.mp4   # Original + corrections
│   └── scene_2.mp4
├── script.md          # Human-readable storyboard
├── state.json         # Full pipeline state (resumable)
└── final_video.mp4    # Assembled output
```

## Development Setup

```bash
# Install all dependencies (runtime + dev tools)
pip install -r requirements-dev.txt
pip install -e .
```

## Linting & Formatting

All tool configuration lives in `pyproject.toml`. CI runs these checks on every push and pull request to `main`.

```bash
# Auto-fix formatting
python -m isort .
python -m black .

# Check only (CI mode — exits non-zero on violations)
python -m isort . --check-only --diff
python -m black . --check --diff
python -m ruff check .
python -m mypy src/grok_spicy/
```

| Tool | Purpose | Config |
|---|---|---|
| **black** | Code formatting | line-length 88, Python 3.12 |
| **isort** | Import sorting | `profile = "black"`, first-party = `grok_spicy` |
| **ruff** | Fast linter | Rules: E, F, W, I, UP, B, SIM |
| **mypy** | Static type checking | `ignore_missing_imports`, `check_untyped_defs` |

## Testing

```bash
# Run all tests
python -m pytest tests/ --tb=short -q

# Run a specific test file
python -m pytest tests/test_schemas.py -v

# Run with verbose output
python -m pytest tests/ -v --tb=long

# Run tests matching a pattern
python -m pytest tests/ -k "test_round_trip"
```

### Test Structure

```
tests/
├── test_schemas.py    # Pydantic model validation, JSON round-trips, field bounds
└── test_client.py     # Constants verification, base64 encoding helper
```

**`test_schemas.py`** covers:
- `StoryPlan.model_json_schema()` produces valid JSON Schema
- `StoryPlan` and `PipelineState` round-trip through JSON serialization
- `ConsistencyScore` field bounds (0.0-1.0)
- `Scene.duration_seconds` bounds (3-15)

**`test_client.py`** covers:
- All pipeline constants match expected values
- `to_base64()` correctly encodes file contents

Tests use `pythonpath = ["src"]` configured in `pyproject.toml`, so imports work without installing the package.

## CI Pipeline

GitHub Actions workflow at `.github/workflows/ci.yml` runs automatically on push and pull requests to `main`:

| Job | Steps |
|---|---|
| **lint** | isort check, black check, ruff check, mypy type check |
| **test** | Install package, run pytest |

## Project Structure

```
grok-spicy/
├── .github/workflows/ci.yml       # CI pipeline
├── CLAUDE.md                       # AI assistant context
├── pyproject.toml                  # Package config + tool settings
├── requirements.txt                # Runtime dependencies
├── requirements-dev.txt            # Dev dependencies (linting, testing)
├── .env.example                    # Environment variable template
├── .gitignore
├── src/
│   └── grok_spicy/
│       ├── __init__.py             # Package version
│       ├── __main__.py             # CLI entry point
│       ├── schemas.py              # Pydantic models (data contracts)
│       ├── client.py               # xAI SDK wrapper + helpers
│       ├── pipeline.py             # Prefect flow (main orchestration)
│       └── tasks/
│           ├── ideation.py         # Step 1: concept → StoryPlan
│           ├── characters.py       # Step 2: generate + verify portraits
│           ├── keyframes.py        # Step 3: multi-image scene composition
│           ├── script.py           # Step 4: markdown storyboard
│           ├── video.py            # Step 5: image → video + corrections
│           └── assembly.py         # Step 6: FFmpeg concat
├── tests/
│   ├── test_schemas.py
│   └── test_client.py
├── docs/features/                  # MVP feature cards
└── grok-video-pipeline-plan.md     # Original design document
```

## API Models Used

| Model | Purpose | Used In |
|---|---|---|
| `grok-4-1-fast-non-reasoning` | Structured output (StoryPlan) | Step 1 |
| `grok-4-1-fast-reasoning` | Vision checks (consistency scoring) | Steps 2, 3, 5 |
| `grok-imagine-image` | Image generation + editing | Steps 2, 3 |
| `grok-imagine-video` | Video generation + editing | Step 5 |

## Cost & Performance

| Metric | Value |
|---|---|
| Cost per run | ~$3.80 |
| Runtime | ~5-6 minutes |
| Output duration | ~24 seconds |
| Resolution | 720p, 16:9 |
| Characters | 2 max per scene |
| Scenes | 3-5 |
