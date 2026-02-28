# Feature 12: Extended Video Duration (Up to 15 Seconds)

**Priority:** P2 — Enhancement
**Depends on:** Card 08 (Video Generation)
**Blocks:** Nothing

---

## Goal

Explicitly support the full 1–15 second duration range now available for text-to-video and image-to-video generation via `grok-imagine-video`, while preserving the 8-second ceiling for scenes that need drift-correction eligibility.

## Background

The `grok-imagine-video` API now supports durations up to **15 seconds** for initial generation (text-to-video and image-to-video). However, the **video edit** endpoint still caps input at **8.7 seconds** — meaning only clips ≤ 8s can enter the drift-correction loop.

The schema (`Scene.duration_seconds`) already validates `ge=3, le=15`, but the pipeline currently treats all scenes uniformly and the ideation prompt defaults toward 8s. This card adds explicit awareness of the two duration tiers so the LLM can make informed choices and the pipeline handles each tier correctly.

## Duration Tiers

| Tier | Duration | Correction Eligible | Best For |
|---|---|---|---|
| **Standard** | 3–8s | Yes | Character-heavy scenes needing consistency checks |
| **Extended** | 9–15s | No | Establishing shots, landscapes, transitions, montages |

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

### 4. Logging & observer updates — `tasks/video.py`

Add a log line before generation that indicates the tier:

```python
tier = "standard (correction eligible)" if scene.duration_seconds <= 8 else "extended (no correction)"
logger.info("Scene %d: duration=%ds, tier=%s", scene.scene_id, scene.duration_seconds, tier)
```

The existing correction-eligibility check (`scene.duration_seconds <= 8`) already handles this correctly — no change needed to the correction logic itself.

### 5. Observer event — `observer.py`

Include the duration tier in `on_video_start` calls so the web dashboard can display whether a scene is correction-eligible.

## What Does NOT Change

- **Schema validation** — `Scene.duration_seconds` already enforces `ge=3, le=15`
- **Correction logic** — the `<= 8` gate in `video.py:119` is already correct
- **Video edit constraint** — still 8.7s max input, unchanged by API
- **Default behavior** — without `--max-duration`, the LLM is free to use the full range

## Acceptance Criteria

- [ ] Ideation prompt includes duration tier guidance
- [ ] LLM produces scenes >8s for appropriate scene types (establishing shots, etc.)
- [ ] `--max-duration` flag clamps all scenes to the specified ceiling
- [ ] Scenes >8s skip the correction loop (existing behavior, verified)
- [ ] Scenes ≤8s still enter the correction loop as before
- [ ] Logs clearly indicate which tier each scene falls into
- [ ] Web dashboard shows correction eligibility per scene
