# Feature 16: Character Clothes & Enhancement Sheets

## Summary

Redesign character sheet generation to support three distinct modes based on what `video.json` provides per character. When both reference images and a `description` are supplied, the description is treated as **enhancements** (clothes, accessories, skin marks, etc.) applied on top of the base likeness extracted from the photo — producing two character sheets: a "base" sheet and an "enhanced" sheet.

## Problem

Currently character sheets are generated in one pass with a single mode decision:

- **Stylize mode** (reference image exists): transforms the photo into the art style, appending the full `visual_description` + `spicy_traits` into the stylize prompt.
- **Generate mode** (no reference image): generates from the text `visual_description` alone.

This conflates two concerns: the character's **identity** (face, body, hair — from the photo) and their **outfit/modifications** (clothes, tattoos, skin marks — from the config description). The LLM tries to do both at once, often losing likeness fidelity when the description asks for dramatic wardrobe or body changes.

## Current Architecture (post-refactoring)

The pipeline is driven entirely by `video.json` — no LLM ideation step:

- `video.json` contains `story_plan` (with `characters[]` and `scenes[]`) plus `characters[]` at the top level (spicy config characters with `images`, `description`, `spicy_traits`)
- `story_plan.characters[].visual_description` = verbatim text used in all prompts
- Top-level `characters[].description` = config-level character description
- Top-level `characters[].images` = reference photos (resolved to local paths)
- At pipeline start: `spicy_traits` are merged from top-level `characters[]` into `story_plan.characters[]` by name match
- Reference images from top-level `characters[].images` are resolved and added to `character_refs` dict
- `generate_character_sheet()` receives a `Character` (from plan) + optional `reference_image_path`

**Key files:**
- `schemas.py`: `Character`, `CharacterAsset`, `SpicyCharacter`, `VideoConfig` (with `story_plan: StoryPlan | None`)
- `pipeline.py`: `video_pipeline(video_config, ...)` — reads plan from `video_config.story_plan`, no ideation
- `tasks/characters.py`: `generate_character_sheet()` — stylize or generate mode
- `prompts.py`: `character_stylize_prompt()`, `character_generate_prompt()`, vision prompts
- `config.py`: `load_video_config()`, `resolve_character_images()`

## Design: Three Cases

The case is determined per character by checking the matching top-level `SpicyCharacter` entry:

| Case | `SpicyCharacter.images` | `SpicyCharacter.description` | Result |
|------|------------------------|------------------------------|--------|
| 1 | empty | non-empty | Generate from `visual_description` text only |
| 2 | non-empty | empty | Stylize from photo, identity only |
| 3 | non-empty | non-empty | Two-pass: base sheet from photo, then enhanced sheet with description as modifications |

### Case 1: Description Only (no images)

**Input:** `SpicyCharacter.images = []`, `story_plan.characters[].visual_description` is non-empty.

**Behavior:** Identical to current "generate" mode. The `visual_description` from `story_plan` is used to generate a portrait from text. No reference image involved.

**Output:** One `CharacterAsset` (base = final).

**No code changes needed.**

### Case 2: Images Only (no description)

**Input:** `SpicyCharacter.images` is non-empty, `SpicyCharacter.description = ""`.

**Behavior:** The reference image is stylized into the art style. Vision verification checks likeness preservation only. The `visual_description` from `story_plan` guides the stylization (it's defined verbatim in `video.json` anyway).

**Output:** One `CharacterAsset` (base = final).

**Minimal change:** When `description` is empty, don't append it to any prompts (current code already handles this since `description` isn't directly used in character sheet generation — `visual_description` from the plan is used instead).

### Case 3: Images + Description (enhancement)

**Input:** `SpicyCharacter.images` is non-empty AND `SpicyCharacter.description` is non-empty.

**Behavior — two-pass generation:**

1. **Pass 1 — Base Sheet:** Generate a character sheet from the reference image using stylize mode with **only** the `visual_description` (identity from plan). No `spicy_traits` or config `description` enhancements are applied. Vision check scores likeness fidelity against the reference photo. This produces the "base" portrait — the character's canonical identity.

2. **Pass 2 — Enhanced Sheet:** Take the base portrait from Pass 1 and apply the `SpicyCharacter.description` as **modifications** via a new `character_enhance_prompt`. This prompt instructs the model to keep the person's face, body, and likeness identical while changing/adding only the specified enhancements (clothing, accessories, skin marks, etc.). `spicy_traits` are also applied in this pass. Vision check verifies both likeness preservation AND that the enhancements are present.

**Output:** Two `CharacterAsset` entries:
- `{name}_base` — the identity-locked portrait (stored for reference)
- `{name}` — the enhanced portrait (used downstream in keyframes and videos)

## Schema Changes

### `schemas.py` — `CharacterAsset`

```python
class CharacterAsset(BaseModel):
    name: str
    portrait_url: str
    portrait_path: str
    visual_description: str
    consistency_score: float
    generation_attempts: int
    # NEW
    base_portrait_path: str | None = None   # Path to pre-enhancement portrait (Case 3)
    enhancement_applied: bool = False        # True if this is a Pass 2 result
    enhancements: list[str] = []             # What was added in Pass 2
```

