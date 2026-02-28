# Grok Imagine × Prefect.io Video Pipeline
## From Concept → Consistent Multi-Scene Video

---

## 1. Verified API Surface (from xAI docs, Feb 2026)

Everything in this plan uses **only** these four Grok endpoints. No open-source models, no local GPU.

### Image Generation & Editing (`grok-imagine-image`)

| Operation | SDK Call | Key Parameters |
|---|---|---|
| **Text → Image** | `client.image.sample(prompt, model)` | `n` (batch), `aspect_ratio`, `resolution` |
| **Single-Image Edit** | `client.image.sample(prompt, model, image_url=...)` | Output matches input aspect ratio |
| **Multi-Image Edit** | `client.image.sample(prompt, model, image_urls=[...])` | **Up to 3 input images.** Output follows first image's ratio unless `aspect_ratio` overridden |
| **Batch Generate** | `client.image.sample_batch(prompt, model, n=4)` | Generate N variants in one call |
| **Async Concurrent** | `AsyncClient` + `asyncio.gather` | Fire multiple requests in parallel |

**Critical detail:** The OpenAI SDK `images.edit()` method does **not** work for editing (it uses multipart/form-data). Must use xAI SDK or direct HTTP with JSON body.

### Video Generation & Editing (`grok-imagine-video`)

| Operation | SDK Call | Key Parameters |
|---|---|---|
| **Text → Video** | `client.video.generate(prompt, model, ...)` | `duration` (1–15s), `aspect_ratio` (default 16:9), `resolution` (480p/720p) |
| **Image → Video** | `client.video.generate(prompt, model, image_url=...)` | Single image input. Duration/ratio/resolution configurable |
| **Video Edit** | `client.video.generate(prompt, model, video_url=...)` | Input max **8.7 seconds**. Output matches input duration, ratio, resolution (capped 720p). No custom duration/ratio/resolution |
| **Manual Poll** | `client.video.start(...)` → `client.video.get(request_id)` | For custom polling logic |
| **Async Concurrent** | `AsyncClient` + `asyncio.gather` | xAI docs show this exact pattern for parallel video edits |

**Critical detail:** Video URLs are **temporary**. Download every asset immediately after generation.

### Structured Outputs (`grok-4-1-fast` / `grok-4-1-fast-non-reasoning`)

| Operation | SDK Call | Notes |
|---|---|---|
| **Pydantic Parse** | `chat.parse(PydanticModel)` | Returns `(response, parsed_object)` |
| **With Tools** | `chat.parse(Model, tools=[...])` | Combine with function calling or web search |
| **JSON Schema** | `response_format={"type":"json_schema","json_schema":...}` | OpenAI-compatible path (Responses API) |

**Critical detail:** Structured outputs with Pydantic `chat.parse()` works on the **Grok 4 family only**. For non-reasoning tasks, use `grok-4-1-fast-non-reasoning` (cheaper, no thinking tokens).

### Vision / Image Understanding (`grok-4-1-fast-reasoning`)

| Operation | SDK Call | Notes |
|---|---|---|
| **Analyze Image** | `chat.append(user("prompt", image(url)))` | Multiple images supported in one message |
| **Compare Images** | `chat.append(user("compare", image(url1), image(url2)))` | Perfect for consistency checks |

---

## 2. Pipeline Architecture

