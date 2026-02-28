# Feature 05: Character Sheet Generation (Step 2)

**Priority:** P1 — Core Pipeline
**Depends on:** Cards 02 (Schemas), 03 (Client), 04 (Ideation provides input)
**Blocks:** Card 06 (Keyframes need character sheets as references)

---

## Goal

Implement Step 2: generate a verified character reference portrait for each character. Each portrait goes through a generate → vision-verify → retry loop to ensure it faithfully matches the character's frozen `visual_description`.

## Deliverables

### `src/grok_spicy/tasks/characters.py`

**`generate_character_sheet(character: Character, style: str, aspect_ratio: str) -> CharacterAsset`**

**Loop (max 3 attempts):**

1. **Generate portrait** via `client.image.sample()`:
   - Prompt template: `"{STYLE}. Full body character portrait of {VISUAL_DESCRIPTION}. Standing in a neutral three-quarter pose against a plain light gray background. Professional character design reference sheet style. Sharp details, even studio lighting, no background clutter, no text or labels."`
   - Model: `grok-imagine-image`
   - Three-quarter pose shows more of the character than front-on
   - Gray background isolates cleanly for downstream multi-image edit

2. **Download immediately** — URLs are temporary

3. **Vision verify** via `grok-4-1-fast-reasoning`:
   - Send the generated portrait + the text description
   - Prompt: score how well the portrait matches — be strict on hair color/style, eye color, clothing colors/style, build, distinguishing features
   - Parse response as `ConsistencyScore`

4. **Track best** — keep the highest-scoring attempt across all iterations

5. **Accept if score ≥ 0.80** (CONSISTENCY_THRESHOLD), otherwise retry

**Return:** `CharacterAsset` with best portrait's URL, path, score, and attempt count

**Prefect decoration:**
- `@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)`
- Characters are **parallelizable** — the main flow uses `.submit()` for concurrent execution

### File output

```
output/character_sheets/{name}_v1.jpg
output/character_sheets/{name}_v2.jpg  # if retry needed
output/character_sheets/{name}_v3.jpg  # if second retry
```

All attempts are kept (not just the best) for debugging.

## Acceptance Criteria

- [ ] Generates portrait with correct prompt template (style lock + full description)
- [ ] Vision verification scores the portrait against the character description
- [ ] Retries up to 3 times if score < 0.80
- [ ] Downloads every generated image immediately
- [ ] Returns `CharacterAsset` with best result
- [ ] Can run in parallel for multiple characters (no shared mutable state)
- [ ] All attempts saved to disk with versioned filenames
