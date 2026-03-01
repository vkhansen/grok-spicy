# BUG FIX: Hardcoded Content Leaks & Broken Data Flow

**Priority:** P0 — Critical / Data Integrity
**Affects:** `prompts.py`, `prompt_builder.py`, `client.py`, `schemas.py`, `config.py`, `pipeline.py`, `tasks/characters.py`
**Root cause:** Prompt construction functions contain hardcoded scene/motion/style content instead of reading from `video.json` config or user input concept

---

## Principle

**Every word in every generated prompt MUST come from exactly one of two sources:**

1. **User input** — the concept string passed via CLI (`python -m grok_spicy "concept"`) or `--prompt-file`
2. **`video.json`** — the config file loaded via `--config` / `--spicy`

**Zero hardcoded content in Python code.** Prompt functions are _compositors_, not _content sources_. They assemble fields from the input and config — they never invent scene descriptions, motion directives, style instructions, or aesthetic choices.

---

## Issue 1: "Smooth cinematic motion" hardcoded in `build_video_prompt()`

### Location

`src/grok_spicy/prompts.py` lines 121-126, 152-159

### Problem

```python
# Line 125 — standard tier (<=8s)
base = (
    f"{prompt_summary} "
    f"{camera}. {action}. "
    f"{mood}. {style}. "
    f"Smooth cinematic motion."          # ← HARDCODED
)

# Line 157 — extended tier (>8s)
prompt = (
    f"{style}. "
    f"Phase 1 (0-{mid}s): {phase1}. "
    f"Phase 2 ({mid}-{duration_seconds}s): {phase2}. "
    f"{camera}. {mood}. "
    f"Smooth cinematic motion throughout. "  # ← HARDCODED
    f"Maintain: {action}. "
    f"No sudden scene changes. No freeze frames. No unrelated motion."  # ← HARDCODED
)
```

### Impact

- Overrides the scene's `camera` field which already contains motion direction from ideation
- Overrides `video.json` → `scene_default.primary_motion` which has user-defined motion (e.g., `"ultra-rapid violent pendular swings..."`)
- Cannot be removed by user — `--negative-prompt` adds "Avoid:" text but can't cancel a positive instruction
- Forces every video to use slow floaty camera moves even when scene calls for fast cuts, handheld, or static framing
- The `"No sudden scene changes"` constraint is also hardcoded policy that may conflict with user intent

### Fix

Remove all hardcoded motion strings. The `camera` and `action` fields from `Scene` (populated by ideation from user input) are the sole source of motion direction. If `video_config` provides `default_video.motion`, use that as a fallback only when no scene-specific camera direction exists.

```python
# Standard tier — after fix
base = (
    f"{prompt_summary} "
    f"{camera}. {action}. "
    f"{mood}. {style}."
)

# Extended tier — after fix
prompt = (
    f"{style}. "
    f"Phase 1 (0-{mid}s): {phase1}. "
    f"Phase 2 ({mid}-{duration_seconds}s): {phase2}. "
    f"{camera}. {mood}. "
    f"Maintain: {action}."
)
```

### Tests affected

- `test_build_video_prompt_standard` (line 99): asserts `"Smooth cinematic motion" in result` — **must be removed**
- New tests needed (see Test Plan below)

---

## Issue 2: "Professional character design reference sheet style. Sharp details, even studio lighting." hardcoded in character prompts

### Location

`src/grok_spicy/prompts.py` lines 14-19 (`character_stylize_prompt`), lines 32-35 (`character_generate_prompt`)

### Problem

```python
# character_stylize_prompt — line 18-19
f"Professional character design "
f"reference sheet style. Sharp details, even studio lighting."

# character_generate_prompt — line 34-35
f"Professional character design "
f"reference sheet style. Sharp details, even studio lighting."
```

### Impact

- Forces a specific art direction ("studio lighting", "reference sheet style") on every character sheet regardless of what the user's concept or `video.json` specifies
- The user's `video.json` → `narrative_core.style_directive` already defines the desired aesthetic (e.g., `"hyperrealistic cinematic intensity, cold steel-blue palette slashed with crimson, dramatic harsh rim lighting"`) — but it's ignored here
- The `plan.style` field (the style lock) already carries the correct aesthetic from ideation — but these hardcoded strings override it
- "Even studio lighting" directly contradicts configs that specify harsh, dramatic, or rim lighting

