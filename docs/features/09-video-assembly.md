# Feature 09: Video Assembly (Step 6)

**Priority:** P1 — Core Pipeline
**Depends on:** Card 08 (Video clips)
**Blocks:** Card 10 (Pipeline completion)

---

## Goal

Implement Step 6: normalize all scene video clips to a common format and concatenate them into a single final video using FFmpeg.

## Deliverables

### `src/grok_spicy/tasks/assembly.py`

**`assemble_final_video(videos: list[VideoAsset]) -> str`**

### Assembly flow:

**Single clip shortcut:**
If only 1 video, copy it directly to `output/final_video.mp4` — no processing needed.

**Multi-clip pipeline:**

**6a. Normalize each clip:**
```
ffmpeg -y -i {input} \
    -vf "fps=24,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:-1:-1:color=black" \
    -c:v libx264 -preset fast \
    -c:a aac -ar 44100 \
    {input}_norm.mp4
```
- Force 24fps
- Scale to 1280x720, preserve aspect ratio, pad with black bars if needed
- Re-encode to H.264 for codec consistency
- Normalize audio to AAC 44.1kHz

**6b. Write concat file:**
```
file '/absolute/path/to/scene_1_norm.mp4'
file '/absolute/path/to/scene_2_norm.mp4'
file '/absolute/path/to/scene_3_norm.mp4'
```

**6c. Concatenate:**
```
ffmpeg -y -f concat -safe 0 \
    -i concat.txt \
    -c:v libx264 -preset medium -crf 18 \
    -c:a aac -b:a 192k \
    output/final_video.mp4
```
- CRF 18 for high quality
- Medium preset balances speed/quality for final output

### File output

```
output/videos/scene_{id}_norm.mp4    # Normalized intermediates
output/concat.txt                     # Concat manifest
output/final_video.mp4               # Final assembled video
```

**Prefect decoration:**
- `@task(name="assemble-video")`
- No retries (local FFmpeg, deterministic)

### Future: Crossfade transitions

The plan mentions 0.5s crossfade transitions. For the MVP, simple cuts (concat) are sufficient. Crossfades can be added later using FFmpeg's `xfade` filter:
```
-filter_complex "[0:v][1:v]xfade=transition=fade:duration=0.5:offset={scene1_duration-0.5}"
```

## Acceptance Criteria

- [ ] Single-clip shortcut works (no unnecessary processing)
- [ ] Multi-clip normalization produces consistent codec/fps/resolution
- [ ] Concat file uses absolute paths with `-safe 0`
- [ ] Final video is properly encoded (H.264, AAC)
- [ ] FFmpeg errors are surfaced, not swallowed
- [ ] Returns path to `final_video.mp4`
