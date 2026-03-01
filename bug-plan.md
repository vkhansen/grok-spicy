# Bug Plan — Trace, Verify & Fix

Status: **verified via code-level analysis**
Priority ordering: HIGH first, then MEDIUM.

---

## Bug #2 — Ideation dry-run ignores `video_config` [HIGH]

### Trace

- **Root**: `src/grok_spicy/tasks/ideation.py:102-147` — `_mock_story_plan(concept, ref_descriptions)` accepts no `video_config` parameter.
- **Caller**: `ideation.py:188-200` — dry-run branch calls `_mock_story_plan(concept, ref_descriptions)`, discarding the `video_config` that is already available as a parameter in `plan_story()` (line 158).
- **Downstream impact**: All dry-run steps (2-6) receive a mock plan with hardcoded `["Alice", "Bob"]` characters, zero `spicy_traits`, no `narrative_core` constraints, and a generic 3-scene structure — regardless of `video.json` contents.

### What's wrong

| Field | Currently | Should be |
|---|---|---|
| Characters | Hardcoded `["Alice", "Bob"]` (or ref keys) | `video_config.characters[]` names + descriptions |
| `spicy_traits` | Empty list `[]` | `video_config.characters[].spicy_traits` per character |
| Scene count | Fixed 3 | Informed by `narrative_core.escalation_arc` length |
| Scene descriptions | Generic placeholder text | Reflect `escalation_arc` stages |
| Style | `"[DRY-RUN] Cinematic realism..."` | Could incorporate `global_prefix` |

### Fix plan

1. Add `video_config: VideoConfig | None = None` parameter to `_mock_story_plan()`.
2. When `video_config` is provided and `spicy_mode.enabled`:
   - Use `video_config.characters` for names/descriptions instead of `["Alice", "Bob"]`.
   - Populate `spicy_traits` on each mock character from the matching `SpicyCharacter`.
   - If `narrative_core.escalation_arc` exists, use its entries as scene descriptions.
   - Prepend `global_prefix` to the mock style string.
3. Update the call site at line ~193 to pass `video_config`.
4. Add a test: `--dry-run --spicy` with a config containing 3 named characters → verify mock plan uses those names and traits.

---

## Bug #3 — Spicy traits duplication in prompts [HIGH]

### Trace

**Path A — generation prompts** (`prompts.py:10-59`):
- `character_stylize_prompt()` line 22-23: `desc = f"{desc}, {', '.join(spicy_traits)}"` — traits appended to description string.
- `character_generate_prompt()` line 48-50: same pattern.
- Then lines 35-36 / 57-58: `video_config.spicy_mode.enabled_modifiers` appended to the prompt again.
- `enabled_modifiers` may overlap with per-character `spicy_traits` depending on config.

**Path B — vision check prompts** (`prompts.py:62-87`):
- `character_vision_stylize_prompt()` line 69: uses `character.visual_description` (clean, no traits).
- Line 71-73: then separately appends `character.spicy_traits` as bullet points.
- `character_vision_generate_prompt()` lines 82-86: same pattern.

**The actual duplication**: The generation prompts (Path A) embed traits into the description text AND append `enabled_modifiers`. The vision prompts (Path B) use clean `visual_description` + separate traits — this path is correct. The overlap is between per-character `spicy_traits` and `enabled_modifiers` in Path A, where both can contain the same content (e.g., config has modifiers that are also character traits).

**Secondary concern**: The comment at `pipeline.py:395-399` claims traits are NOT baked into `visual_description` — this is true for the stored field, but the prompt builders create a local `desc` variable that IS mutated. This is by design but fragile — any future code reusing `desc` downstream would carry the pollution.

### Fix plan

1. In `character_stylize_prompt()` and `character_generate_prompt()`: deduplicate `spicy_traits` against `enabled_modifiers` before appending. Only add traits that aren't already in the modifiers list.
2. Alternatively (cleaner): remove trait injection from the `desc` variable entirely and add a dedicated `Spicy details: ...` section to the prompt, keeping description and traits visually separated.
3. Add a test: config with overlapping traits and modifiers → assert the final prompt string contains each trait exactly once.

---

## Bug #4 — `prompt_builder.py` is dead code [HIGH]

### Trace

- **File**: `src/grok_spicy/prompt_builder.py` (119 lines) — exports `build_spicy_prompt()`.
- **Runtime usage**: zero. Not imported in any file under `src/grok_spicy/`.
  - Not in `pipeline.py`, `__main__.py`, `prompts.py`, or any task module.
- **Test usage only**: imported in `tests/test_prompts.py` (lines 3, 435, 452) and `tests/test_video_config.py` (line 10 + 12 calls).
- **Doc references**: `CLAUDE.md` line 85/149, `README.md` line 770 — stale architecture descriptions.

### Why it's dead

The pipeline was refactored to inject spicy content directly through `prompts.py` functions (`character_stylize_prompt`, `character_generate_prompt`, `keyframe_compose_prompt`, etc.) via their `video_config` and `spicy_traits` parameters. The centralized `build_spicy_prompt()` approach was abandoned but never cleaned up.

### Fix plan

1. Delete `src/grok_spicy/prompt_builder.py`.
2. Remove imports and test functions referencing it from `tests/test_prompts.py` and `tests/test_video_config.py`.
3. Update `CLAUDE.md` and `README.md` to remove `prompt_builder.py` references.
4. Run `pytest` to confirm no breakage.

---

## Bug #5 — `PipelineState` missing resumability data [HIGH]

### Trace