### Fix

Remove hardcoded aesthetic strings. The `style` parameter (which is `plan.style` — the style lock) already provides the correct aesthetic. If `video_config.narrative_core.style_directive` exists, append it. The prompt function should only compose what it receives.

```python
# character_stylize_prompt — after fix
def character_stylize_prompt(
    style: str, visual_description: str, video_config: VideoConfig | None = None
) -> str:
    prompt = (
        f"{style}. Transform this photo into a full body character "
        f"portrait while preserving the person's exact facial features, "
        f"face shape, and likeness. Keep the following appearance details "
        f"accurate: {visual_description}."
    )
    # ... spicy mode injection stays the same
    return prompt

# character_generate_prompt — after fix
def character_generate_prompt(
    style: str, visual_description: str, video_config: VideoConfig | None = None
) -> str:
    prompt = (
        f"{style}. Full body character portrait of "
        f"{visual_description}."
    )
    # ... spicy mode injection stays the same
    return prompt
```

### Tests affected

- `test_character_stylize_prompt` (line 28): asserts `"Transform this photo" in result` — **still passes** (structural, not content)
- `test_character_generate_prompt` (line 35): asserts `"Full body character portrait" in result` — **still passes**
- No tests currently assert for "studio lighting" or "reference sheet" — no removals needed

---

## Issue 3: `"(extreme detail, maximum realism)"` hardcoded in `prompt_builder.py`

### Location

`src/grok_spicy/prompt_builder.py` line 108

### Problem

```python
# Line 107-108
if spicy.intensity == "extreme" and modifiers:
    parts.append("(extreme detail, maximum realism)")
```

### Impact

- Injects a hardcoded aesthetic directive into every extreme-intensity prompt
- Not configurable — user cannot change what "extreme" emphasis means
- May conflict with the user's actual style intent (e.g., stylized/cartoon aesthetic at extreme intensity)

### Fix

Add an `extreme_emphasis` field to `SpicyMode` in `video.json` schema. Read it from config instead of hardcoding.

```json
{
  "spicy_mode": {
    "extreme_emphasis": "(extreme detail, maximum realism)",
    ...
  }
}
```

```python
# After fix
if spicy.intensity == "extreme" and modifiers and spicy.extreme_emphasis:
    parts.append(spicy.extreme_emphasis)
```

### Tests affected

- No existing tests cover this. New test needed.

---

## Issue 4: Moderation reword contains hardcoded aesthetic substitutions

### Location

`src/grok_spicy/client.py` lines 141-149 (inside `reword_prompt()`)

### Problem

```python
"Replace any explicit, revealing, or "
"NSFW clothing/body descriptions with tasteful, stylish alternatives "
"(e.g. replace lingerie with elegant evening wear, replace nudity "
"with fashionable outfits)."
```

### Impact

- Hardcodes specific content substitution policy ("lingerie → elegant evening wear")
- User cannot configure what the reword fallback aesthetic should be
- The reword function imposes its own creative direction instead of using config

### Fix

