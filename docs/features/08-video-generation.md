# Feature 08: Video Generation (Step 5)

**Priority:** P1 — Core Pipeline
**Depends on:** Cards 02 (Schemas), 03 (Client), 06 (Keyframes as input images)
**Blocks:** Card 09 (Assembly needs video clips)

---

## Goal

Implement Step 5: generate a video clip for each scene from its keyframe image, then detect and correct character drift using vision checks and the video edit endpoint.

## Deliverables

### `src/grok_spicy/tasks/video.py`

**`generate_scene_video(keyframe: KeyframeAsset, scene: Scene, char_map: dict[str, CharacterAsset]) -> VideoAsset`**

### Generation flow:

**5a. Image → Video:**
```python
client.video.generate(
    prompt=keyframe.video_prompt,    # Motion-only, no appearance text
    model="grok-imagine-video",
    image_url=keyframe.keyframe_url,
    duration=scene.duration_seconds,
    aspect_ratio="16:9",
    resolution="720p",
)
```

The video prompt describes **camera movement and action only**. The keyframe image encodes the visual truth. Adding appearance text to video prompts creates a tug-of-war that causes drift.

**5b. Download + extract frames:**
- Download video immediately (temporary URL)
- Extract first and last frame via FFmpeg
- Save to `output/frames/scene_{id}_first.jpg` and `scene_{id}_last.jpg`

**5c. Vision check last frame:**
- Send last frame (as base64 data URL) + character reference portraits to `grok-4-1-fast-reasoning`
- "Has the character drifted? Score consistency."
- Parse as `ConsistencyScore`

**5d. Correction loop (max 2 passes):**

Only eligible if `scene.duration_seconds <= 8` (video edit API limit: 8.7s input).

If score < 0.80:
1. Call `client.video.generate(prompt=fix_prompt, model, video_url=current_url)` — video edit mode
2. Note: video edit output matches input duration/ratio/resolution — no custom params
3. Download corrected video
4. Re-extract last frame
5. Re-check with vision
6. Repeat if still below threshold (max 2 corrections)

**5e. Extract last frame for next scene chain:**
- The last frame is available for Step 3's frame chaining when processing subsequent scenes
- However, in the MVP, video gen happens after all keyframes, so this is primarily for debugging

### File output

```
output/videos/scene_{id}.mp4
output/videos/scene_{id}_c1.mp4      # Correction pass 1 (if needed)
output/videos/scene_{id}_c2.mp4      # Correction pass 2 (if needed)
output/frames/scene_{id}_first.jpg
output/frames/scene_{id}_last.jpg
```

**Prefect decoration:**
- `@task(name="generate-video", retries=1, retry_delay_seconds=30, timeout_seconds=600)`
- 10-minute timeout because video generation can be slow

### Important constraints

- Video URLs are temporary — download immediately
- Video edit accepts max 8.7s input — only attempt corrections on clips ≤ 8s
- Video edit output matches input characteristics — cannot change duration/ratio/resolution
- Videos are processed **sequentially** in the MVP (frame chaining dependency)

## Acceptance Criteria

- [ ] Generates video from keyframe with motion-only prompt
- [ ] Downloads video and extracts first/last frames via FFmpeg
- [ ] Vision checks last frame against character reference sheets
- [ ] Correction loop only fires for clips ≤ 8s duration
- [ ] Max 2 correction passes
- [ ] Returns `VideoAsset` with all paths and scores
- [ ] All generated files (originals + corrections) saved to disk