```
                        ┌─────────────────┐
                        │   User Concept   │
                        │  "A story about  │
                        │   a fox and owl  │
                        │   in a forest"   │
                        └────────┬────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP 1: IDEATION                                                   │
│ grok-4-1-fast-non-reasoning + Pydantic StoryPlan                   │
│                                                                    │
│ IN:  concept string                                                │
│ OUT: StoryPlan{characters[], scenes[], style, palette}             │
│                                                                    │
│ Single LLM call with structured output.                            │
│ The visual_description on each character is 100+ words and         │
│ becomes the FROZEN identity string used everywhere downstream.     │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP 2: CHARACTER SHEETS (per character, parallelizable)           │
│ grok-imagine-image                                                 │
│                                                                    │
│ ┌──────────────────────────────────────────────┐                   │
│ │ 2a. Generate portrait (text → image)         │                   │
│ │     prompt = style + visual_description +     │                  │
│ │     "neutral bg, character reference sheet"   │                  │
│ │                                               │                  │
│ │ 2b. Vision verify (grok-4-1-fast-reasoning)  │                   │
│ │     "Does this image match: {description}?"   │                  │
│ │     → parse ConsistencyScore                  │                  │
│ │                                               │                  │
│ │ 2c. If score < 0.8 → regenerate (max 3×)     │                   │
│ └──────────────┬───────────────────────────────┘                   │
│                │ RETRY LOOP                                        │
│                                                                    │
│ OUT: CharacterSheet per character (verified portrait URL + file)   │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP 3: KEYFRAME COMPOSITION (per scene, sequential for chaining) │
│ grok-imagine-image (multi-image edit mode, up to 3 refs)           │
│                                                                    │
│ ┌──────────────────────────────────────────────┐                   │
│ │ 3a. Compose scene keyframe                   │                   │
│ │     image_urls = [char1_sheet, char2_sheet,   │                  │
│ │                   prev_scene_last_frame?]     │                  │
│ │     (max 3 images per API limit)              │                  │
│ │     prompt = scene desc + positions +          │                 │
│ │              camera + mood + style lock        │                 │
│ │                                               │                  │
│ │ 3b. Vision consistency check                  │                  │
│ │     Compare keyframe vs each character sheet  │                  │
│ │     → parse ConsistencyScore                  │                  │
│ │                                               │                  │
│ │ 3c. If issues found → targeted edit           │                  │
│ │     image_url = keyframe                      │                  │
│ │     prompt = "Fix ONLY: {specific issue}"     │                  │
│ │                                               │                  │
│ │ 3d. Re-check. If still < 0.8 → regenerate    │                  │
│ └──────────────┬───────────────────────────────┘                   │
│                │ REFINE LOOP (max 3 iterations)                    │
│                                                                    │
│ OUT: Verified keyframe image per scene                             │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP 4: COMPILE SCRIPT                                             │
│ Pure Python — no API calls                                         │
│                                                                    │
│ Generates:                                                         │
│   script.md   — human-readable storyboard with embedded images     │
│   state.json  — machine-readable pipeline state for resumability   │
│                                                                    │
│ Contains per-scene: keyframe path, exact video prompt,             │
│ duration, transition, generation log                               │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP 5: VIDEO GENERATION (per scene, sequential for chaining)     │
│ grok-imagine-video (image → video)                                 │
│                                                                    │
│ ┌──────────────────────────────────────────────┐                   │
│ │ 5a. Generate video from keyframe              │                  │
│ │     image_url = scene keyframe                │                  │
│ │     prompt = MOTION-focused (not appearance)  │                  │
│ │     duration = from plan (max 15s)            │                  │
│ │                                               │                  │
│ │ 5b. Download video, extract first+last frame  │                  │
│ │     via FFmpeg                                │                  │
│ │                                               │                  │
│ │ 5c. Vision check last frame vs char sheets    │                  │
│ │     Has character drifted during the video?   │                  │
│ │                                               │                  │
│ │ 5d. If drift AND duration ≤ 8.7s →            │                  │
│ │     Video Edit correction pass                │                  │
│ │     video_url = generated video               │                  │
│ │     prompt = "Fix: {drift description}"       │                  │
│ │                                               │                  │
│ │ 5e. Extract last frame for next scene chain   │                  │
│ └──────────────┬───────────────────────────────┘                   │
│                │ CORRECTION LOOP (max 2×)                          │
│                                                                    │
│ OUT: Downloaded .mp4 per scene + extracted frames                  │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP 6: ASSEMBLY                                                   │
│ FFmpeg                                                             │
│                                                                    │
│ 6a. Normalize all clips (codec, fps, resolution)                   │
│ 6b. Apply crossfade transitions (0.5s)                             │
│ 6c. Concatenate → final_video.mp4                                  │
│ 6d. Update script.md with final video path + stats                 │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Pydantic Schemas (Structured Output Contracts)

Every inter-step handoff is typed. These schemas are passed directly to `chat.parse()`.

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# STEP 1 OUTPUT: Story Plan
# ═══════════════════════════════════════════════════════════════

class Character(BaseModel):
    """A character in the story. visual_description is the SOLE source
    of truth for appearance — used verbatim in every downstream prompt."""
    name: str = Field(description="Short unique name, e.g. 'Luna'")
    role: str = Field(description="protagonist / antagonist / supporting")
    visual_description: str = Field(
        description=(
            "Exhaustive visual description, minimum 80 words. Include: "
            "age range, gender, ethnicity/skin tone, hair (color, style, length), "
            "eye color, facial features (nose shape, jawline), body build, "
            "exact clothing (colors, materials, accessories), "
            "any distinguishing marks (scars, tattoos, glasses). "
            "This text is copy-pasted into every image prompt — be precise."
        )
    )
    personality_cues: list[str] = Field(
        description="3-5 adjective/phrases for expression guidance"
    )

class Scene(BaseModel):
    scene_id: int
    title: str = Field(description="Brief scene title, 3-6 words")
    description: str = Field(description="What happens in 2-3 sentences")
    characters_present: list[str] = Field(
        description="Character names (must match Character.name exactly)"
    )
    setting: str = Field(description="Physical environment, time of day, weather")
    camera: str = Field(description="Shot type + movement: 'medium shot, slow dolly forward'")
    mood: str = Field(description="Lighting/atmosphere: 'warm golden hour, soft shadows'")
    action: str = Field(description="Primary motion for video: 'fox leaps over a fallen log'")
    duration_seconds: int = Field(ge=3, le=15, description="Video duration, 8 is a good default")
    transition: str = Field(default="cut", description="cut / crossfade / match-cut")

class StoryPlan(BaseModel):
    title: str
    style: str = Field(
        description=(
            "Visual style for ALL images/videos. Be specific: "
            "'Pixar-style 3D animation with soft volumetric lighting' "
            "not just 'animated'. This prefix starts every prompt."
        )
    )
    aspect_ratio: str = Field(default="16:9", description="16:9 / 9:16 / 1:1 / 4:3")
    color_palette: str = Field(
        description="Dominant colors: 'deep forest greens, amber, moonlight silver'"
    )
    characters: list[Character]
    scenes: list[Scene]


# ═══════════════════════════════════════════════════════════════
# STEP 2-3: Consistency Scoring (used by Vision checks)
# ═══════════════════════════════════════════════════════════════

class ConsistencyScore(BaseModel):
    overall_score: float = Field(ge=0.0, le=1.0,
        description="0 = completely wrong, 1 = perfect match")
    per_character: dict[str, float] = Field(default_factory=dict,
        description="Score per character name")
    issues: list[str] = Field(default_factory=list,
        description="Specific problems: 'hair is brown, should be red'")
    fix_prompt: Optional[str] = Field(default=None,
        description="Surgical edit prompt to fix issues if any")


# ═══════════════════════════════════════════════════════════════
# PIPELINE STATE (resumability + script generation)
# ═══════════════════════════════════════════════════════════════

class CharacterAsset(BaseModel):
    name: str
    portrait_url: str
    portrait_path: str
    visual_description: str
    consistency_score: float
    generation_attempts: int

class KeyframeAsset(BaseModel):
    scene_id: int
    keyframe_url: str
    keyframe_path: str
    consistency_score: float
    generation_attempts: int
    edit_passes: int
    video_prompt: str

class VideoAsset(BaseModel):
    scene_id: int
    video_url: str
    video_path: str
    duration: float
    first_frame_path: str
    last_frame_path: str
    consistency_score: float
    correction_passes: int

class PipelineState(BaseModel):
    plan: StoryPlan
    characters: list[CharacterAsset] = []
    keyframes: list[KeyframeAsset] = []
    videos: list[VideoAsset] = []
    final_video_path: Optional[str] = None
```