This is a lower priority than Issues 1-3 because moderation rewording is a cloud-only fallback mechanism (local providers won't hit it). However, the examples should be configurable or removed entirely — the LLM can figure out appropriate substitutions from context.

Remove the hardcoded examples. Keep the structural instruction:

```python
"The following image/video generation prompt was blocked by content "
"moderation. Rephrase it to pass moderation while preserving the "
"scene composition, character names, positioning, camera angles, "
"lighting, and artistic style. "
"Return ONLY the reworded prompt text.\n\n"
```

### Tests affected

- No existing tests cover `reword_prompt()`. No changes needed.

---

## Issue 5: `video_config` not passed to `generate_character_sheet()` in pipeline

### Location

`src/grok_spicy/pipeline.py` lines 404-410

### Problem

```python
generate_character_sheet.submit(
    c,
    plan.style,
    plan.aspect_ratio,
    reference_image_path=matched_refs.get(c.name),
    config=config,
    # video_config is MISSING
)
```

### Impact

- `character_stylize_prompt()` and `character_generate_prompt()` accept `video_config` and use it to inject `global_prefix` and `enabled_modifiers` — but the pipeline never passes it
- Character sheet generation in spicy mode runs WITHOUT spicy modifiers even though the functions support it
- The `narrative_core.style_directive` from `video.json` is never available during character generation

### Fix

Pass `video_config` to `generate_character_sheet()`:

```python
generate_character_sheet.submit(
    c,
    plan.style,
    plan.aspect_ratio,
    reference_image_path=matched_refs.get(c.name),
    config=config,
    video_config=video_config,
)
```

Verify `generate_character_sheet()` in `tasks/characters.py` accepts and forwards the `video_config` parameter to the prompt functions.

### Tests affected

- Pipeline integration tests should verify `video_config` flows through. New test needed.

---

## Issue 6: `video.json` field names don't match Pydantic schema

### Location

`video.json` (root config) vs `src/grok_spicy/schemas.py` (`DefaultVideo`, `NarrativeCore`, `SpicyMode`)

### Problem

The root `video.json` uses **different field names** than the Pydantic models expect:

| `video.json` field | Pydantic model field | Status |
|---|---|---|
| `scene_default` | `default_video` | **MISMATCH** — entire section silently dropped |
| `scene_default.environment` | `default_video.scene` | **MISMATCH** — never loaded |
| `scene_default.primary_motion` | `default_video.motion` | **MISMATCH** — never loaded |
| `scene_default.audio_design` (list) | `default_video.audio_cues` (str) | **MISMATCH** — wrong type AND wrong name |
| `narrative_core.style_directive` | _(not in schema)_ | **MISSING** — field exists in JSON, no model field |
| `spicy_mode.modifiers` | `spicy_mode.enabled_modifiers` | **MISMATCH** — never loaded |
| `characters[].reference_images` | `characters[].images` | **MISMATCH** — never loaded |

### Impact

This is catastrophic. The main `video.json` config at project root has been **silently failing to load** its scene defaults, motion, audio, style directive, modifiers, and character reference images. Pydantic's `model_validate()` with default config ignores unknown fields, so:

- `scene_default.primary_motion` (`"ultra-rapid violent pendular swings..."`) → **NEVER LOADED** → `default_video.motion` stays `""` → `prompt_builder.py` gets empty string → motion comes from hardcoded `"Smooth cinematic motion"` instead
- `scene_default.environment` → **NEVER LOADED** → `default_video.scene` stays `""`
- `scene_default.audio_design` → **NEVER LOADED** → `default_video.audio_cues` stays `""`
- `narrative_core.style_directive` → **NEVER LOADED** — not even in the model
- `spicy_mode.modifiers` → **NEVER LOADED** → `spicy_mode.enabled_modifiers` stays `[]`
- `characters[].reference_images` → **NEVER LOADED** → `characters[].images` stays `[]`

The example configs in `examples/` use the correct Pydantic field names (`default_video`, `scene`, `motion`, `enabled_modifiers`, `images`) — those load fine. Only the **root `video.json`** uses different names.

### Fix

**Two options (do BOTH):**

**A) Fix `video.json` to match the schema** — rename fields to match what Pydantic expects:

```json
{
  "spicy_mode": {
    "enabled_modifiers": [...],     // was "modifiers"
    ...
  },
  "characters": [
    {
      "images": [...],              // was "reference_images"
      ...
    }
  ],
  "default_video": {                // was "scene_default"
    "scene": "...",                 // was "environment"
    "motion": "...",                // was "primary_motion"
    "audio_cues": "..."            // was "audio_design" (and was array, now string)
  },
  "narrative_core": {
    "restraint_rule": "...",
    "escalation_arc": "...",
    "style_directive": "..."        // ADD to schema
  }
}
```

**B) Add `style_directive` to `NarrativeCore` model:**

```python
class NarrativeCore(BaseModel):
    restraint_rule: str = ""
    escalation_arc: str = ""
    style_directive: str = ""       # ← ADD THIS
```

### Tests affected

- `test_video_config.py` should validate loading with both old and new field names
- New test needed: load root `video.json` and verify all fields are populated (not empty defaults)

---

## Issue 7: `narrative_core.style_directive` exists in config but never injected into prompts

