# Feature 06: Keyframe Composition (Step 3)

**Priority:** P1 — Core Pipeline
**Depends on:** Cards 02 (Schemas), 03 (Client), 05 (Character sheets as reference images)
**Blocks:** Cards 07 (Script), 08 (Video gen needs keyframes)

---

## Goal

Implement Step 3: compose a keyframe image for each scene using multi-image editing. Character reference sheets are passed as input images so Grok can maintain character appearance. Each keyframe goes through a compose → vision-check → fix loop.

## Deliverables

### `src/grok_spicy/tasks/keyframes.py`

**`compose_keyframe(scene: Scene, plan: StoryPlan, char_map: dict[str, CharacterAsset], prev_last_frame_url: str | None) -> KeyframeAsset`**

### The 3-Image Budget (Critical Constraint)

Multi-image edit accepts **max 3 images**. Slot allocation:

| Scene Setup | Slot 1 | Slot 2 | Slot 3 |
|---|---|---|---|
| 1 character | char sheet | prev frame | *empty* |
| 2 characters | char1 sheet | char2 sheet | prev frame |

Build `ref_urls` list accordingly: character portrait URLs first (max 2), then previous scene's last frame if room.

### Composition flow (max 3 iterations):

**Iteration 1 — Initial composition:**
1. Build prompt: `"{STYLE}. Setting: {SETTING}. {MOOD}. {CHAR_1} from reference image 1: {BRIEF_DESC}, positioned on {POSITION}. ... Action: {ACTION}. Camera: {CAMERA}. Color palette: {PALETTE}. Maintain exact character appearances from the reference images."`
2. Call `client.image.sample(prompt, model, image_urls=ref_urls, aspect_ratio=...)`
3. Download keyframe

**Vision consistency check:**
4. Send keyframe + character sheet images to `grok-4-1-fast-reasoning`
5. Prompt: "Image 1 is a scene. Images 2+ are character references. Score how well characters match their refs. If issues, provide a surgical fix prompt."
6. Parse as `ConsistencyScore`

**Iterations 2+ — Targeted edit (if score < 0.80):**
7. Use `client.image.sample(prompt=fix_prompt, model, image_url=best_url)` — single-image edit mode
8. Fix prompt: `"Fix ONLY these issues, keep everything else identical: {issues}"`
9. Re-check via vision

### Video prompt generation

Also generates the motion-focused video prompt for Step 5:
```
"{CAMERA}. {ACTION}. {MOOD}. {STYLE}. Smooth cinematic motion."
```

This is stored on `KeyframeAsset.video_prompt`. It deliberately omits character appearance — the keyframe image carries that.

### Frame chaining

Scenes are processed **sequentially**. Each scene's `keyframe_url` is passed as `prev_last_frame_url` to the next scene, creating visual continuity in backgrounds, lighting, and character positioning.

### File output

```
output/keyframes/scene_{id}_v1.jpg
output/keyframes/scene_{id}_v2.jpg  # if edit pass needed
```

## Acceptance Criteria

- [ ] Multi-image edit with correct reference image slot allocation
- [ ] "From reference image N" explicitly binds characters to input image indices
- [ ] Vision consistency check compares keyframe vs character sheets
- [ ] Fix loop uses surgical single-image edit (max 3 iterations)
- [ ] Generates motion-only video prompt (no appearance text)
- [ ] Supports frame chaining via `prev_last_frame_url`
- [ ] Returns `KeyframeAsset` with best result + video prompt