---

## 4. Prefect Pipeline Implementation

### Why Prefect

Prefect gives us: automatic retries on API failures, observability (see where a scene failed in the timeline UI), task-level caching (don't regenerate a passing character sheet), and concurrent task submission via `.submit()`.

### Complete Flow

```python
from prefect import flow, task
from prefect.tasks import task_input_hash
from datetime import timedelta
import asyncio, os, base64, json, subprocess, requests

# ─── CONFIG ───────────────────────────────────────────────────

CONSISTENCY_THRESHOLD = 0.80
MAX_CHAR_ATTEMPTS     = 3
MAX_KEYFRAME_ITERS    = 3
MAX_VIDEO_CORRECTIONS = 2
DEFAULT_DURATION      = 8
RESOLUTION            = "720p"


def _download(url: str, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = requests.get(url); r.raise_for_status()
    with open(path, "wb") as f: f.write(r.content)
    return path

def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def _extract_frame(video: str, out: str, position: str = "first"):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if position == "first":
        subprocess.run(["ffmpeg","-y","-i",video,
            "-vf","select=eq(n\\,0)","-vframes","1",out],
            capture_output=True)
    else:
        subprocess.run(["ffmpeg","-y","-sseof","-0.1","-i",video,
            "-vframes","1",out], capture_output=True)


# ══════════════════════════════════════════════════════════════
# STEP 1: IDEATION
# ══════════════════════════════════════════════════════════════

@task(name="plan-story", retries=2, retry_delay_seconds=10,
      cache_key_fn=task_input_hash, cache_expiration=timedelta(hours=1))
def plan_story(concept: str) -> StoryPlan:
    from xai_sdk import Client
    from xai_sdk.chat import system, user

    client = Client()
    chat = client.chat.create(model="grok-4-1-fast-non-reasoning")
    chat.append(system(
        "You are a visual storytelling director. Create a production plan. "
        "Every character needs an exhaustive visual description (80+ words) — "
        "this is the sole appearance reference used for all image generation. "
        "Design scenes for 8-second video clips with simple, clear actions. "
        "Limit: 2-3 characters, 3-5 scenes for best quality."
    ))
    chat.append(user(f"Create a visual story plan for: {concept}"))
    _, plan = chat.parse(StoryPlan)
    return plan


# ══════════════════════════════════════════════════════════════
# STEP 2: CHARACTER SHEETS
# ══════════════════════════════════════════════════════════════

@task(name="generate-character-sheet", retries=2, retry_delay_seconds=15)
def generate_character_sheet(
    character: Character, style: str, aspect_ratio: str
) -> CharacterAsset:
    from xai_sdk import Client
    from xai_sdk.chat import user as usr, image

    client = Client()
    best = {"score": 0.0, "url": "", "path": ""}

    for attempt in range(1, MAX_CHAR_ATTEMPTS + 1):
        # 2a: Generate portrait
        prompt = (
            f"{style}. Full body character portrait of "
            f"{character.visual_description}. "
            f"Standing in a neutral three-quarter pose against a plain "
            f"light gray background. Professional character design "
            f"reference sheet style. Sharp details, even studio lighting, "
            f"no background clutter, no text or labels."
        )
        img = client.image.sample(
            prompt=prompt, model="grok-imagine-image",
            aspect_ratio=aspect_ratio,
        )
        path = _download(
            img.url,
            f"output/character_sheets/{character.name}_v{attempt}.jpg"
        )

        # 2b: Vision verify
        chat = client.chat.create(model="grok-4-1-fast-reasoning")
        chat.append(usr(
            f"Score how well this portrait matches the description. "
            f"Be strict on: hair color/style, eye color, clothing "
            f"colors and style, build, distinguishing features.\n\n"
            f"Description: {character.visual_description}",
            image(img.url),
        ))
        _, score = chat.parse(ConsistencyScore)

        if score.overall_score > best["score"]:
            best = {"score": score.overall_score,
                    "url": img.url, "path": path}

        if score.overall_score >= CONSISTENCY_THRESHOLD:
            break

    return CharacterAsset(
        name=character.name,
        portrait_url=best["url"],
        portrait_path=best["path"],
        visual_description=character.visual_description,
        consistency_score=best["score"],
        generation_attempts=attempt,
    )


# ══════════════════════════════════════════════════════════════
# STEP 3: KEYFRAME COMPOSITION
# ══════════════════════════════════════════════════════════════

@task(name="compose-keyframe", retries=1, retry_delay_seconds=20)
def compose_keyframe(
    scene: Scene, plan: StoryPlan,
    char_map: dict[str, CharacterAsset],
    prev_last_frame_url: str | None,
) -> KeyframeAsset:
    from xai_sdk import Client
    from xai_sdk.chat import user as usr, image

    client = Client()
    scene_chars = [char_map[n] for n in scene.characters_present if n in char_map]

    # Build reference URLs (max 3)
    ref_urls = [c.portrait_url for c in scene_chars[:2]]
    if prev_last_frame_url and len(ref_urls) < 3:
        ref_urls.append(prev_last_frame_url)

    # Composition prompt
    char_lines = []
    for i, c in enumerate(scene_chars[:2]):
        pos = ["left side", "right side"][i] if len(scene_chars) > 1 else "center"
        # Truncate description for scene prompt (keep most distinctive traits)
        brief = c.visual_description[:250]
        char_lines.append(
            f"{c.name} from reference image {i+1}: {brief}, "
            f"positioned on the {pos}"
        )

    compose_prompt = (
        f"{plan.style}. "
        f"Setting: {scene.setting}. {scene.mood}. "
        f"{'. '.join(char_lines)}. "
        f"Action: {scene.action}. "
        f"Camera: {scene.camera}. "
        f"Color palette: {plan.color_palette}. "
        f"Maintain exact character appearances from the reference images."
    )

    # Motion-focused video prompt (for Step 5)
    video_prompt = (
        f"{scene.camera}. {scene.action}. "
        f"{scene.mood}. {plan.style}. "
        f"Smooth cinematic motion."
    )

    best = {"score": 0.0, "url": "", "path": ""}
    fix_prompt = None

    for iteration in range(1, MAX_KEYFRAME_ITERS + 1):
        if iteration == 1:
            # 3a: Multi-image composition
            img = client.image.sample(
                prompt=compose_prompt,
                model="grok-imagine-image",
                image_urls=ref_urls,
                aspect_ratio=plan.aspect_ratio,
            )
        else:
            # 3c: Targeted edit
            img = client.image.sample(
                prompt=fix_prompt,
                model="grok-imagine-image",
                image_url=best["url"],
            )

        path = _download(
            img.url,
            f"output/keyframes/scene_{scene.scene_id}_v{iteration}.jpg"
        )

        # 3b: Vision consistency check
        vision_imgs = [image(img.url)]
        for c in scene_chars[:2]:
            vision_imgs.append(image(c.portrait_url))

        chat = client.chat.create(model="grok-4-1-fast-reasoning")
        chat.append(usr(
            "Image 1 is a scene. Images 2+ are character references. "
            "Score how well characters in the scene match their refs. "
            "If issues, provide a surgical fix prompt.",
            *vision_imgs,
        ))
        _, score = chat.parse(ConsistencyScore)

        if score.overall_score > best["score"]:
            best = {"score": score.overall_score,
                    "url": img.url, "path": path}

        if score.overall_score >= CONSISTENCY_THRESHOLD:
            break

        fix_prompt = score.fix_prompt or (
            f"Fix ONLY these issues, keep everything else identical: "
            f"{'; '.join(score.issues)}"
        )

    return KeyframeAsset(
        scene_id=scene.scene_id,
        keyframe_url=best["url"], keyframe_path=best["path"],
        consistency_score=best["score"],
        generation_attempts=1, edit_passes=iteration - 1,
        video_prompt=video_prompt,
    )


# ══════════════════════════════════════════════════════════════
# STEP 4: COMPILE SCRIPT
# ══════════════════════════════════════════════════════════════

@task(name="compile-script")
def compile_script(
    plan: StoryPlan,
    characters: list[CharacterAsset],
    keyframes: list[KeyframeAsset],
) -> str:
    lines = [
        f"# {plan.title}\n",
        f"**Style:** {plan.style}  ",
        f"**Aspect Ratio:** {plan.aspect_ratio}  ",
        f"**Color Palette:** {plan.color_palette}\n",
        f"---\n",
        f"## Characters\n",
    ]
    for c in characters:
        lines += [
            f"### {c.name}",
            f"**Score:** {c.consistency_score:.2f} | "
            f"**Attempts:** {c.generation_attempts}\n",
            f"> {c.visual_description}\n",
            f"![{c.name}]({c.portrait_path})\n",
        ]
    lines += [f"---\n", f"## Scenes\n"]
    for kf in sorted(keyframes, key=lambda k: k.scene_id):
        sc = next(s for s in plan.scenes if s.scene_id == kf.scene_id)
        lines += [
            f"### Scene {sc.scene_id}: {sc.title}\n",
            f"| Property | Value |",
            f"|---|---|",
            f"| Setting | {sc.setting} |",
            f"| Characters | {', '.join(sc.characters_present)} |",
            f"| Camera | {sc.camera} |",
            f"| Duration | {sc.duration_seconds}s |",
            f"| Transition | {sc.transition} |",
            f"| Consistency | {kf.consistency_score:.2f} (edits: {kf.edit_passes}) |\n",
            f"![Scene {sc.scene_id}]({kf.keyframe_path})\n",
            f"**Video Prompt:**",
            f"> {kf.video_prompt}\n",
        ]

    path = "output/script.md"
    os.makedirs("output", exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


# ══════════════════════════════════════════════════════════════
# STEP 5: VIDEO GENERATION
# ══════════════════════════════════════════════════════════════

@task(name="generate-video", retries=1,
      retry_delay_seconds=30, timeout_seconds=600)
def generate_scene_video(
    keyframe: KeyframeAsset, scene: Scene,
    char_map: dict[str, CharacterAsset],
) -> VideoAsset:
    from xai_sdk import Client
    from xai_sdk.chat import user as usr, image

    client = Client()
    corrections = 0

    # 5a: Image → Video
    vid = client.video.generate(
        prompt=keyframe.video_prompt,
        model="grok-imagine-video",
        image_url=keyframe.keyframe_url,
        duration=scene.duration_seconds,
        aspect_ratio="16:9",
        resolution=RESOLUTION,
    )

    video_path = f"output/videos/scene_{scene.scene_id}.mp4"
    _download(vid.url, video_path)
    current_url = vid.url

    # 5b: Extract frames
    first_frame = f"output/frames/scene_{scene.scene_id}_first.jpg"
    last_frame = f"output/frames/scene_{scene.scene_id}_last.jpg"
    _extract_frame(video_path, first_frame, "first")
    _extract_frame(video_path, last_frame, "last")

    # 5c: Vision check last frame
    scene_chars = [char_map[n] for n in scene.characters_present if n in char_map]
    chat = client.chat.create(model="grok-4-1-fast-reasoning")
    imgs = [image(f"data:image/jpeg;base64,{_b64(last_frame)}")]
    for c in scene_chars[:2]:
        imgs.append(image(c.portrait_url))
    chat.append(usr(
        "Image 1 is a video's last frame. Images 2+ are character refs. "
        "Has the character drifted? Score consistency.", *imgs
    ))
    _, score = chat.parse(ConsistencyScore)

    # 5d: Correction loop (only for clips ≤ 8s, API limit 8.7s)
    while (score.overall_score < CONSISTENCY_THRESHOLD
           and corrections < MAX_VIDEO_CORRECTIONS
           and scene.duration_seconds <= 8):
        corrections += 1
        fix = score.fix_prompt or f"Fix: {'; '.join(score.issues)}"

        vid = client.video.generate(
            prompt=fix, model="grok-imagine-video",
            video_url=current_url,
        )
        current_url = vid.url
        corr_path = f"output/videos/scene_{scene.scene_id}_c{corrections}.mp4"
        _download(vid.url, corr_path)
        video_path = corr_path

        _extract_frame(video_path, last_frame, "last")
        chat = client.chat.create(model="grok-4-1-fast-reasoning")
        chat.append(usr(
            "Image 1 is a video's last frame. Images 2+ are refs. "
            "Score consistency.", *imgs
        ))
        _, score = chat.parse(ConsistencyScore)

    return VideoAsset(
        scene_id=scene.scene_id,
        video_url=current_url, video_path=video_path,
        duration=scene.duration_seconds,
        first_frame_path=first_frame, last_frame_path=last_frame,
        consistency_score=score.overall_score,
        correction_passes=corrections,
    )


# ══════════════════════════════════════════════════════════════
# STEP 6: ASSEMBLY
# ══════════════════════════════════════════════════════════════

@task(name="assemble-video")
def assemble_final_video(videos: list[VideoAsset]) -> str:
    sorted_vids = sorted(videos, key=lambda v: v.scene_id)

    if len(sorted_vids) == 1:
        final = "output/final_video.mp4"
        subprocess.run(["cp", sorted_vids[0].video_path, final])
        return final

    # Write concat file
    concat_file = "output/concat.txt"
    with open(concat_file, "w") as f:
        for v in sorted_vids:
            # Normalize each clip first
            norm = v.video_path.replace(".mp4", "_norm.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-i", v.video_path,
                "-vf", "fps=24,scale=1280:720:force_original_aspect_ratio=decrease,"
                       "pad=1280:720:-1:-1:color=black",
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-ar", "44100",
                norm
            ], capture_output=True)
            f.write(f"file '{os.path.abspath(norm)}'\n")

    final = "output/final_video.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        final
    ], capture_output=True, check=True)
    return final


# ═══════════════════════════════════════════════════════════════
# MAIN FLOW
# ═══════════════════════════════════════════════════════════════

@flow(name="grok-video-pipeline", retries=1,
      retry_delay_seconds=60, log_prints=True)
def video_pipeline(concept: str) -> str:

    # STEP 1
    print("═══ STEP 1: Planning story ═══")
    plan = plan_story(concept)
    print(f"→ {plan.title}: {len(plan.characters)} chars, {len(plan.scenes)} scenes")

    # STEP 2 (parallel via .submit)
    print("═══ STEP 2: Character sheets ═══")
    char_futures = [
        generate_character_sheet.submit(c, plan.style, plan.aspect_ratio)
        for c in plan.characters
    ]
    characters = [f.result() for f in char_futures]
    char_map = {c.name: c for c in characters}
    for c in characters:
        print(f"  {c.name}: score={c.consistency_score:.2f}, attempts={c.generation_attempts}")

    # STEP 3 (sequential for frame chaining)
    print("═══ STEP 3: Keyframes ═══")
    keyframes = []
    prev_url = None
    for scene in plan.scenes:
        kf = compose_keyframe(scene, plan, char_map, prev_url)
        keyframes.append(kf)
        prev_url = kf.keyframe_url  # chain to next scene
        print(f"  Scene {scene.scene_id}: score={kf.consistency_score:.2f}, edits={kf.edit_passes}")

    # STEP 4
    print("═══ STEP 4: Script ═══")
    script = compile_script(plan, characters, keyframes)
    print(f"→ {script}")

    # Save state
    state = PipelineState(plan=plan, characters=characters, keyframes=keyframes)
    with open("output/state.json", "w") as f:
        f.write(state.model_dump_json(indent=2))

    # STEP 5 (sequential for chaining)
    print("═══ STEP 5: Videos ═══")
    videos = []
    for scene, kf in zip(plan.scenes, keyframes):
        v = generate_scene_video(kf, scene, char_map)
        videos.append(v)
        print(f"  Scene {scene.scene_id}: score={v.consistency_score:.2f}, "
              f"corrections={v.correction_passes}")

    # STEP 6
    print("═══ STEP 6: Assembly ═══")
    final = assemble_final_video(videos)
    print(f"✓ {final}")

    # Final state
    state.videos = videos
    state.final_video_path = final
    with open("output/state.json", "w") as f:
        f.write(state.model_dump_json(indent=2))

    return final


if __name__ == "__main__":
    video_pipeline(
        "A curious fox named Ember meets a wise old owl named Sage "
        "in an enchanted autumn forest. They discover a glowing "
        "crystal and must decide what to do with it."
    )
```

---

## 5. Prompt Engineering Strategy

### The Style Lock

Every image/video prompt starts with `plan.style`. This is the single most important consistency lever.

**Good:** `"Studio Ghibli-inspired watercolor animation with soft edges, warm tones, and hand-drawn texture"`
**Bad:** `"animated"` — too vague, each generation will interpret differently

### Character Sheet Prompt

```
{STYLE}. Full body character portrait of {VISUAL_DESCRIPTION}.
Standing in a neutral three-quarter pose against a plain light gray background.
Professional character design reference sheet style.
Sharp details, even studio lighting, no background clutter, no text or labels.
```

Three-quarter pose shows more of the character than front-on. Gray background isolates them cleanly.

### Scene Keyframe Prompt (Multi-Image Edit)

```
{STYLE}. Setting: {SETTING}. {MOOD}.
{CHAR_1} from reference image 1: {BRIEF_DESC}, positioned on the {POSITION}.
{CHAR_2} from reference image 2: {BRIEF_DESC}, positioned on the {POSITION}.
Action: {ACTION}. Camera: {CAMERA}. Color palette: {PALETTE}.
Maintain exact character appearances from the reference images.
```

"From reference image N" explicitly binds each character to its input image index — crucial when passing multiple references.

### Video Prompt (Motion Only)

```
{CAMERA_MOVEMENT}. {ACTION}. {MOOD}. {STYLE}. Smooth cinematic motion.
```

**Do NOT repeat character appearance** in video prompts. The keyframe image already encodes how they look. Adding appearance text creates a tug-of-war between image and text, causing drift.

### Fix/Edit Prompt

```
Change ONLY {ELEMENT}: {FIX}. Keep everything else identical.
Do not alter any character not mentioned.
```

Surgical. Broad edits ("make it better") cause cascading unwanted changes.

---

## 6. The 3-Image Budget (Critical Constraint)

Multi-image edit accepts **max 3 images**. This is the tightest constraint in the pipeline.

| Scene Setup | Slot 1 | Slot 2 | Slot 3 | Trade-off |
|---|---|---|---|---|
| 1 character | char sheet | prev frame | *empty* | Best consistency + continuity |
| 2 characters | char1 sheet | char2 sheet | prev frame | Full coverage |
| 2 chars, no chain | char1 sheet | char2 sheet | *empty* | Loses temporal continuity |
| 3+ characters | char1 | char2 | prev frame | Char 3+ text-only — will drift |

**PoC recommendation:** Limit to 2 characters per scene. Reserve slot 3 for frame chaining.

---

## 7. Consistency Maximization Techniques

1. **Frozen descriptions** — The `visual_description` from Step 1 is never paraphrased. Same string everywhere.

2. **Multi-image anchoring** — Always pass character sheets as `image_urls[]` in Step 3. Never rely on text alone.

3. **Last-frame chaining** — Scene N's last frame becomes reference input for Scene N+1's keyframe. Creates visual continuity in backgrounds, lighting, positioning.

4. **Vision-in-the-loop** — Every generation is checked by Grok Vision against the reference sheets. Issues generate specific fix prompts. Max 3 iterations before accepting best-of-N.

5. **Video edit correction** — For clips ≤8s, use the video edit endpoint to surgically fix drift detected in the last frame. This is a Grok-exclusive capability other pipelines lack.

6. **Motion-only video prompts** — Keep Step 5 prompts about camera and action, not appearance. The keyframe carries the visual truth.

7. **Re-anchor every scene** — Always reference original character sheets, not just the previous frame. Previous frames carry accumulated drift.

---

## 8. Output Structure

```
output/
├── character_sheets/
│   ├── Ember_v1.jpg, Ember_v2.jpg    # All attempts kept
│   └── Sage_v1.jpg
├── keyframes/
│   ├── scene_1_v1.jpg, scene_1_v2.jpg
│   └── scene_2_v1.jpg
├── frames/
│   ├── scene_1_first.jpg, scene_1_last.jpg
│   └── scene_2_first.jpg, scene_2_last.jpg
├── videos/
│   ├── scene_1.mp4, scene_1_c1.mp4   # Original + corrections
│   └── scene_2.mp4
├── script.md          # Human-readable storyboard
├── state.json         # Full pipeline state (Pydantic → JSON)
└── final_video.mp4    # Assembled output
```

---

## 9. PoC Scope

| Dimension | Target |
|---|---|
| Input | 1-2 sentence concept |
| Characters | 2 maximum |
| Scenes | 3 (8s each) |
| Output | ~24s video, 720p, 16:9 |
| Dependencies | `xai-sdk`, `prefect`, `pydantic`, `requests`, `ffmpeg` |
| Cost | ~$3.80 per run |
| Runtime | ~5-6 minutes |

### Success = both characters visually recognizable as the same entity across all 3 scenes.

---

## 10. Limitations & Workarounds

| Limitation | Workaround |
|---|---|
| Max 3 reference images in edit | Limit 2 chars/scene; extra chars text-only |
| Video uses single `image_url` | Invest heavily in Step 3 keyframe quality |
| Video edit max 8.7s input | Keep scenes ≤ 8s for correction eligibility |
| Temporary URLs | Download everything immediately |
| No audio control | Accept native audio for PoC |
| Structured output = Grok 4 only | Use `grok-4-1-fast-non-reasoning` (cheapest) |
| OpenAI SDK edit incompatible | Must use xAI native SDK |

---

## 11. Future Enhancements

- **Audio overlay** via Eleven Labs voiceover mixed over Grok native audio
- **Longer videos** by splitting >15s scenes into sub-scenes with match-cuts
- **Parallel video gen** for non-chained scenes via `AsyncClient` + `gather`
- **Human-in-the-loop** via Prefect pause/resume for keyframe approval
- **Batch variants** using `sample_batch(n=4)` to pick best keyframe
- **Background plates** generated separately, characters composited on top
- **Character turnarounds** (front/side/back) for richer multi-angle reference