### Location

`video.json` → `narrative_core.style_directive` field
`src/grok_spicy/prompts.py` — all prompt functions

### Problem

Even after fixing Issue 6 (schema mismatch), `style_directive` is read into the model but **no prompt function uses it**. The current code only injects `restraint_rule` and `escalation_arc` from `narrative_core`:

```python
# Current pattern in prompts.py (repeated 6 times)
if video_config.narrative_core:
    prompt += "\n\n**INVIOLABLE RULES:**\n"
    prompt += f"- **Restraint Rule**: {video_config.narrative_core.restraint_rule}\n"
    prompt += f"- **Escalation Arc**: {video_config.narrative_core.escalation_arc}\n"
    # style_directive is NEVER injected
```

### Impact

The user's `style_directive` (e.g., `"hyperrealistic cinematic intensity, cold steel-blue palette slashed with crimson..."`) is completely ignored. Instead, character prompts hardcode `"even studio lighting"` and video prompts hardcode `"Smooth cinematic motion"`.

### Fix

Inject `style_directive` into prompts where the style lock (`plan.style`) is used. The `style_directive` should supplement or override `plan.style` when present, as it represents the user's explicit aesthetic instruction from config.

Character prompts and video prompts should append `style_directive` when available:

```python
if video_config and video_config.narrative_core and video_config.narrative_core.style_directive:
    prompt += f" {video_config.narrative_core.style_directive}."
```

### Tests affected

- New tests needed: verify `style_directive` appears in prompt output when config provides it

---

## Issue 8: `default_video.motion` never reaches `build_video_prompt()`

### Location

`src/grok_spicy/prompt_builder.py` lines 69, 80, 100 — reads `config.default_video.motion`
`src/grok_spicy/prompts.py` `build_video_prompt()` — does NOT read it

### Problem

`prompt_builder.py` correctly reads `default_video.motion` from config, but its output is only used to augment the ideation concept (pipeline.py line 293-297). The actual `build_video_prompt()` function that generates per-scene video prompts **never receives or uses** the config motion field. It hardcodes `"Smooth cinematic motion"` instead.

### Impact

The user's configured motion style (e.g., `"slow dolly in, gentle focus pulls"` from `video-low.json`, or `"ultra-rapid violent pendular swings"` from root `video.json`) is only visible during ideation concept augmentation. By the time per-scene video prompts are built, this motion direction is lost — replaced by hardcoded text.

### Fix

This is resolved by Issue 1 (remove hardcoded motion). After removal, the scene's `camera` field (populated by ideation which DID see the motion config) becomes the sole motion source. No additional wiring needed — the ideation step already incorporates `default_video.motion` into its output, which flows into `scene.camera` and `scene.action`.

---

## Summary: All Hardcoded Content Leaks

| # | File:Line | Hardcoded Content | Should Come From | Severity |
|---|---|---|---|---|
| 1 | `prompts.py:125` | `"Smooth cinematic motion."` | `scene.camera` (from ideation/user input) | **CRITICAL** |
| 2 | `prompts.py:157` | `"Smooth cinematic motion throughout."` | `scene.camera` (from ideation/user input) | **CRITICAL** |
| 3 | `prompts.py:159` | `"No sudden scene changes. No freeze frames. No unrelated motion."` | Config or omit (let scene action speak) | **CRITICAL** |
| 4 | `prompts.py:18-19` | `"Professional character design reference sheet style. Sharp details, even studio lighting."` | `plan.style` + `narrative_core.style_directive` | **HIGH** |
| 5 | `prompts.py:34-35` | Same as #4 (duplicated) | Same as #4 | **HIGH** |
| 6 | `prompt_builder.py:108` | `"(extreme detail, maximum realism)"` | `spicy_mode.extreme_emphasis` (new field) | **HIGH** |
| 7 | `client.py:145-147` | `"replace lingerie with elegant evening wear, replace nudity with fashionable outfits"` | Remove examples; LLM doesn't need them | **MEDIUM** |

## Summary: Data Flow Breaks