No changes needed to `SpicyCharacter`, `Character`, or `VideoConfig`.

## Prompt Changes

### `prompts.py` — New functions

```python
def character_enhance_prompt(
    style: str,
    base_description: str,
    enhancements: str,
    video_config: VideoConfig | None = None,
    spicy_traits: list[str] | None = None,
) -> str:
    """Prompt for Pass 2: apply enhancements to the base portrait."""
    desc = enhancements
    if spicy_traits:
        desc = f"{desc}, {', '.join(spicy_traits)}"

    prompt = (
        f"{style}. Modify this character portrait to add the following changes "
        f"while preserving the person's exact facial features, face shape, skin "
        f"tone, hair, and body. Keep the pose and framing similar. "
        f"ONLY change: {desc}. "
        f"Base identity: {base_description}."
    )
    if video_config and video_config.spicy_mode.enabled:
        prompt = f"{video_config.spicy_mode.global_prefix}{prompt}"
        if video_config.narrative_core and video_config.narrative_core.style_directive:
            prompt += f" {video_config.narrative_core.style_directive}."
    return prompt


def character_vision_enhance_prompt(
    character: Character,
    enhancements: str,
) -> str:
    """Vision check for Pass 2: verify both likeness AND enhancements."""
    prompt = (
        f"Image 1 is the enhanced portrait. Image 2 is the base portrait "
        f"(before enhancements). Image 3 is the original reference photo.\n\n"
        f"Score how well the enhanced portrait:\n"
        f"1. Preserves the person's facial features and likeness from the "
        f"reference photo (be strict — face shape, eyes, nose, skin tone)\n"
        f"2. Successfully applies these enhancements: {enhancements}\n\n"
        f"Base description: {character.visual_description}"
    )
    if character.spicy_traits:
        prompt += "\n\n**Also check for these specific details:**\n"
        prompt += "\n".join(f"- {trait}" for trait in character.spicy_traits)
    return prompt
```

## Task Changes

### `tasks/characters.py` — `generate_character_sheet`

Add an `enhancements` parameter:

```python
@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)
def generate_character_sheet(
    character: Character,
    style: str,
    aspect_ratio: str,
    reference_image_path: str | None = None,
    enhancements: str | None = None,     # NEW: description text to apply as modifications
    config: PipelineConfig | None = None,
    video_config: VideoConfig | None = None,
) -> CharacterAsset:
```

**Logic change:**

```python
if reference_image_path and enhancements:
    # CASE 3: Two-pass
    # Pass 1: stylize from reference (identity only — no spicy_traits, no enhancements)
    base_asset = _generate_base_sheet(
        character, style, aspect_ratio, reference_image_path, config, video_config
    )
    # Pass 2: enhance the base portrait
    enhanced_asset = _generate_enhanced_sheet(
        character, style, aspect_ratio, reference_image_path,
        base_asset, enhancements, config, video_config
    )
    return enhanced_asset  # with base_portrait_path set
elif reference_image_path:
    # CASE 2: Images only — single stylize pass (existing behavior)
    ...
else:
    # CASE 1: Description only — single generate pass (existing behavior)
    ...
```

**`_generate_base_sheet()`**: Extract the existing stylize retry loop but strip spicy_traits from the prompt. Uses `character_stylize_prompt(style, character.visual_description, video_config, spicy_traits=None)`. Vision check uses `character_vision_stylize_prompt()` without spicy_traits check.

**`_generate_enhanced_sheet()`**: New function that:
1. Takes the base portrait as input image (via `image_url`)
2. Uses `character_enhance_prompt()` to apply modifications
3. Vision-checks with `character_vision_enhance_prompt()` comparing against base portrait + original reference photo (3 images)
4. Returns `CharacterAsset` with `enhancement_applied=True`, `base_portrait_path` set, and `enhancements` populated

## Pipeline Changes

### `pipeline.py` — Step 2 invocation

Determine the enhancement case per character before calling `generate_character_sheet`:

```python
# ═══ STEP 2: CHARACTER SHEETS (parallel) ═══
char_futures = []
for c in plan.characters:
    # Find the matching SpicyCharacter config (if any)
    cfg_char = next(
        (sc for sc in video_config.characters if sc.name == c.name), None
    )

    # Determine if this is a Case 3 (images + description)
    enhancements = None
    if cfg_char and cfg_char.images and cfg_char.description:
        enhancements = cfg_char.description

    char_futures.append(
        generate_character_sheet.submit(
            c, plan.style, plan.aspect_ratio,
            reference_image_path=matched_refs.get(c.name),
            enhancements=enhancements,
            config=config,
            video_config=video_config,
        )
    )
```

