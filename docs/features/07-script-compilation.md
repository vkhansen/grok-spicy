# Feature 07: Script Compilation (Step 4)

**Priority:** P1 — Core Pipeline
**Depends on:** Cards 02 (Schemas), 05 (Character assets), 06 (Keyframe assets)
**Blocks:** Card 10 (Pipeline orchestration uses script output)

---

## Goal

Implement Step 4: compile all generated assets into a human-readable markdown storyboard (`script.md`) and a machine-readable pipeline state file (`state.json`). No API calls — pure Python.

## Deliverables

### `src/grok_spicy/tasks/script.py`

**`compile_script(plan: StoryPlan, characters: list[CharacterAsset], keyframes: list[KeyframeAsset]) -> str`**

### `script.md` format

```markdown
# {Title}

**Style:** {style}
**Aspect Ratio:** {aspect_ratio}
**Color Palette:** {color_palette}

---

## Characters

### {Name}
**Score:** {score} | **Attempts:** {attempts}
> {visual_description}
![{Name}]({portrait_path})

---

## Scenes

### Scene {id}: {title}

| Property | Value |
|---|---|
| Setting | ... |
| Characters | ... |
| Camera | ... |
| Duration | ...s |
| Transition | ... |
| Consistency | {score} (edits: {n}) |

![Scene {id}]({keyframe_path})

**Video Prompt:**
> {video_prompt}
```

### `state.json`

Serialize `PipelineState` via `model_dump_json(indent=2)`. This enables:
- **Resumability** — if the pipeline crashes at Step 5, reload state and skip Steps 1–4
- **Debugging** — inspect all scores, attempts, and prompts used
- **Audit trail** — full generation history

### File output

```
output/script.md
output/state.json
```

**Prefect decoration:**
- `@task(name="compile-script")`
- No retries needed (pure Python, no API calls)

## Acceptance Criteria

- [ ] Generates readable markdown with embedded image paths
- [ ] Scenes sorted by scene_id
- [ ] state.json round-trips through `PipelineState.model_validate_json()`
- [ ] Creates `output/` directory if it doesn't exist
- [ ] Returns the script file path
