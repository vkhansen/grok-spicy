# Feature 12: Extended Video Duration (Up to 15 Seconds)

**Priority:** P2 — Enhancement
**Depends on:** Card 08 (Video Generation)
**Blocks:** Nothing

---

## Goal

Explicitly support the full 1–15 second duration range now available for text-to-video and image-to-video generation via `grok-imagine-video`, while preserving the 8-second ceiling for scenes that need drift-correction eligibility. Because extended-tier scenes **cannot be corrected** after generation, this card also introduces tier-aware prompt construction to compensate for the loss of the drift-correction safety net.

## Background

The `grok-imagine-video` API now supports durations up to **15 seconds** for initial generation (text-to-video and image-to-video). However, the **video edit** endpoint still caps input at **8.7 seconds** — meaning only clips ≤ 8s can enter the drift-correction loop.

The schema (`Scene.duration_seconds`) already validates `ge=3, le=15`, but the pipeline currently treats all scenes uniformly and the ideation prompt defaults toward 8s. This card adds explicit awareness of the two duration tiers so the LLM can make informed choices and the pipeline handles each tier correctly.

### The Prompt Quality Problem

Currently, all video prompts are built with the same inline f-string in `keyframes.py:96-101`:

```python
video_prompt = (
    f"{scene.prompt_summary} "
    f"{scene.camera}. {scene.action}. "
    f"{scene.mood}. {plan.style}. "
    f"Smooth cinematic motion."
)
```

For **standard-tier** scenes (≤ 8s), this is acceptable — if the model drifts, the correction loop catches it. For **extended-tier** scenes (9–15s), this one-shot prompt is all we get. Longer clips amplify two known failure modes:

1. **Action drift** — the model starts executing the described action but veers into unrelated motion by second 10+.
2. **Sequence merging** — multiple actions get blended into a single ambiguous movement instead of playing out sequentially.

This means extended scenes need **stronger, more structured prompts** that constrain the model more tightly — compensating for the absence of iterative correction.

## Duration Tiers

| Tier | Duration | Correction Eligible | Prompt Strategy |
|---|---|---|---|
| **Standard** | 3–8s | Yes | Current prompt + correction loop as safety net |
| **Extended** | 9–15s | No | Enhanced prompt with sequencing, repetition, and negatives |

## Deliverables

### 1. Ideation prompt update — `tasks/ideation.py`

Update the system/user prompt for `plan_story` to inform the LLM about the two tiers:

```
Scene duration guidelines:
- Use 3–8 seconds for scenes with named characters (enables drift correction).
- Use 9–15 seconds for establishing shots, landscapes, or scenes where
  character consistency is less critical.
- Default to 8 seconds when unsure.
```

This lets the LLM produce longer atmospheric scenes when appropriate, without sacrificing correction capability on character-driven scenes.

### 2. CLI flag — `__main__.py`

Add an optional `--max-duration` flag:

```
--max-duration  Maximum per-scene duration in seconds (3-15, default: 15)
```

When set, clamp `Scene.duration_seconds` to this value after ideation. This gives users control — e.g., `--max-duration 8` to force all scenes into the correction-eligible tier.

### 3. Pipeline duration clamping — `pipeline.py`

After ideation returns the `StoryPlan`, clamp each scene's `duration_seconds` to `max_duration`:

```python
for scene in plan.scenes:
    scene.duration_seconds = min(scene.duration_seconds, max_duration)
```

### 4. Tier-aware video prompt builder — `tasks/keyframes.py`

Replace the current inline video prompt construction with a `build_video_prompt()` function that produces different prompt structures depending on the duration tier.

**Standard tier (≤ 8s)** — existing behavior, unchanged:

```python
def build_video_prompt(scene: Scene, plan: StoryPlan) -> str:
    base = (
        f"{scene.prompt_summary} "
        f"{scene.camera}. {scene.action}. "
        f"{scene.mood}. {plan.style}. "
        f"Smooth cinematic motion."
    )
    if scene.duration_seconds <= 8:
        return base
    # ... extended tier below
```

**Extended tier (9–15s)** — structured prompt with three additions:

#### a) Sequenced timing cues

Break the action into timed phases so the model has explicit temporal anchors instead of one blob of motion:

```python
    # For extended scenes, add sequenced timing
    seconds = scene.duration_seconds
    mid = seconds // 2
    prompt = (
        f"{plan.style}. "
        f"Phase 1 (0–{mid}s): {scene.action}. "
        f"Phase 2 ({mid}–{seconds}s): {scene.prompt_summary}. "
        f"{scene.camera}. {scene.mood}. "
        f"Smooth cinematic motion throughout."
    )
```

The ideation prompt (deliverable 1) should also instruct the LLM to populate `scene.action` with a primary motion suitable for the first half, and `scene.prompt_summary` with the culminating motion for the second half, when `duration_seconds > 8`.

#### b) Key-phrase repetition

Repeat the most critical action phrase to fight prompt dilution over long generations:

```python
    # Reinforce the core action
    prompt += f" Maintain: {scene.action}."
```

#### c) Negative constraints

