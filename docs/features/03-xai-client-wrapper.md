# Feature 03: xAI Client Wrapper & Helpers

**Priority:** P0 — Foundation
**Depends on:** Card 01 (Project Scaffolding)
**Blocks:** Cards 04, 05, 06, 08

---

## Goal

Create a thin wrapper in `src/grok_spicy/client.py` that centralizes xAI SDK initialization and provides reusable helper functions used across all pipeline tasks.

## Deliverables

### `client.py`

**Client factory:**
- `get_client() -> Client` — reads `GROK_API_KEY` from env (loaded via python-dotenv), returns configured `xai_sdk.Client`
- Fail-fast with clear error if key is missing

**Download helper:**
- `download(url: str, path: str) -> str` — downloads a URL to a local file path, creates parent dirs, returns the path
- Critical because all Grok image/video URLs are **temporary** — must download immediately

**Base64 helper:**
- `to_base64(path: str) -> str` — reads a local file and returns base64-encoded string (used for vision checks on downloaded frames)

**Frame extraction:**
- `extract_frame(video_path: str, output_path: str, position: str = "first") -> str` — wraps FFmpeg to extract first or last frame from a video file
- `position="first"`: `select=eq(n,0)`
- `position="last"`: `-sseof -0.1 -vframes 1`
- Returns output path
- Raises if FFmpeg not found on PATH

**Constants:**
```python
CONSISTENCY_THRESHOLD = 0.80
MAX_CHAR_ATTEMPTS = 3
MAX_KEYFRAME_ITERS = 3
MAX_VIDEO_CORRECTIONS = 2
DEFAULT_DURATION = 8
RESOLUTION = "720p"

MODEL_IMAGE = "grok-imagine-image"
MODEL_VIDEO = "grok-imagine-video"
MODEL_REASONING = "grok-4-1-fast-reasoning"
MODEL_STRUCTURED = "grok-4-1-fast-non-reasoning"
```

## Acceptance Criteria

- [ ] `get_client()` raises clear error when `GROK_API_KEY` is unset
- [ ] `download()` creates intermediate directories and writes file
- [ ] `extract_frame()` works for both first and last frame positions
- [ ] All constants match values from the pipeline plan
- [ ] No business logic — this is purely infrastructure
