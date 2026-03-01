# Feature 02: Data Models & Schemas

**Priority:** P0 — Foundation
**Depends on:** Card 01 (Project Scaffolding)
**Blocks:** Cards 04–10

---

## Goal

Implement all Pydantic models in `src/grok_spicy/schemas.py`. These are the typed contracts between every pipeline step and are passed directly to Grok's `chat.parse()` for structured output.

## Deliverables

### `schemas.py` — Full implementation

**Story Plan models (Step 1 output):**
- `Character` — name, role, visual_description (80+ words, frozen identity string), personality_cues
- `Scene` — scene_id, title, description, characters_present, setting, camera, mood, action, duration_seconds (3–15), transition
- `StoryPlan` — title, style (specific visual style prefix), aspect_ratio, color_palette, characters[], scenes[]

**Consistency scoring (Steps 2–3–5 vision checks):**
- `ConsistencyScore` — overall_score (0–1), per_character dict, issues[], fix_prompt (optional surgical edit instruction)

**Asset tracking (pipeline state):**
- `CharacterAsset` — name, portrait_url, portrait_path, visual_description, consistency_score, generation_attempts
- `KeyframeAsset` — scene_id, keyframe_url, keyframe_path, consistency_score, generation_attempts, edit_passes, video_prompt
- `VideoAsset` — scene_id, video_url, video_path, duration, first_frame_path, last_frame_path, consistency_score, correction_passes

**Pipeline state (resumability):**
- `PipelineState` — plan, characters[], keyframes[], videos[], final_video_path

### Field validation

- `Scene.duration_seconds`: `ge=3, le=15`
- `ConsistencyScore.overall_score`: `ge=0.0, le=1.0`
- All `Field(description=...)` populated — these descriptions are used by `chat.parse()` to guide the LLM

## Acceptance Criteria

- [ ] All models from plan Section 3 are implemented
- [ ] `StoryPlan.model_json_schema()` produces valid JSON Schema
- [ ] `PipelineState` can round-trip through `model_dump_json()` → `model_validate_json()`
- [ ] Field descriptions are detailed enough for structured output parsing