- **Model**: `schemas.py:220-226` — `PipelineState` has only: `plan`, `characters`, `keyframes`, `videos`, `final_video_path`.
- **State save**: `tasks/script.py:30-36` — writes `PipelineState` to `state.json`.
- **State load**: `__main__.py:260-279` — `--script` loads file as `StoryPlan` (not even `PipelineState`!), passes it as `script_plan`.
- **Pipeline resume path**: `pipeline.py:253-258` — when `script_plan` is set, skips ideation but hardcodes `matched_refs = {}` (line 258).

### What's missing

| Field | Impact when missing |
|---|---|
| `run_id` | Can't relocate assets or identify the run |
| `config` (PipelineConfig) | Loses `max_duration`, `consistency_threshold`, retry counts — downstream steps use defaults |
| `video_config` (VideoConfig) | Spicy mode disabled on resume — no modifiers, no traits |
| `character_refs` | Characters with reference photos regenerated from scratch |
| `ref_descriptions` | Vision-extracted descriptions lost |
| `matched_refs` | Hardcoded `{}` — stylize mode never triggered |

### Fix plan

1. Add optional fields to `PipelineState`: `run_id`, `config`, `video_config`, `character_refs`, `ref_descriptions`, `matched_refs`.
2. Populate them in `compile_script` (or in `pipeline.py` before the save call).
3. Update `__main__.py` `--script` path to load `PipelineState` (with fallback to raw `StoryPlan` for backward compat).
4. Pass restored fields into `video_pipeline()` so downstream steps have full context.
5. Add a test: save state → load via `--script` → verify config and refs survive round-trip.

---

## Bug #6 — DB stores corrupted `visual_description` [MEDIUM]

### Trace

- **Mutation point**: `ideation.py:213-218` — `char.spicy_traits = spicy_char.spicy_traits` mutates the `Character` object in-place after ideation.
- **DB write**: `observer.py:135` — `insert_characters()` called with the mutated character list.
- **Character asset DB write**: `observer.py:156` → `db.py:284` — stores `asset.visual_description` which comes from `character.visual_description` (`characters.py:264`).

### Current status

The design is **currently sound** — `visual_description` itself is not mutated, only `spicy_traits` is set. The `character_stylize_prompt()` creates a local `desc` copy. **However**, the architecture is fragile: any future code that appends traits to `visual_description` directly (instead of using the prompt builder pattern) would silently corrupt the DB.

### Fix plan

1. Defensive: freeze `visual_description` after ideation by storing it as a separate immutable field, or deep-copy the plan before mutation.
2. Alternatively: move the spicy_traits merge OUT of `plan_story()` and into the pipeline, operating on a copy — keeping the returned `StoryPlan` pristine.
3. Add an assertion in `on_character()` observer: `assert "spicy" not in asset.visual_description.lower()` (or similar canary) during development.

---

## Bug #7 — LLM character name matching fragility [MEDIUM]

### Trace

- **Location**: `pipeline.py:48-136` — `_match_character_refs()`.
- **Phase 1** (lines 64-84): exact case-insensitive match — safe.
- **Phase 2** (lines 89-136): LLM fallback using `chat.parse(CharacterRefMapping)`.

### Failure modes

1. **Silent swallow**: line 132-133 catches ALL exceptions with `logger.warning()` — unmatched refs silently dropped.
2. **No retry**: unlike vision checks and ideation, the LLM call has no retry logic.
3. **Minimal context**: the prompt sends only `{name, role}` — LLM has no visual/description context to match against labels like `"Alex"` → `"Alexander the Great"`.
4. **Validation gap**: lines 126-131 silently drop invalid mappings (nonexistent labels or names).

### Fix plan

1. Enrich the LLM prompt with character `visual_description` snippets for better matching context.
2. Add 1 retry on failure (match the pattern used elsewhere in the pipeline).
3. Log a clear WARNING when refs go unmatched after both phases (not just debug-level).
4. Consider a simpler fuzzy-match heuristic (substring, Levenshtein) before the LLM fallback to reduce LLM dependency.

---

## Bug #8 — Spicy config image URL collision risk [MEDIUM]

### Trace

- **Download location**: `pipeline.py:198-216` — downloads config character images to `output/staging/references/{safe_name}_config.jpg`.
- **Shared path**: the staging directory is global — no run-id namespace.
- **Copy to run dir**: lines 234-250 copy from staging to `{config.run_dir}/references/`, but this happens AFTER the download.

### Race condition

```
Run A: downloads → output/staging/references/Alice_config.jpg (write begins)
Run B: downloads → output/staging/references/Alice_config.jpg (overwrites mid-write)
Run A: copies corrupted file → run_A/references/Alice_config.jpg
```

No file locking, no atomic write, no run-scoped staging.

### Fix plan

1. Namespace staging downloads by run: `output/staging/{run_id}/references/{safe}_config.jpg`.
2. Alternatively: download directly into `{config.run_dir}/references/` (skip staging entirely — the run dir is already created by this point or can be created earlier).
3. Use atomic write pattern: download to a temp file, then `os.replace()` to final path.
4. Add cleanup: remove staging files after successful copy to run dir.

---

## Execution order

| Phase | Bugs | Rationale |
|---|---|---|
| 1 | #4 (dead code) | Zero risk, removes noise, simplifies codebase |
| 2 | #3 (trait duplication) | Fixes prompt quality, prerequisite for #6 |
| 3 | #6 (DB corruption risk) | Defensive hardening after #3 is resolved |
| 4 | #2 (dry-run mock) | Unblocks spicy dry-run testing |
| 5 | #5 (resumability) | Schema change — do after other schema-adjacent fixes |
| 6 | #7, #8 (matching + collision) | Lower risk, can be done independently |

---

## Test strategy

- Each fix gets a targeted unit test in `tests/`.
- After all fixes: full `--dry-run --spicy` integration test to validate the pipeline end-to-end.
- Run `pytest`, `ruff`, `black`, `isort`, `mypy` after each phase.
