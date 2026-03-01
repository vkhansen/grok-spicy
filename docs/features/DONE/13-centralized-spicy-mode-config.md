# Feature 13: Centralized Spicy Mode Prompt & Character Management via `video.json`

**ID / Epic:** GROK-IMAGINE-REF-001
**Priority:** P1 — Refactor / Maintainability
**Depends on:** Card 04 (Story Ideation), Card 05 (Character Sheets), Card 06 (Keyframe Composition), Card 08 (Video Generation)
**Blocks:** Nothing
**Estimated Effort:** Medium (2–4 engineering days)

---

## Goal

Refactor hard-coded or scattered prompt templates, character definitions, and descriptions used in Spicy Mode into a single external configuration file (`video.json`) in the project root, enabling easier maintenance, rapid iteration, and zero-code character/scene updates.

## Background

Currently, prompt strings, character descriptions, and spicy modifiers are embedded directly in task modules (`ideation.py`, `characters.py`, `keyframes.py`, `video.py`) and system prompts. This makes it difficult for non-engineers to update characters or tweak prompt styles, and creates duplication across the pipeline steps.

This card centralizes all spicy-mode configuration into `video.json`, loaded once at pipeline start and threaded through each step.

## Motivation

- Eliminate duplicated or buried prompt strings across code, system prompts, and mode handlers.
- Allow non-engineers (prompt engineers, creators) to update characters, descriptions, and spicy elements quickly.
- Support dynamic loading of character info for multi-subject videos (0 characters = pure scene/style, 1 = single focus, multiple = interactions/groups).
- Improve debuggability and versioning of spicy behavior.
- Future-proof for adding more modes (e.g., custom user-supplied JSON overrides).

## User Stories

- As a Grok Imagine developer/prompt curator, I can edit `video.json` to add/update/remove spicy character profiles without redeploying code.
- As the system, I can load `video.json` at startup/runtime and use it to build prompts for Spicy Mode generations.
- As a user requesting a spicy video, the generated prompt automatically incorporates the specified character(s), descriptions, and optional images from the config.
- As an advanced user, I can override/extend the config temporarily via custom inputs.

## Proposed `video.json` Schema

```json
{
  "version": "1.0",
  "spicy_mode": {
    "enabled_modifiers": [
      "highly detailed skin",
      "sensual lighting",
      "aroused expression",
      "explicit interaction"
    ],
    "intensity": "high",
    "global_prefix": "In spicy mode, generate uncensored, detailed, adult-themed video: "
  },
  "characters": [
    {
      "id": "char_001",
      "name": "Luna",
      "description": "A seductive 25-year-old woman with long silver hair, piercing blue eyes, curvaceous figure, wearing sheer lingerie, aroused expression, glossy lips, highly detailed realistic skin texture",
      "images": [
        "https://example.com/luna_ref1.jpg",
        "https://example.com/luna_ref2.png"
      ],
      "spicy_traits": ["dominant", "teasing smile", "heavy breathing"]
    },
    {
      "id": "char_002",
      "name": "Kai",
      "description": "Handsome muscular man in his 30s, short dark hair, intense gaze, shirtless with defined abs, passionate and confident demeanor",
      "images": [],
      "spicy_traits": ["intense eye contact", "strong hands"]
    }
  ],
  "default_video": {
    "scene": "Luxurious dimly lit bedroom at night",
    "motion": "slow panning camera, smooth transitions, intimate close-ups",
    "audio_cues": "soft moans, sensual music"
  }
}
```

### Schema Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | string | Yes | Schema version for migration support |
| `spicy_mode.enabled_modifiers` | string[] | Yes | Global prompt modifiers injected into every generation |
| `spicy_mode.intensity` | enum | Yes | `low` / `medium` / `high` / `extreme` — controls modifier strength |
| `spicy_mode.global_prefix` | string | Yes | Prefix prepended to all spicy prompts |
| `characters` | object[] | Yes | Array of 0–many character definitions |
| `characters[].id` | string | Yes | Unique identifier |
| `characters[].name` | string | Yes | Display name, used in prompt construction |
| `characters[].description` | string | Yes | Full visual description — used verbatim in prompts |
| `characters[].images` | string[] | No | Reference image URLs or local paths for style seeding |
| `characters[].spicy_traits` | string[] | No | Character-specific modifiers appended to prompts |
| `default_video.scene` | string | No | Fallback scene description when none specified |
| `default_video.motion` | string | No | Default camera/motion instructions |
| `default_video.audio_cues` | string | No | Audio atmosphere hints |