| # | Location | Break | Fix |
|---|---|---|---|
| 8 | `video.json` | `scene_default` vs `default_video`, `modifiers` vs `enabled_modifiers`, `reference_images` vs `images`, `environment` vs `scene`, `primary_motion` vs `motion`, `audio_design` vs `audio_cues` | Rename JSON fields to match schema |
| 9 | `schemas.py` | `NarrativeCore` missing `style_directive` field | Add `style_directive: str = ""` |
| 10 | `pipeline.py:404-410` | `video_config` not passed to `generate_character_sheet()` | Add `video_config=video_config` param |
| 11 | `prompts.py` (all spicy blocks) | `narrative_core.style_directive` never injected | Inject where style lock is used |
| 12 | `prompts.py:build_video_prompt()` | `default_video.motion` never reaches this function | Resolved by removing hardcoded motion (#1-3) |

---

## Files to Modify

| File | Changes |
|---|---|
| `src/grok_spicy/prompts.py` | Remove 3 hardcoded motion strings, remove 2 hardcoded aesthetic strings, inject `style_directive` from config |
| `src/grok_spicy/prompt_builder.py` | Replace hardcoded `"(extreme detail, maximum realism)"` with `spicy_mode.extreme_emphasis` from config |
| `src/grok_spicy/client.py` | Remove hardcoded moderation reword examples from `reword_prompt()` |
| `src/grok_spicy/schemas.py` | Add `style_directive` to `NarrativeCore`, add `extreme_emphasis` to `SpicyMode` |
| `src/grok_spicy/pipeline.py` | Pass `video_config` to `generate_character_sheet()` |
| `src/grok_spicy/config.py` | No changes (loader already works, issue is in JSON field naming) |
| `video.json` | Rename fields to match Pydantic schema |
| `tests/test_prompts.py` | Update/add tests (see Test Plan) |

## Files NOT Modified

| File | Why |
|---|---|
| `src/grok_spicy/tasks/ideation.py` | System prompts are structural LLM instructions, not content leaks |
| `src/grok_spicy/tasks/keyframes.py` | Calls `prompts.py` functions (fixes flow through) |
| `src/grok_spicy/tasks/video.py` | Calls `prompts.py` functions (fixes flow through) |
| `src/grok_spicy/tasks/assembly.py` | No prompts (FFmpeg only) |
| `src/grok_spicy/tasks/script.py` | No prompts (pure Python) |
| `src/grok_spicy/observer.py` | No prompts |
| `src/grok_spicy/web.py` | No prompts |

---

## Test Plan

### Tests to UPDATE (existing assertions that check for hardcoded content)

#### `test_build_video_prompt_standard` — remove hardcoded motion assertion

```python
# BEFORE (tests/test_prompts.py line 99)
assert "Smooth cinematic motion" in result

# AFTER — verify only user-provided fields appear
def test_build_video_prompt_standard():
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=8,
    )
    assert "Fox leaps" in result
    assert "medium shot" in result
    assert "Fox jumps" in result
    assert "warm golden" in result
    assert "Pixar 3D" in result
    # Must NOT contain hardcoded content
    assert "Smooth cinematic motion" not in result
    assert "studio lighting" not in result
    # Standard tier: no phases
    assert "Phase 1" not in result
```

### Tests to ADD

#### 1. Verify NO hardcoded content in any prompt function

These tests enforce the principle: prompt functions are compositors, not content sources.

```python
FORBIDDEN_HARDCODED = [
    "Smooth cinematic motion",
    "even studio lighting",
    "Sharp details",
    "Professional character design reference sheet style",
    "extreme detail, maximum realism",
    "elegant evening wear",
    "fashionable outfits",
    "No sudden scene changes",
    "No freeze frames",
    "No unrelated motion",
]


def test_build_video_prompt_no_hardcoded_content():
    """Video prompts must not contain any hardcoded scene/motion/style content."""
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=8,
    )
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


def test_build_video_prompt_extended_no_hardcoded_content():
    """Extended video prompts must not contain any hardcoded content."""
    result = build_video_prompt(
        prompt_summary="Fox leaps",
        camera="medium shot",
        action="Fox jumps; Fox lands",
        mood="warm golden",
        style="Pixar 3D",
        duration_seconds=12,
    )
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


def test_character_stylize_prompt_no_hardcoded_content():
    """Character stylize prompts must not inject hardcoded aesthetics."""
    result = character_stylize_prompt("Dark cinematic", "red hair, blue eyes")
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"


def test_character_generate_prompt_no_hardcoded_content():
    """Character generate prompts must not inject hardcoded aesthetics."""
    result = character_generate_prompt("Anime cel-shaded", "tall, dark cloak")
    for forbidden in FORBIDDEN_HARDCODED:
        assert forbidden not in result, f"Hardcoded content leak: {forbidden!r}"
```

#### 2. Verify prompts are pure composites of their inputs

```python
def test_build_video_prompt_only_contains_inputs():
    """Every content word in the output must originate from an input parameter."""
    result = build_video_prompt(
        prompt_summary="ALPHA_SUMMARY",
        camera="BETA_CAMERA",
        action="GAMMA_ACTION",
        mood="DELTA_MOOD",
        style="EPSILON_STYLE",
        duration_seconds=6,
    )
    assert "ALPHA_SUMMARY" in result
    assert "BETA_CAMERA" in result
    assert "GAMMA_ACTION" in result
    assert "DELTA_MOOD" in result
    assert "EPSILON_STYLE" in result


def test_character_generate_prompt_only_contains_inputs():
    """Character prompt output must only contain the style and description passed in."""
    result = character_generate_prompt("STYLE_TOKEN", "DESCRIPTION_TOKEN")
    assert "STYLE_TOKEN" in result
    assert "DESCRIPTION_TOKEN" in result


def test_character_stylize_prompt_only_contains_inputs():
    """Character stylize prompt must only contain the style and description passed in."""
    result = character_stylize_prompt("STYLE_TOKEN", "DESCRIPTION_TOKEN")
    assert "STYLE_TOKEN" in result
    assert "DESCRIPTION_TOKEN" in result
```

#### 3. Verify `style_directive` injection when config is present

```python
from grok_spicy.schemas import NarrativeCore, SpicyMode, VideoConfig


def _make_video_config(style_directive: str = "") -> VideoConfig:
    return VideoConfig(
        spicy_mode=SpicyMode(
            enabled=True,
            enabled_modifiers=["modifier_a"],
            intensity="high",
            global_prefix="PREFIX: ",
        ),
        narrative_core=NarrativeCore(
            restraint_rule="test rule",
            escalation_arc="test arc",
            style_directive=style_directive,
        ),
    )


def test_build_video_prompt_with_style_directive():
    """style_directive from config must appear in video prompt output."""
    cfg = _make_video_config(style_directive="harsh rim lighting, cold blue palette")
    result = build_video_prompt(
        prompt_summary="summary",
        camera="tracking shot",
        action="action",
        mood="tense",
        style="cinematic",
        duration_seconds=6,
        video_config=cfg,
    )
    assert "harsh rim lighting, cold blue palette" in result


def test_character_generate_prompt_with_style_directive():
    """style_directive from config must appear in character prompt output."""
    cfg = _make_video_config(style_directive="dramatic shadows, crimson accents")
    result = character_generate_prompt("cinematic", "tall figure", video_config=cfg)
    assert "dramatic shadows, crimson accents" in result


def test_character_stylize_prompt_with_style_directive():
    """style_directive from config must appear in character stylize prompt output."""
    cfg = _make_video_config(style_directive="noir lighting")
    result = character_stylize_prompt("cinematic", "blue eyes", video_config=cfg)
    assert "noir lighting" in result
```

#### 4. Verify `extreme_emphasis` comes from config, not hardcoded

```python
from grok_spicy.prompt_builder import build_spicy_prompt
from grok_spicy.schemas import SpicyMode, VideoConfig, DefaultVideo


def test_extreme_emphasis_from_config():
    """Extreme emphasis text must come from config, not be hardcoded."""
    cfg = VideoConfig(
        spicy_mode=SpicyMode(
            enabled=True,
            enabled_modifiers=["modifier_a"],
            intensity="extreme",
            global_prefix="",
            extreme_emphasis="(CUSTOM EMPHASIS FROM CONFIG)",
        ),
        default_video=DefaultVideo(),
    )
    result = build_spicy_prompt(cfg)
    assert "(CUSTOM EMPHASIS FROM CONFIG)" in result
    assert "(extreme detail, maximum realism)" not in result


def test_extreme_no_emphasis_when_field_empty():
    """No emphasis appended when extreme_emphasis is empty."""
    cfg = VideoConfig(
        spicy_mode=SpicyMode(
            enabled=True,
            enabled_modifiers=["modifier_a"],
            intensity="extreme",
            global_prefix="",
            extreme_emphasis="",
        ),
        default_video=DefaultVideo(),
    )
    result = build_spicy_prompt(cfg)
    assert "(extreme detail, maximum realism)" not in result
```

#### 5. Verify `video.json` loads correctly after field rename

```python
import json
from pathlib import Path
from grok_spicy.config import load_video_config, clear_cache


def test_root_video_json_loads_all_fields(tmp_path):
    """Root video.json must load all fields into the correct Pydantic model fields."""
    clear_cache()
    config_path = tmp_path / "video.json"
    config_path.write_text(json.dumps({
        "version": "1.0",
        "spicy_mode": {
            "enabled": True,
            "enabled_modifiers": ["modifier_one", "modifier_two"],
            "intensity": "high",
            "global_prefix": "test prefix: ",
        },
        "characters": [
            {
                "id": "char_1",
                "name": "TestChar",
                "description": "test description",
                "images": ["path/to/img.jpg"],
                "spicy_traits": ["trait_a"],
            }
        ],
        "default_video": {
            "scene": "test environment",
            "motion": "test motion directive",
            "audio_cues": "test audio",
        },
        "narrative_core": {
            "restraint_rule": "test rule",
            "escalation_arc": "test arc",
            "style_directive": "test style directive",
        },
    }))

    cfg = load_video_config(config_path)

    # spicy_mode fields
    assert cfg.spicy_mode.enabled is True
    assert cfg.spicy_mode.enabled_modifiers == ["modifier_one", "modifier_two"]
    assert cfg.spicy_mode.intensity == "high"
    assert cfg.spicy_mode.global_prefix == "test prefix: "

    # characters
    assert len(cfg.characters) == 1
    assert cfg.characters[0].name == "TestChar"
    assert cfg.characters[0].images == ["path/to/img.jpg"]

    # default_video — these MUST NOT be empty
    assert cfg.default_video.scene == "test environment"
    assert cfg.default_video.motion == "test motion directive"
    assert cfg.default_video.audio_cues == "test audio"

    # narrative_core
    assert cfg.narrative_core is not None
    assert cfg.narrative_core.restraint_rule == "test rule"
    assert cfg.narrative_core.escalation_arc == "test arc"
    assert cfg.narrative_core.style_directive == "test style directive"
```

#### 6. Verify `video_config` flows to character sheet generation

```python
def test_pipeline_passes_video_config_to_character_sheet():
    """Pipeline must pass video_config to generate_character_sheet().

    This is a code inspection test — verify the call site in pipeline.py
    includes video_config in the arguments.
    """
    import ast
    from pathlib import Path

    source = Path("src/grok_spicy/pipeline.py").read_text()
    tree = ast.parse(source)

    # Find all calls to generate_character_sheet.submit
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "submit"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "generate_character_sheet"
            ):
                # Check keyword arguments include video_config
                kwarg_names = [kw.arg for kw in node.keywords]
                assert "video_config" in kwarg_names, (
                    "generate_character_sheet.submit() is missing video_config kwarg"
                )
```

---

## Execution Order

1. **Fix `video.json`** — rename fields to match Pydantic schema (Issue 6)
2. **Fix `schemas.py`** — add `style_directive` to `NarrativeCore`, `extreme_emphasis` to `SpicyMode` (Issues 3, 7, 9)
3. **Fix `prompts.py`** — remove all hardcoded content, inject `style_directive` (Issues 1, 2, 4)
4. **Fix `prompt_builder.py`** — read `extreme_emphasis` from config (Issue 3)
5. **Fix `client.py`** — remove hardcoded moderation examples (Issue 4)
6. **Fix `pipeline.py`** — pass `video_config` to `generate_character_sheet()` (Issue 5)
7. **Update tests** — remove hardcoded assertions, add new tests per Test Plan
8. **Verify** — `--dry-run` with root `video.json` and confirm all prompts contain only user input + config content
