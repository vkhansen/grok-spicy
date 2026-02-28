# Feature 10: Prefect Orchestration & Pipeline Flow

**Priority:** P1 — Integration
**Depends on:** Cards 04–09 (All task implementations)
**Blocks:** Card 11 (CLI entry point)

---

## Goal

Wire all six pipeline steps into a single Prefect flow in `src/grok_spicy/pipeline.py`. Handle parallel execution, sequential chaining, state persistence, and resumability.

## Deliverables

### `src/grok_spicy/pipeline.py`

**`video_pipeline(concept: str) -> str`** — decorated with `@flow`

### Flow structure:

```python
@flow(name="grok-video-pipeline", retries=1,
      retry_delay_seconds=60, log_prints=True)
def video_pipeline(concept: str) -> str:
    # STEP 1: Ideation (single call)
    plan = plan_story(concept)

    # STEP 2: Character sheets (PARALLEL via .submit)
    char_futures = [
        generate_character_sheet.submit(c, plan.style, plan.aspect_ratio)
        for c in plan.characters
    ]
    characters = [f.result() for f in char_futures]
    char_map = {c.name: c for c in characters}

    # STEP 3: Keyframes (SEQUENTIAL for frame chaining)
    keyframes = []
    prev_url = None
    for scene in plan.scenes:
        kf = compose_keyframe(scene, plan, char_map, prev_url)
        keyframes.append(kf)
        prev_url = kf.keyframe_url

    # STEP 4: Compile script (no API calls)
    script = compile_script(plan, characters, keyframes)

    # Save intermediate state
    state = PipelineState(plan=plan, characters=characters, keyframes=keyframes)
    save_state(state)

    # STEP 5: Video generation (SEQUENTIAL)
    videos = []
    for scene, kf in zip(plan.scenes, keyframes):
        v = generate_scene_video(kf, scene, char_map)
        videos.append(v)

    # STEP 6: Assembly
    final = assemble_final_video(videos)

    # Save final state
    state.videos = videos
    state.final_video_path = final
    save_state(state)

    return final
```

### State persistence

**`save_state(state: PipelineState) -> None`:**
- Write to `output/state.json` via `model_dump_json(indent=2)`
- Called after Steps 4 and 6

### Print logging

Use `print()` statements (captured by Prefect's `log_prints=True`) at each step boundary:
- Step entry: `"═══ STEP N: {name} ═══"`
- Per-asset: character scores, keyframe scores, video scores
- Final: path to assembled video

### Parallelism decisions

| Step | Execution | Why |
|---|---|---|
| Step 2 | Parallel (`.submit()`) | Characters are independent |
| Step 3 | Sequential | Frame chaining — scene N feeds scene N+1 |
| Step 5 | Sequential | MVP simplicity; future: parallel for non-chained scenes |

### Prefect flow config

- `retries=1` — retry the entire flow once on catastrophic failure
- `retry_delay_seconds=60` — wait a minute before flow-level retry
- `log_prints=True` — capture print statements as Prefect logs

## Acceptance Criteria

- [ ] All 6 steps wired in correct order
- [ ] Character sheets generated in parallel via `.submit()`
- [ ] Keyframes and videos processed sequentially
- [ ] State saved after Step 4 and after Step 6
- [ ] Progress printed at each step boundary
- [ ] Flow-level retry configured
- [ ] Returns path to final video