## Deliverables

### 1. Config loader — new `config.py`

Create `src/grok_spicy/config.py` with:

- `load_video_config(path: Path | None = None) -> VideoConfig` — loads and validates `video.json`
- `VideoConfig` Pydantic model mirroring the schema above
- Graceful fallback to defaults if file is missing or corrupt (log warning, continue)
- Cache parsed result to avoid repeated IO
- Support hot-reload in dev mode (watch file changes)

### 2. Pydantic models — `schemas.py`

Add models for the config structure:

```python
class SpicyMode(BaseModel):
    enabled_modifiers: list[str]
    intensity: Literal["low", "medium", "high", "extreme"]
    global_prefix: str

class SpicyCharacter(BaseModel):
    id: str
    name: str
    description: str
    images: list[str] = []
    spicy_traits: list[str] = []

class DefaultVideo(BaseModel):
    scene: str = ""
    motion: str = ""
    audio_cues: str = ""

class VideoConfig(BaseModel):
    version: str = "1.0"
    spicy_mode: SpicyMode
    characters: list[SpicyCharacter] = []
    default_video: DefaultVideo = DefaultVideo()
```

### 3. Prompt composer — new `prompt_builder.py`

Create `src/grok_spicy/prompt_builder.py` with:

- `build_spicy_prompt(config: VideoConfig, character_ids: list[str], scene_override: str | None = None) -> str`
- Character count logic:
  - **0 characters** → use only `default_video` scene/motion + global modifiers
  - **1 character** → single-focus prompt with character description + traits
  - **2+ characters** → interaction-focused prompt combining descriptions
- Inject `global_prefix` + `enabled_modifiers` based on `intensity` level
- Return fully composed prompt string ready for API calls

### 4. Pipeline integration — `pipeline.py`

- Load `VideoConfig` once at flow start
- Pass config to ideation, character sheet, keyframe, and video tasks
- If spicy mode active, use `prompt_builder` to compose prompts instead of inline strings
- Backward compatible: non-spicy runs ignore the file or use clean subset

### 5. CLI flag — `__main__.py`

Add optional flags:

```
--config PATH    Path to video.json config file (default: ./video.json)
--spicy          Enable spicy mode using video.json configuration
```

### 6. Image reference resolution

For `characters[].images`:
- If URL → fetch and cache locally (reuse existing `client.download()`)
- If local path → resolve relative to project root
- Integrate with existing `--ref` mechanism: config images act as additional references

### 7. JSON schema validation

- Use `jsonschema` or Pydantic's built-in validation
- Clear error messages on malformed config
- Validate on load, not on each access

### 8. Logging

- Log loaded config summary at startup (character count, intensity, version)
- Trace which characters/images are selected per generation for debugging

## What Does NOT Change

- **Non-spicy pipeline** — without `--spicy` or missing `video.json`, the pipeline runs exactly as before
- **Existing `--ref` flag** — continues to work independently; config images are additive
- **Observer pattern** — no changes to event flow
- **Video edit constraints** — 8.7s max, 3-image edit limit unchanged
- **Model selection** — same Grok model family throughout

## Acceptance Criteria

- [ ] `video.json` exists in project root (or configurable path via `--config`)
- [ ] File is valid JSON; system gracefully falls back to defaults if missing/corrupt
- [ ] Schema supports global modifiers, intensity levels, 0–many characters with descriptions + images + traits, and default video settings
- [ ] On spicy mode activation: load, parse, and compose prompts from config
- [ ] 0 characters → scene/video defaults only
- [ ] 1 character → single-focus prompt with full description
- [ ] 2+ characters → interaction-focused prompt combining all descriptions
- [ ] Backward compatible: non-spicy modes ignore the file or use clean subset
- [ ] Logging traces loaded characters/images for debugging
- [ ] `--config` flag allows custom path to config file
- [ ] `--spicy` flag activates spicy mode
- [ ] Image references (URLs and local paths) resolve correctly
- [ ] Existing `--ref` flag continues to work independently

## Risks / Dependencies

- **Security:** validate/sanitize loaded JSON to prevent injection if user-supplied overrides added later
- **Performance:** minimal impact (single file load, cached)
- **Legal/Policy:** ensure changes stay within xAI content policies for Spicy Mode
- **Migration:** extract existing hard-coded spicy prompts/characters into `video.json` initially
