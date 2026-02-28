# Feature 04: Story Ideation (Step 1)

**Priority:** P1 — Core Pipeline
**Depends on:** Cards 02 (Schemas), 03 (Client)
**Blocks:** Cards 05, 06, 07, 08

---

## Goal

Implement Step 1 of the pipeline: take a short concept string and produce a fully structured `StoryPlan` using Grok's structured output capability.

## Deliverables

### `src/grok_spicy/tasks/ideation.py`

**`plan_story(concept: str) -> StoryPlan`**

1. Create chat with `grok-4-1-fast-non-reasoning`
2. System prompt establishes the "visual storytelling director" role:
   - Every character needs exhaustive visual description (80+ words)
   - This description is the sole appearance reference for all downstream image generation
   - Design scenes for 8-second video clips with simple, clear actions
   - Limit: 2–3 characters, 3–5 scenes
3. User message: the concept string
4. Call `chat.parse(StoryPlan)` to get structured output
5. Return the parsed `StoryPlan`

**Prefect decoration:**
- `@task(name="plan-story", retries=2, retry_delay_seconds=10)`
- Cache with `task_input_hash`, 1-hour expiration

### Key design decisions

- The `visual_description` field on each `Character` is the **most critical output**. It becomes the frozen identity string used verbatim in every image prompt. The system prompt must emphasize precision: exact colors, materials, distinguishing features.
- The `style` field on `StoryPlan` must be specific (e.g., "Pixar-style 3D animation with soft volumetric lighting"), not vague ("animated"). This prefix starts every downstream prompt.
- `Scene.action` should describe a single, simple motion suitable for an 8-second clip.

### Standalone test

Should be runnable independently:
```python
plan = plan_story("A fox and owl discover a glowing crystal in an autumn forest")
print(plan.model_dump_json(indent=2))
```

## Acceptance Criteria

- [ ] Returns a valid `StoryPlan` with all required fields populated
- [ ] Each character's `visual_description` is 80+ words
- [ ] `plan.style` is specific enough to maintain visual consistency
- [ ] Scenes have reasonable durations (default 8s) and clear actions
- [ ] Prefect task decorators applied with retries and caching
- [ ] Works as a standalone call (no dependency on other pipeline steps)
