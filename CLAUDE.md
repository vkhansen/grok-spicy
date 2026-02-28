# Grok Spicy — Video Pipeline

## What This Is

An automated video production pipeline that turns a short text concept into a multi-scene video with consistent characters. Powered entirely by xAI's Grok API family (image gen, video gen, vision, structured outputs) and orchestrated with Prefect. Includes an optional live web dashboard for watching runs in real time.

## Tech Stack

- **Python 3.12+**
- **xai-sdk** — xAI native SDK for image/video/chat (NOT the OpenAI SDK — it doesn't support image editing)
- **Prefect** — workflow orchestration, retries, caching, observability
- **Pydantic v2** — data contracts between pipeline steps, structured output parsing
- **FFmpeg** — frame extraction and final video assembly
- **requests** — downloading temporary asset URLs
- **FastAPI + Jinja2 + htmx** — optional web dashboard (`pip install -e ".[web]"`)
- **SQLite** — pipeline run persistence (stdlib `sqlite3`, no ORM)

## Architecture

Six-step pipeline, each step a Prefect task, with an observer pattern for live updates:

1. **Ideation** — `grok-4-1-fast-non-reasoning` + `chat.parse(StoryPlan)` → structured story plan
2. **Character Sheets** — `grok-imagine-image` text→image OR stylize from reference photo + `grok-4-1-fast-reasoning` vision verify loop
3. **Keyframe Composition** — `grok-imagine-image` multi-image edit (max 3 refs) + vision consistency
4. **Script Compilation** — pure Python, generates `script.md` + `state.json`
5. **Video Generation** — `grok-imagine-video` image→video + drift correction via video edit
6. **Assembly** — FFmpeg normalize + concatenate → `final_video.mp4`

### Observer Pattern

The pipeline calls `observer.on_*()` at each step boundary. Two implementations:
- **`NullObserver`** — default, all no-ops, zero overhead (CLI-only)
- **`WebObserver`** — writes to SQLite via `db.py` + pushes events to `EventBus` for SSE

Observer calls are fire-and-forget — errors are caught and logged, never crash the pipeline.

### Web Dashboard

- **`web.py`** — FastAPI app with routes for HTML pages, JSON API, SSE stream, static files
- **`templates/`** — Jinja2 + htmx + SSE for live-reloading, dark theme, zero npm
- **`db.py`** — 7-table SQLite schema (runs, characters, scenes, reference_images, character_assets, keyframe_assets, video_assets)
- **`events.py`** — Thread-safe `EventBus` bridging sync pipeline → async SSE via `asyncio.Queue`

### Reference Image Upload

Users can provide photos of real people or character art before a run:
- **Dashboard**: `/new` form with concept + 2 image upload slots
- **CLI**: `--ref "Alex=photos/alex.jpg"` (repeatable)
- Names are injected as hints into the ideation prompt
- If exact match fails, LLM fallback maps labels → character names via `chat.parse(CharacterRefMapping)`
- `generate_character_sheet` uses `image_url` (single-image edit/stylize) when reference is provided
- Characters without references generate from scratch as before

## Key Constraints

- Multi-image edit accepts **max 3 images** — limit 2 characters per scene, reserve slot 3 for frame chaining
- Video edit input max **8.7 seconds** — keep scenes ≤ 8s for correction eligibility
- Video/image URLs are **temporary** — download immediately after generation
- Structured output (`chat.parse()`) requires **Grok 4 family** models only
- OpenAI SDK `images.edit()` does NOT work — must use xAI SDK or direct HTTP with JSON body

## Project Structure

```
grok-spicy/
├── CLAUDE.md
├── pyproject.toml
├── src/
│   └── grok_spicy/
│       ├── __init__.py
│       ├── __main__.py          # CLI entry point (--serve, --web, --ref)
│       ├── schemas.py           # Pydantic models (StoryPlan, CharacterRefMapping, etc.)
│       ├── client.py            # xAI SDK wrapper + helpers
│       ├── db.py                # SQLite schema + CRUD functions
│       ├── events.py            # Thread-safe EventBus (sync→async bridge)
│       ├── observer.py          # PipelineObserver protocol + NullObserver + WebObserver
│       ├── web.py               # FastAPI dashboard app
│       ├── templates/
│       │   ├── base.html        # Layout shell (htmx + dark theme)
│       │   ├── index.html       # Run list
│       │   ├── new_run.html     # New run form + image upload
│       │   └── run.html         # Live-updating run detail (SSE)
│       ├── tasks/
│       │   ├── __init__.py
│       │   ├── ideation.py      # Step 1: plan_story
│       │   ├── characters.py    # Step 2: generate_character_sheet (+ stylize mode)
│       │   ├── keyframes.py     # Step 3: compose_keyframe
│       │   ├── script.py        # Step 4: compile_script
│       │   ├── video.py         # Step 5: generate_scene_video
│       │   └── assembly.py      # Step 6: assemble_final_video
│       └── pipeline.py          # Prefect flow wiring + observer hooks
├── docs/
│   └── features/                # Feature cards (numbered)
├── output/                      # Generated assets (gitignored)
└── tests/
```

## Conventions

- All inter-step data passes through Pydantic models defined in `schemas.py`
- Every image/video prompt starts with `plan.style` (the "style lock")
- Character `visual_description` is frozen from Step 1 — never paraphrased, used verbatim everywhere
- Video prompts describe **motion only**, not appearance (the keyframe image carries visual truth)
- Download every generated asset immediately — URLs expire
- Vision-in-the-loop: every generation is checked against character reference sheets
- Observer calls are fire-and-forget — wrapped in try/except, never crash the pipeline
- Web dependencies (FastAPI, uvicorn, Jinja2) are optional — only imported when `--serve` or `--web` is used

## Environment

- `GROK_API_KEY` environment variable (or `.env` file) required
- FFmpeg must be installed and on PATH
- Prefect server optional (works with local ephemeral server)

## Running

```bash
# Install (core only)
pip install -e .

# Install with web dashboard
pip install -e ".[web]"

# Run pipeline (CLI only)
python -m grok_spicy "A curious fox meets a wise owl in an enchanted forest"

# Run pipeline with live dashboard
python -m grok_spicy "A fox and owl adventure" --serve

# Run pipeline with character reference images
python -m grok_spicy "A spy thriller" --ref "Alex=photos/alex.jpg" --ref "Maya=photos/maya.jpg"

# Dashboard only (browse past runs, launch new ones from web)
python -m grok_spicy --web

# Or via Prefect
prefect deployment run grok-video-pipeline/default --param concept="..."
```

## Linting & Formatting

All tools are configured in `pyproject.toml`. CI runs these on every push/PR.

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Auto-fix formatting
python -m isort .
python -m black .

# Check (CI mode — no changes, just report)
python -m isort . --check-only --diff
python -m black . --check --diff
python -m ruff check .
python -m mypy src/grok_spicy/
```

**Tool config:**
- **black** — line length 88, target Python 3.12
- **isort** — `profile = "black"`, first-party = `grok_spicy`
- **ruff** — rules: E, F, W, I, UP, B, SIM (no E501)
- **mypy** — `ignore_missing_imports = true`, `check_untyped_defs = true`

## Testing

```bash
# Run all tests
python -m pytest tests/ --tb=short -q

# Run a specific test file
python -m pytest tests/test_schemas.py -v
```

Tests live in `tests/` with `pythonpath = ["src"]` set in `pyproject.toml`.

## CI Pipeline

GitHub Actions workflow at `.github/workflows/ci.yml` runs on push/PR to `main`:
- **lint** job — isort, black, ruff, mypy
- **test** job — pytest

## Cost & Runtime

- ~$3.80 per run (2 characters, 3 scenes)
- ~5-6 minutes end-to-end
- Output: ~24s video, 720p, 16:9
