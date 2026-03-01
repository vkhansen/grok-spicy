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

Seven-step pipeline (six core + one pre-ideation), each step a Prefect task, with an observer pattern for live updates:

0. **Reference Description** (optional) — `grok-4-1-fast-reasoning` vision extracts visual descriptions from uploaded reference photos → `CharacterDescription`
1. **Ideation** — `grok-4-1-fast-non-reasoning` + `chat.parse(StoryPlan)` → structured story plan (uses `SPICY_SYSTEM_PROMPT` when spicy mode is active)
2. **Character Sheets** — `grok-imagine-image` text→image OR stylize from reference photo + `grok-4-1-fast-reasoning` vision verify loop
3. **Keyframe Composition** — `grok-imagine-image` multi-image edit (max 3 refs) + vision consistency
4. **Script Compilation** — pure Python, generates `script.md` + `state.json`
5. **Video Generation** — `grok-imagine-video` image→video + drift correction via video edit (tier-aware: ≤8s correction-eligible, 9-15s extended)
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
- **Scene duration tiers**: 3-8s = correction-eligible (drift fix loop), 9-15s = extended (no corrections, only extended-retry if score < 0.50)
- **Scene count**: 3-6 total (ideally 4-5), each 6-10s with one primary action
- **Characters per scene**: 1-3 (max 4) to avoid visual clutter
- **Moderation auto-reword**: max 2 attempts to rewrite blocked prompts while preserving scene/character/camera/style
- **Extended retry threshold**: 0.50 — extended-tier scenes below this score are regenerated from scratch

## Project Structure

