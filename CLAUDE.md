# Grok Spicy — Video Pipeline

## What This Is

An automated video production pipeline that turns a short text concept into a multi-scene video with consistent characters. Powered entirely by xAI's Grok API family (image gen, video gen, vision, structured outputs) and orchestrated with Prefect.

## Tech Stack

- **Python 3.12+**
- **xai-sdk** — xAI native SDK for image/video/chat (NOT the OpenAI SDK — it doesn't support image editing)
- **Prefect** — workflow orchestration, retries, caching, observability
- **Pydantic v2** — data contracts between pipeline steps, structured output parsing
- **FFmpeg** — frame extraction and final video assembly
- **requests** — downloading temporary asset URLs

## Architecture

Six-step pipeline, each step a Prefect task:

1. **Ideation** — `grok-4-1-fast-non-reasoning` + `chat.parse(StoryPlan)` → structured story plan
2. **Character Sheets** — `grok-imagine-image` text→image + `grok-4-1-fast-reasoning` vision verify loop
3. **Keyframe Composition** — `grok-imagine-image` multi-image edit (max 3 refs) + vision consistency
4. **Script Compilation** — pure Python, generates `script.md` + `state.json`
5. **Video Generation** — `grok-imagine-video` image→video + drift correction via video edit
6. **Assembly** — FFmpeg normalize + concatenate → `final_video.mp4`

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
│       ├── __main__.py          # CLI entry point
│       ├── schemas.py           # Pydantic models (StoryPlan, ConsistencyScore, etc.)
│       ├── client.py            # xAI SDK wrapper + helpers
│       ├── tasks/
│       │   ├── __init__.py
│       │   ├── ideation.py      # Step 1: plan_story
│       │   ├── characters.py    # Step 2: generate_character_sheet
│       │   ├── keyframes.py     # Step 3: compose_keyframe
│       │   ├── script.py        # Step 4: compile_script
│       │   ├── video.py         # Step 5: generate_scene_video
│       │   └── assembly.py      # Step 6: assemble_final_video
│       └── pipeline.py          # Prefect flow wiring
├── docs/
│   └── features/                # MVP feature cards (numbered)
├── output/                      # Generated assets (gitignored)
└── grok-video-pipeline-plan.md  # Original design doc
```

## Conventions

- All inter-step data passes through Pydantic models defined in `schemas.py`
- Every image/video prompt starts with `plan.style` (the "style lock")
- Character `visual_description` is frozen from Step 1 — never paraphrased, used verbatim everywhere
- Video prompts describe **motion only**, not appearance (the keyframe image carries visual truth)
- Download every generated asset immediately — URLs expire
- Vision-in-the-loop: every generation is checked against character reference sheets

## Environment

- `XAI_API_KEY` environment variable (or `.env` file) required
- FFmpeg must be installed and on PATH
- Prefect server optional (works with local ephemeral server)

## Running

```bash
# Install
pip install -e .

# Run pipeline
python -m grok_spicy "A curious fox meets a wise owl in an enchanted forest"

# Or via Prefect
prefect deployment run grok-video-pipeline/default --param concept="..."
```

## Cost & Runtime

- ~$3.80 per run (2 characters, 3 scenes)
- ~5-6 minutes end-to-end
- Output: ~24s video, 720p, 16:9