Append explicit exclusions to suppress common extended-scene failure modes:

```python
    # Negative constraints for extended clips
    prompt += (
        " No sudden scene changes. "
        "No freeze frames. No unrelated motion."
    )
```

This keeps prompt construction co-located with the existing keyframe logic (no new modules), but separates the two tiers clearly.

### 5. Logging & observer updates — `tasks/video.py`

Add a log line before generation that indicates the tier:

```python
tier = "standard (correction eligible)" if scene.duration_seconds <= 8 else "extended (no correction)"
logger.info("Scene %d: duration=%ds, tier=%s", scene.scene_id, scene.duration_seconds, tier)
```

The existing correction-eligibility check (`scene.duration_seconds <= 8`) already handles this correctly — no change needed to the correction logic itself.

### 6. Observer event — `observer.py`

Include the duration tier in `on_video_start` calls so the web dashboard can display whether a scene is correction-eligible.

### 7. Extended-scene retry on low score — `tasks/video.py`

For extended-tier scenes, the correction loop is unavailable, but we can still **regenerate from scratch** if the vision check scores very low. Add a single-retry gate:

```python
EXTENDED_RETRY_THRESHOLD = 0.50  # much lower than CONSISTENCY_THRESHOLD

if not correction_eligible and score.overall_score < EXTENDED_RETRY_THRESHOLD:
    logger.warning(
        "Scene %d: extended scene scored %.2f < %.2f, regenerating from scratch",
        scene.scene_id, score.overall_score, EXTENDED_RETRY_THRESHOLD,
    )
    # Rebuild prompt with fix hints appended, then re-generate image→video
    vid_prompt = keyframe.video_prompt + f" Fix: {'; '.join(score.issues)}"
    vid = client.video.generate(prompt=vid_prompt, **vid_kw)
    # ... download, re-extract, re-score
```

This is not a correction (no `video_url` input) — it's a fresh generation with a refined prompt. Caps at 1 retry to limit cost.

## What Does NOT Change

- **Schema validation** — `Scene.duration_seconds` already enforces `ge=3, le=15`
- **Correction logic** — the `<= 8` gate in `video.py:152` is already correct
- **Video edit constraint** — still 8.7s max input, unchanged by API
- **Default behavior** — without `--max-duration`, the LLM is free to use the full range
- **Standard-tier prompts** — no change to prompts for scenes ≤ 8s

## Separation of Concerns: Prompting vs. Code Flow

This card touches both **prompt content** (what the model sees) and **code flow** (how the pipeline behaves). To keep changes reviewable, keep them distinct:

| Category | What Changes | Where |
|---|---|---|
| **Prompting** | Duration tier guidance for ideation LLM | `ideation.py` SYSTEM_PROMPT |
| **Prompting** | Sequenced timing, repetition, negatives for extended video prompts | `keyframes.py` build_video_prompt() |
| **Code flow** | Duration clamping after ideation | `pipeline.py` |
| **Code flow** | Tier logging and observer events | `video.py`, `observer.py` |
| **Code flow** | Extended-scene retry on very low score | `video.py` |
| **Config** | `--max-duration` CLI flag | `__main__.py` |

Prompt changes can be iterated (A/B tested across runs) without touching the code flow, and vice versa.

## Future Work (Out of Scope)

These ideas from the broader prompt-architecture discussion are valuable but belong in separate cards:

- **Externalized prompt templates** — Move all inline prompt strings to a YAML/JSON config file with placeholders (e.g., `{style}`, `{action}`). This would make prompt iteration possible without code changes, but it's a cross-cutting refactor affecting all 5 task modules.
- **PromptBuilder module** — A dedicated `prompts.py` with a builder-pattern API (`build_sequence_prompt()`, `add_repetition()`, `append_negatives()`). Useful once we have more tier/mode variants, premature for just two tiers.
- **Post-generation frame analysis** — Use OpenCV or similar to analyze extracted frames for action compliance (e.g., verify a specific motion occurred). Would strengthen validation for extended scenes beyond the current vision-LLM consistency check.
- **Configurable generation parameters** — Expose API-level knobs (guidance scale, inference steps) per tier if/when the `grok-imagine-video` API supports them. Currently not available.
- **Multi-segment stitching for extended scenes** — Generate two 8s clips instead of one 15s clip, then stitch. Enables correction on both halves but adds complexity and a visible seam risk.

## Acceptance Criteria

- [ ] Ideation prompt includes duration tier guidance
- [ ] LLM produces scenes >8s for appropriate scene types (establishing shots, etc.)
- [ ] `--max-duration` flag clamps all scenes to the specified ceiling
- [ ] Scenes >8s skip the correction loop (existing behavior, verified)
- [ ] Scenes ≤8s still enter the correction loop as before
- [ ] Extended-tier video prompts include sequenced timing, key-phrase repetition, and negative constraints
- [ ] Extended-tier scenes retry once on very low vision score (< 0.50)
- [ ] Logs clearly indicate which tier each scene falls into
- [ ] Web dashboard shows correction eligibility per scene
- [ ] Prompt changes and code-flow changes are in separate commits for reviewability