```
grok-spicy/
├── CLAUDE.md
├── pyproject.toml
├── video.json                   # Spicy mode config (default, edit this)
├── examples/                    # Example video.json configs (low/medium/high/extreme/solo/scene-only)
├── src/
│   └── grok_spicy/
│       ├── __init__.py
│       ├── __main__.py          # CLI entry point (--serve, --web, --ref, --spicy, --config, --dry-run)
│       ├── schemas.py           # Pydantic models (StoryPlan, VideoConfig, SpicyMode, etc.)
│       ├── client.py            # xAI SDK wrapper + helpers
│       ├── config.py            # video.json loader with caching + graceful fallback
│       ├── dry_run.py            # Dry-run helpers (write prompts to markdown files)
│       ├── prompts.py           # Pure prompt builder functions (all pipeline prompts)
│       ├── prompt_builder.py    # Spicy prompt composer (0/1/2+ character logic)
│       ├── pipeline.py          # Prefect flow wiring + observer hooks
│       ├── db.py                # SQLite schema + CRUD functions
│       ├── events.py            # Thread-safe EventBus (sync→async bridge)
│       ├── observer.py          # PipelineObserver protocol + NullObserver + WebObserver
│       ├── web.py               # FastAPI dashboard app
│       ├── templates/
│       │   ├── base.html        # Layout shell (htmx + dark theme)
│       │   ├── index.html       # Run list
│       │   ├── new_run.html     # New run form + image upload
│       │   └── run.html         # Live-updating run detail (SSE)
│       └── tasks/
│           ├── __init__.py
│           ├── describe_ref.py  # Step 0: extract visual description from reference photos
│           ├── ideation.py      # Step 1: plan_story (+ SPICY_SYSTEM_PROMPT)
│           ├── characters.py    # Step 2: generate_character_sheet (+ stylize mode)
│           ├── keyframes.py     # Step 3: compose_keyframe
│           ├── script.py        # Step 4: compile_script
│           ├── video.py         # Step 5: generate_scene_video (tier-aware)
│           └── assembly.py      # Step 6: assemble_final_video
├── docs/
│   └── features/                # Feature cards (01-14, numbered)
├── output/                      # Generated assets (gitignored)
│   ├── grok_spicy.db            # Shared SQLite database
│   ├── staging/                 # Temporary pre-run-id files
│   │   └── references/          # CLI --ref and spicy config image downloads
│   └── runs/
│       └── {run_id}/            # Per-run directory (DB id or timestamp)
│           ├── state.json
│           ├── script.md
│           ├── concat.txt
│           ├── final.mp4
│           ├── characters/      # Character reference portraits
│           ├── keyframes/
│           ├── videos/
│           ├── frames/
│           ├── references/      # Copied from staging at run start
│           └── prompts/         # Dry-run prompt files
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
- All prompt construction lives in `prompts.py` as pure functions — one per prompt type
- Spicy mode is entirely config-driven via `video.json` — no code changes needed for new characters/traits
- Reference descriptions from photos override LLM-generated `visual_description` (injected verbatim)
- Character `spicy_traits` from `VideoConfig` are merged into plan characters by name match after ideation

## Spicy Mode

Config-driven adult content pipeline controlled via `video.json` (no code changes needed):

- **Activation**: `--spicy` CLI flag loads `video.json` (or `--config path.json`)
- **Config schema**: `VideoConfig` → `SpicyMode` + `SpicyCharacter[]` + `DefaultVideo`
- **Intensity levels**: `low` (1 modifier), `medium` (2), `high` (all), `extreme` (all + emphasis)
- **Integration points**: ideation system prompt swaps to `SPICY_SYSTEM_PROMPT`, prompts get `global_prefix` + `enabled_modifiers`, characters get `spicy_traits` merged by name match
- **Prompt builder** (`prompt_builder.py`): adapts output based on character count (0 = scene-only, 1 = solo focus, 2+ = interaction)
- **Graceful fallback**: missing/invalid `video.json` logs warning and uses empty defaults (no crash)
- **Example configs** in `examples/` directory (7 presets from low to extreme)

## Dry-Run Mode

Preview all prompts without making API calls or spending money:

- **Activation**: `--dry-run` CLI flag (no API key or FFmpeg required)
- **Behavior**: all prompt construction runs normally, but API calls are replaced with mock returns; every prompt is written to a structured markdown file under `output/dry_run/`
- **Output structure**: `output/dry_run/{step}/{label}.md` + `output/dry_run/summary.md`
- **Mock data**: flows downstream so all steps execute — `StoryPlan` gets 2 characters + 3 scenes with `[DRY-RUN]` prefixed fields, assets get `dry-run://placeholder` URLs and score=1.0
- **Steps skipped**: Step 6 (assembly) is skipped entirely; Step 4 (script) runs unchanged with placeholder paths
- **LLM ref matching**: skips the LLM fallback phase (exact matches still work)
- **Config field**: `PipelineConfig.dry_run: bool = False`

## LLM Models

| Model | Constant | Purpose |
|---|---|---|
| `grok-4-1-fast-non-reasoning` | `MODEL_STRUCTURED` | Structured output (StoryPlan, CharacterRefMapping) |
| `grok-4-1-fast-reasoning` | `MODEL_REASONING` | Vision checks, reference photo description |
| `grok-imagine-image` | `MODEL_IMAGE` | Image generation + editing + stylization |
| `grok-imagine-video` | `MODEL_VIDEO` | Video generation + drift correction |

## Environment

- `GROK_API_KEY` or `XAI_API_KEY` environment variable (or `.env` file) required (not needed for `--dry-run`)
- FFmpeg must be installed and on PATH (not needed for `--dry-run`)
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

# Run pipeline with spicy mode
python -m grok_spicy "A romantic encounter" --spicy
python -m grok_spicy "A romantic encounter" --spicy --config examples/video-extreme.json

# Dry run — preview all prompts without API calls (no key needed)
python -m grok_spicy "A fox and owl adventure" --dry-run
python -m grok_spicy "A romance" --dry-run --spicy --ref "Alex=photo.jpg"

# Run from a prompt file (one or more concepts)
python -m grok_spicy --prompt-file my_prompts.txt

# Pre-built StoryPlan JSON (skips ideation)
python -m grok_spicy --script output/state.json

# Tune generation
python -m grok_spicy "concept" --max-duration 8 --consistency-threshold 0.85 --negative-prompt "blurry"

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