No changes needed to ideation (it doesn't exist anymore). No changes needed to how `visual_description` is defined — it's verbatim from `video.json`'s `story_plan`.

## Downstream Impact

### Keyframes (Step 3)

No change. `char_map[name].portrait_path` points to the **enhanced** portrait (Case 3) or the only portrait (Cases 1 & 2). This is what goes into the keyframe composition as a character reference image.

### Videos (Step 5)

No change. The enhanced portrait is the reference for vision drift checks.

### Vision checks (Steps 3 & 5)

No change. They compare scene/video output against the character portrait, which already has the correct outfit/modifications after enhancement.

### Script (Step 4)

Optional: if `base_portrait_path` is set, include both paths in `script.md`.

### DB / Observer

`on_character` is called once per character with the enhanced asset. Optionally store `base_portrait_path` in the DB for display.

## File Changes Summary

| File | Change |
|---|---|
| `schemas.py` | Add `base_portrait_path`, `enhancement_applied`, `enhancements` fields to `CharacterAsset` |
| `prompts.py` | Add `character_enhance_prompt()`, `character_vision_enhance_prompt()` |
| `tasks/characters.py` | Add `enhancements` param, extract `_generate_base_sheet()`, add `_generate_enhanced_sheet()` |
| `pipeline.py` | Detect Case 3 per character, pass `enhancements` to `generate_character_sheet` |
| `tasks/script.py` | (Optional) Include `base_portrait_path` in script.md |
| `db.py` | (Optional) Add `base_portrait_path` column to `character_assets` table |

## `video.json` Examples for Each Case

### Case 1: Description only (no images)

Top-level character has no images; plan has the visual description:

```json
{
  "characters": [
    {
      "id": "warrior",
      "name": "Warrior",
      "description": "",
      "images": [],
      "spicy_traits": ["battle scars across arms"]
    }
  ],
  "story_plan": {
    "characters": [
      {
        "name": "Warrior",
        "role": "protagonist",
        "visual_description": "Tall muscular woman, dark skin, shaved head, gold armor...",
        "personality_cues": ["fierce", "determined"]
      }
    ]
  }
}
```

### Case 2: Images only (no description)

Top-level character has images but empty description:

```json
{
  "characters": [
    {
      "id": "alex",
      "name": "Alex",
      "description": "",
      "images": ["source_images/alex.jpg"],
      "spicy_traits": []
    }
  ],
  "story_plan": {
    "characters": [
      {
        "name": "Alex",
        "role": "protagonist",
        "visual_description": "Young man with brown hair, blue eyes, athletic build...",
        "personality_cues": ["confident", "relaxed"]
      }
    ]
  }
}
```

### Case 3: Images + description (enhancement)

Top-level character has both images and a description — the description specifies outfit/modification changes to apply on top of the reference photo:

```json
{
  "characters": [
    {
      "id": "maya",
      "name": "Maya",
      "description": "wearing torn black leather harness with metal buckles, sweat-drenched skin, bruising on wrists",
      "images": ["source_images/maya.jpg", "source_images/maya2.jpg"],
      "spicy_traits": ["pallor shift to bluish tint", "veins bulging on neck"]
    }
  ],
  "story_plan": {
    "characters": [
      {
        "name": "Maya",
        "role": "protagonist",
        "visual_description": "Young woman with long dark hair, brown eyes, slender build...",
        "personality_cues": ["terrified", "defiant"]
      }
    ]
  }
}
```

In Case 3: Pass 1 creates a base sheet from `maya.jpg` (preserving her face/body, guided by `visual_description`). Pass 2 takes the base sheet and applies the leather harness, sweat, bruising, plus spicy_traits as a second image-edit pass. The enhanced sheet is what flows into keyframes and videos.

## Enhancement Description Guidelines

The `description` field on top-level `characters[]` for Case 3 should focus on **modifications** — things to add/change relative to the reference photo:

- Clothing/outfits: "wearing a black leather jacket and ripped jeans"
- Accessories: "silver chain necklace, aviator sunglasses"
- Body modifications: "sleeve tattoo on left arm, scar across right cheek"
- Skin effects: "sweat-drenched skin, bruising on arms"
- Hair changes: "hair dyed platinum blonde" (if different from photo)

It should NOT repeat identity information (face shape, ethnicity, eye color) — the reference photo already provides that.

## Acceptance Criteria

1. Case 1 (description only, no images): behavior unchanged from current pipeline
2. Case 2 (images only, empty description): character sheet generated from reference image with `visual_description` guidance; no enhancement pass
3. Case 3 (images + description): two portraits generated — base (identity) and enhanced (with modifications); enhanced portrait used downstream; base portrait stored for reference
4. Vision checks for Case 3 verify both likeness preservation AND enhancement presence
5. Dry-run mode writes prompt files for both passes (Case 3)
6. Existing tests pass without modification
7. Current `video.json` configs continue to work (backward compatible — characters with both images and descriptions become Case 3)

## Migration / Backward Compatibility

Current `video.json` files have characters with both `images` and `description` populated. Under the new system these are Case 3 — a behavior change (two-pass instead of one). The outcome is strictly better (likeness preserved in Pass 1, enhancements applied cleanly in Pass 2), so this is a safe change.

Characters that have no images continue as Case 1. No existing config becomes invalid. The new `CharacterAsset` fields all have defaults (`None`, `False`, `[]`), so old `state.json` files deserialize without error.

## Cost Impact

Case 3 adds one extra image generation + one extra vision check per character. For a 2-character run this adds ~$0.30-0.50 to the baseline. Acceptable given the quality improvement.
