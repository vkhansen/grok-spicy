# Feature 14: Remove Hardcoded "Smooth Cinematic Motion" Suffix

**Priority:** P2 -- Quality / Prompt Control
**Depends on:** Card 12 (Extended Video Duration), prompts.py extraction
**Blocks:** Nothing
**Estimated Effort:** Small (< 1 engineering day)

---

## Problem

`build_video_prompt()` unconditionally appends a hardcoded motion directive to every video generation prompt:

- **Standard tier (<=8s):** `"... Smooth cinematic motion."`
- **Extended tier (>8s):** `"... Smooth cinematic motion throughout. ..."`

This is problematic for several reasons:

1. **Overrides the LLM's scene design.** The ideation step already generates per-scene `camera` and `action` fields specifically to describe motion. Appending a blanket "smooth cinematic motion" competes with those fields and biases the video model toward slow, floaty camera moves even when the scene calls for quick cuts, handheld shake, or static framing.

2. **One size doesn't fit all.** A chase scene wants aggressive tracking. A dialogue close-up wants near-stillness. A landscape establishing shot wants a slow pan. Hardcoding a single motion philosophy into every prompt flattens the variety that the ideation step was designed to create.

3. **Not user-overridable.** Even with `--negative-prompt` and `--style-override`, users cannot remove this suffix -- it's baked in after all other prompt construction. The `append_negative_prompt()` utility adds "Avoid: ..." text, but it can't cancel a positive instruction the model has already seen.

4. **Redundant with scene.camera.** The `camera` field in `Scene` already contains motion instructions like "slow dolly forward", "tracking shot", "static close-up". The suffix duplicates or contradicts this.

### Where it lives

`src/grok_spicy/prompts.py`, function `build_video_prompt()`:

```python
# Standard tier
base = (
    f"{prompt_summary} "
    f"{camera}. {action}. "
    f"{mood}. {style}. "
    f"Smooth cinematic motion."     # <-- hardcoded
)

# Extended tier
return (
    f"{style}. "
    f"Phase 1 (0-{mid}s): {phase1}. "
    f"Phase 2 ({mid}-{duration_seconds}s): {phase2}. "
    f"{camera}. {mood}. "
    f"Smooth cinematic motion throughout. "  # <-- hardcoded
    ...
)
```

## Proposed Fix

### Option A: Remove entirely (recommended)

Delete the "Smooth cinematic motion" / "Smooth cinematic motion throughout" fragments from both tiers. The `camera` and `action` fields already carry motion intent. If a user wants smooth motion, they can add it via `--style-override` or let the ideation LLM include it in the camera field naturally.

```python
# Standard tier -- after removal
base = (
    f"{prompt_summary} "
    f"{camera}. {action}. "
    f"{mood}. {style}."
)

# Extended tier -- after removal
return (
    f"{style}. "
    f"Phase 1 (0-{mid}s): {phase1}. "
    f"Phase 2 ({mid}-{duration_seconds}s): {phase2}. "
    f"{camera}. {mood}. "
    f"Maintain: {action}. "
    f"No sudden scene changes. No freeze frames. No unrelated motion."
)
```

### Option B: Make it configurable via PipelineConfig

Add a `motion_suffix: str | None` field to `PipelineConfig` (default `None` = no suffix). If set, append it to video prompts. This gives users explicit control without hardcoding a default bias.

## What Changes

| File | Change |
|---|---|
| `src/grok_spicy/prompts.py` | Remove hardcoded suffix from `build_video_prompt()` |
| `tests/test_prompts.py` | Update assertions that check for "Smooth cinematic motion" |

## What Does NOT Change

- Ideation system prompt (already instructs LLM to specify camera/motion per scene)
- Character sheet prompts (never had this suffix)
- Keyframe composition prompts (never had this suffix)
- `--negative-prompt` / `--style-override` mechanics
- Extended tier negative constraints ("No sudden scene changes" etc.) -- these stay

## Acceptance Criteria

- [ ] `build_video_prompt()` output does not contain "Smooth cinematic motion" by default
- [ ] Scene `camera` field is the sole source of motion direction in video prompts
- [ ] Existing tests updated and passing
- [ ] A/B comparison: generate the same concept with and without the suffix to confirm quality is maintained or improved
