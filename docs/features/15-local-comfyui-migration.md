# Feature 15: Multi-Backend Provider Architecture & Local ComfyUI Migration

**ID / Epic:** GROK-LOCAL-MIGRATE-001
**Priority:** P1 — Architecture / Capability Expansion
**Depends on:** Card 03 (xAI Client Wrapper), Card 13 (Centralized Spicy Mode Config)
**Blocks:** Nothing (existing pipeline continues to work unchanged)
**Estimated Effort:** Large (10–14 engineering days across 6 phases)

---

## Goal

Introduce an object-oriented **Backend Provider** abstraction layer that decouples every pipeline step from the xAI Grok API, enabling per-step configuration of any model backend (Grok cloud, local ComfyUI, Ollama, or future providers). Then implement ComfyUI and Ollama as concrete providers, giving the pipeline full local/uncensored capability while retaining the option to mix cloud and local backends freely.

## Background

The current pipeline is tightly coupled to xAI's Grok API family — model constants live in `client.py`, SDK calls are embedded directly in every task module, and the API's content moderation limits NSFW generation. Moving to a local stack (ComfyUI for image/video, Ollama for LLM/vision) removes moderation constraints, eliminates per-run API costs, and enables LoRA/IP-Adapter-based character locking.

However, a hard cutover is risky and unnecessary. The correct approach is a **provider abstraction** that lets each pipeline step declare *what* it needs (generate an image, check consistency, produce structured text) while configuration determines *how* (which backend, which model, which parameters). This enables:

- Pure Grok runs (current behavior, zero changes)
- Pure local runs (ComfyUI + Ollama, no cloud calls)
- Hybrid runs (e.g., Ollama for ideation, ComfyUI for images, Grok for video)
- Easy addition of future backends (Replicate, RunPod serverless, etc.)

## Motivation

- **Uncensored generation**: Local models have no content moderation gateway
- **Cost elimination**: ~$3.80/run cloud cost drops to electricity + GPU amortization
- **Character control**: LoRA fine-tuning and IP-Adapter give tighter consistency than prompt-only approaches
- **Offline capability**: Full pipeline runs without internet
- **Vendor independence**: Not locked to any single API provider
- **Experimentation**: Swap models per-step without code changes — test Flux vs Pony vs SDXL for images, Wan2.1 vs SVD for video

## Architecture

### Design Patterns

| Pattern | Where | Purpose |
|---|---|---|
| **Strategy** | `providers/` | Each capability (image gen, video gen, LLM, vision) is an abstract interface with swappable implementations |
| **Abstract Factory** | `ProviderFactory` | Creates the correct provider implementation from config |
| **Registry** | `ProviderRegistry` | Maps string identifiers to provider classes for config-driven instantiation |
| **Adapter** | Each concrete provider | Wraps vendor-specific APIs (xAI SDK, ComfyUI HTTP, Ollama HTTP) behind uniform interfaces |
| **Composition** | `BackendConfig` | Pipeline steps compose capabilities rather than inheriting from a monolithic client |

### Capability Interfaces

The pipeline requires exactly **four capabilities**. Each is an abstract base class:

```python
class ImageProvider(ABC):
    """Generates and edits images."""
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> GeneratedImage: ...
    @abstractmethod
    async def edit(self, images: list[str], prompt: str, **kwargs) -> GeneratedImage: ...
    @abstractmethod
    async def stylize(self, source: str, prompt: str, **kwargs) -> GeneratedImage: ...

class VideoProvider(ABC):
    """Generates video from images and edits existing video."""
    @abstractmethod
    async def generate(self, image: str, prompt: str, duration: int, **kwargs) -> GeneratedVideo: ...
    @abstractmethod
    async def edit(self, video: str, prompt: str, **kwargs) -> GeneratedVideo: ...

class LLMProvider(ABC):
    """Text generation with optional structured output."""
    @abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> str: ...
    @abstractmethod
    async def parse(self, messages: list[dict], response_model: type[T], **kwargs) -> T: ...

class VisionProvider(ABC):
    """Analyzes images/frames and returns structured assessments."""
    @abstractmethod
    async def analyze(self, image: str, prompt: str, **kwargs) -> str: ...
    @abstractmethod
    async def check_consistency(self, image: str, references: list[str], prompt: str, **kwargs) -> ConsistencyScore: ...
```

### Provider Implementations

```
providers/
├── __init__.py              # ProviderRegistry + ProviderFactory
├── base.py                  # ABC definitions + GeneratedImage/GeneratedVideo types
├── grok/
│   ├── __init__.py
│   ├── image.py             # GrokImageProvider  (xai_sdk wrapper)
│   ├── video.py             # GrokVideoProvider  (xai_sdk wrapper)
│   ├── llm.py               # GrokLLMProvider    (xai_sdk chat + parse)
│   └── vision.py            # GrokVisionProvider (xai_sdk vision)
├── comfyui/
│   ├── __init__.py
│   ├── client.py            # ComfyUI HTTP API client (queue, poll, download)
│   ├── workflows.py         # Workflow JSON template loader + parameter injection
│   ├── image.py             # ComfyUIImageProvider  (Flux/Pony workflows)
│   └── video.py             # ComfyUIVideoProvider  (Wan2.1/SVD workflows)
├── ollama/
│   ├── __init__.py
│   ├── llm.py               # OllamaLLMProvider    (structured output via JSON mode)
│   └── vision.py            # OllamaVisionProvider (LLaVA/multimodal models)
└── workflows/               # ComfyUI workflow JSON templates
    ├── character_sheet.json
    ├── keyframe_compose.json
    ├── video_generate.json
    └── video_correct.json
```

### Pipeline Step → Provider Mapping

Each pipeline step declares which capability it needs. Configuration determines which provider fulfills it:

| Pipeline Step | Capability Used | Default (Grok) | Local Alternative |
|---|---|---|---|
| Step 0: Reference Description | `VisionProvider` | `grok-4-1-fast-reasoning` | Ollama LLaVA / MiniCPM-V |
| Step 1: Ideation | `LLMProvider.parse()` | `grok-4-1-fast-non-reasoning` | Ollama Mistral-Nemo / Llama 3.1 |
| Step 2: Character Sheets | `ImageProvider.generate/stylize()` + `VisionProvider` | `grok-imagine-image` + vision | ComfyUI Flux/Pony + Ollama CLIP |
| Step 3: Keyframes | `ImageProvider.edit()` + `VisionProvider` | `grok-imagine-image` + vision | ComfyUI IP-Adapter + ControlNet |
| Step 4: Script Compilation | (none — pure Python) | — | — |
| Step 5: Video Generation | `VideoProvider.generate/edit()` + `VisionProvider` | `grok-imagine-video` + vision | ComfyUI Wan2.1/SVD + Ollama |
| Step 6: Assembly | (none — FFmpeg) | — | — |
| Moderation Reword | `LLMProvider.complete()` | `grok-4-1-fast-non-reasoning` | Ollama (or skip — no moderation locally) |

### Configuration Schema

Backend selection is driven by a new `backends` section in `video.json` (or a separate `backends.json`):

```json
{
  "backends": {
    "image": {
      "provider": "comfyui",
      "model": "flux-dev",
      "params": {
        "steps": 30,
        "cfg_scale": 7.0,
        "sampler": "euler_ancestral",
        "scheduler": "normal",
        "width": 1280,
        "height": 720,
        "ip_adapter_weight": 0.85
      }
    },
    "video": {
      "provider": "comfyui",
      "model": "wan2.1",
      "params": {
        "frames": 81,
        "fps": 16,
        "steps": 30,
        "cfg_scale": 6.0,
        "use_first_last_frame": true
      }
    },
    "llm": {
      "provider": "ollama",
      "model": "mistral-nemo:12b-instruct",
      "params": {
        "temperature": 0.7,
        "num_ctx": 8192
      }
    },
    "vision": {
      "provider": "ollama",
      "model": "llava:13b",
      "params": {
        "temperature": 0.2
      }
    },
    "comfyui_url": "http://127.0.0.1:8188",
    "ollama_url": "http://127.0.0.1:11434"
  }
}
```

When `backends` is absent, the pipeline uses Grok providers (current behavior, fully backward compatible).

### Provider Registry & Factory

```python
class ProviderRegistry:
    """Maps provider names to implementation classes."""
    _image: dict[str, type[ImageProvider]] = {}
    _video: dict[str, type[VideoProvider]] = {}
    _llm: dict[str, type[LLMProvider]] = {}
    _vision: dict[str, type[VisionProvider]] = {}

    @classmethod
    def register_image(cls, name: str, provider_cls: type[ImageProvider]) -> None: ...
    # ... register_video, register_llm, register_vision

    @classmethod
    def get_image(cls, name: str) -> type[ImageProvider]: ...
    # ... get_video, get_llm, get_vision


class ProviderFactory:
    """Creates provider instances from BackendConfig."""
    def __init__(self, config: BackendConfig): ...

    def image(self) -> ImageProvider: ...
    def video(self) -> VideoProvider: ...
    def llm(self) -> LLMProvider: ...
    def vision(self) -> VisionProvider: ...
```

Auto-registration via decorator:

```python
@ProviderRegistry.register("comfyui", capability="image")
class ComfyUIImageProvider(ImageProvider):
    ...
```

### Return Types

Uniform return types replace raw URLs/paths scattered across tasks:

```python
@dataclass
class GeneratedImage:
    local_path: Path          # Already downloaded / saved locally
    width: int
    height: int
    provider: str             # "grok", "comfyui", etc.
    model: str                # "grok-imagine-image", "flux-dev", etc.
    metadata: dict[str, Any]  # Provider-specific info (seed, workflow_id, etc.)

@dataclass
class GeneratedVideo:
    local_path: Path
    duration: float
    fps: int
    first_frame_path: Path
    last_frame_path: Path
    provider: str
    model: str
    metadata: dict[str, Any]
```

---

## Deliverables by Phase

### Phase 0: Environment & Prerequisites (no code changes)

**Goal**: Validate local hardware and install ComfyUI + Ollama.

- [ ] Install ComfyUI (portable or git clone) and verify `python main.py` starts the server
- [ ] Install essential custom nodes via ComfyUI Manager:
  - ComfyUI-Impact-Pack
  - IPAdapter_plus
  - ControlNet (OpenPose/Depth)
  - ComfyUI-VideoHelperSuite
  - ComfyUI-Wan (Wan2.1/2.2 support)
- [ ] Download core models:
  - Image: Flux.1-dev or Flux.2-klein + Pony Diffusion XL (for NSFW strength)
  - Video: Wan2.1 or Wan2.2 (first-last-frame workflow support)
  - Fallback: Stable Video Diffusion XT
- [ ] Install Ollama and pull models:
  - `ollama pull mistral-nemo:12b-instruct` (structured output)
  - `ollama pull llava:13b` (vision/consistency checks)
- [ ] Hardware validation: generate test image in ComfyUI (requires ~12-16 GB VRAM)
- [ ] Keep existing Python environment unchanged — providers will call these services via HTTP

### Phase 1: Provider Abstraction Layer

**Files created:**

```
src/grok_spicy/providers/
├── __init__.py          # ProviderRegistry, ProviderFactory, auto-registration
├── base.py              # ABCs (ImageProvider, VideoProvider, LLMProvider, VisionProvider)
│                        # + dataclasses (GeneratedImage, GeneratedVideo)
└── grok/
    ├── __init__.py      # Auto-registers all Grok providers
    ├── image.py         # GrokImageProvider — wraps existing grok-imagine-image calls
    ├── video.py         # GrokVideoProvider — wraps existing grok-imagine-video calls
    ├── llm.py           # GrokLLMProvider — wraps chat.complete + chat.parse
    └── vision.py        # GrokVisionProvider — wraps vision checks
```

**Files modified:**

| File | Change |
|---|---|
| `schemas.py` | Add `BackendConfig`, `ProviderConfig` Pydantic models |
| `config.py` | Parse `backends` section from `video.json` |
| `client.py` | Extract Grok-specific logic into `providers/grok/`, keep shared utils (`download`, `extract_frame`, `to_base64`) |

**Key rule**: After this phase, running without a `backends` config must produce *identical* behavior to the current pipeline. The Grok providers are the default — zero regression.

**Deliverables:**

- [ ] Four abstract base classes in `providers/base.py` with full type annotations
- [ ] `GeneratedImage` and `GeneratedVideo` dataclasses with `local_path`, `provider`, `model`, `metadata`
- [ ] `ProviderRegistry` with decorator-based registration
- [ ] `ProviderFactory` that reads `BackendConfig` and instantiates correct providers
- [ ] All four Grok provider implementations passing existing behavior through the new interfaces
- [ ] `BackendConfig` Pydantic model in `schemas.py`
- [ ] `config.py` loads `backends` section (defaults to all-Grok when absent)
- [ ] Shared utilities remain in `client.py` (not provider-specific)
- [ ] Existing tests pass unchanged

### Phase 2: Refactor Task Modules to Use Providers

**Files modified:**

| File | Change |
|---|---|
| `tasks/ideation.py` | Accept `LLMProvider` instead of calling `xai_sdk` directly |
| `tasks/describe_ref.py` | Accept `VisionProvider` instead of calling `xai_sdk` directly |
| `tasks/characters.py` | Accept `ImageProvider` + `VisionProvider` |
| `tasks/keyframes.py` | Accept `ImageProvider` + `VisionProvider` |
| `tasks/video.py` | Accept `VideoProvider` + `VisionProvider` |
| `pipeline.py` | Create `ProviderFactory` once at flow start, pass providers to each task |

**Refactor approach** — each task function gains a provider parameter:

```python
# Before
@task
def plan_story(concept: str, config: PipelineConfig, ...) -> StoryPlan:
    client = get_client()
    result = client.chat.parse(...)

# After
@task
def plan_story(concept: str, config: PipelineConfig, llm: LLMProvider, ...) -> StoryPlan:
    result = llm.parse(messages, response_model=StoryPlan)
```

**Deliverables:**

- [ ] All six task modules refactored to accept provider interfaces
- [ ] `pipeline.py` creates `ProviderFactory` from config and passes providers to tasks
- [ ] Moderation retry logic moved into `GrokImageProvider` / `GrokVideoProvider` (not applicable to local providers)
- [ ] Dry-run mode continues to work (providers are not called in dry-run)
- [ ] Full pipeline runs identically with Grok providers (regression test)

### Phase 3: Ollama Providers (LLM + Vision)

**Files created:**

```
src/grok_spicy/providers/ollama/
├── __init__.py
├── llm.py               # OllamaLLMProvider
└── vision.py            # OllamaVisionProvider
```

**OllamaLLMProvider:**

- HTTP client to `http://localhost:11434/api/chat` (configurable URL)
- `complete()`: standard chat completion
- `parse()`: uses Ollama's JSON mode (`format: "json"`) + Pydantic validation
  - Sends schema as part of system prompt for structured output
  - Validates response against `response_model`, retries once on parse failure
- Supports `temperature`, `num_ctx`, `top_p` via provider params

**OllamaVisionProvider:**

- Uses multimodal models (LLaVA, MiniCPM-V) via same Ollama API with base64 images
- `analyze()`: sends image + prompt, returns text description
- `check_consistency()`: compares generated image against references
  - Prompt asks model to score consistency 0.0-1.0 and list issues
  - Parses response into `ConsistencyScore`
  - Falls back to CLIP-based scoring if available

**Deliverables:**

- [ ] `OllamaLLMProvider` generates `StoryPlan` via JSON mode with quality comparable to Grok
- [ ] `OllamaVisionProvider` produces `ConsistencyScore` from image comparison
- [ ] Both providers handle connection errors gracefully (clear error message if Ollama not running)
- [ ] Test: run `--dry-run` with `"llm": {"provider": "ollama"}` config — verify prompts are correct
- [ ] Test: run Step 1 (ideation) end-to-end with Ollama, compare output quality

### Phase 4: ComfyUI Providers (Image + Video)

**Files created:**

```
src/grok_spicy/providers/comfyui/
├── __init__.py
├── client.py             # ComfyUI HTTP client (queue workflow, poll status, download output)
├── workflows.py          # Load workflow JSON templates, inject parameters
├── image.py              # ComfyUIImageProvider
└── video.py              # ComfyUIVideoProvider

src/grok_spicy/providers/workflows/
├── character_sheet.json       # Flux/Pony text-to-image for character portraits
├── character_stylize.json     # IP-Adapter/InstantID from reference photo
├── keyframe_compose.json      # Multi-reference IP-Adapter + ControlNet composition
├── video_generate.json        # Wan2.1 image-to-video (first-last-frame)
└── video_correct.json         # Wan2.1 video edit for drift correction
```

**ComfyUI HTTP Client (`comfyui/client.py`):**

```python
class ComfyUIClient:
    """HTTP client for ComfyUI's API."""
    def __init__(self, base_url: str = "http://127.0.0.1:8188"): ...

    def queue_workflow(self, workflow: dict, client_id: str | None = None) -> str:
        """POST /prompt — queue a workflow, return prompt_id."""
        ...

    def poll_until_complete(self, prompt_id: str, timeout: int = 300) -> dict:
        """GET /history/{prompt_id} — poll until execution completes."""
        ...

    def get_output_path(self, prompt_id: str, node_id: str) -> Path:
        """Extract output file path from completed execution history."""
        ...

    def download_output(self, prompt_id: str, node_id: str, dest: Path) -> Path:
        """GET /view — download generated image/video to local path."""
        ...
```

**Workflow Template System (`comfyui/workflows.py`):**

```python
class WorkflowTemplate:
    """Loads a ComfyUI workflow JSON and injects runtime parameters."""
    def __init__(self, template_path: Path): ...

    def render(self, **params) -> dict:
        """Replace placeholder values in workflow nodes with runtime params.

        Params map to specific node inputs:
        - prompt: str → KSampler positive prompt text
        - negative_prompt: str → KSampler negative prompt text
        - seed: int → KSampler seed (-1 for random)
        - steps: int → KSampler steps
        - cfg_scale: float → KSampler cfg
        - width/height: int → EmptyLatentImage dimensions
        - image_path: str → LoadImage file path
        - ip_adapter_weight: float → IPAdapter weight
        - controlnet_strength: float → ControlNet strength
        """
        ...
```

**ComfyUIImageProvider:**

- `generate()`: loads `character_sheet.json` template, injects prompt + params, queues workflow, polls, downloads result
- `edit()`: loads `keyframe_compose.json`, attaches reference images via IP-Adapter nodes + optional ControlNet for pose
- `stylize()`: loads `character_stylize.json`, uses IP-Adapter FaceID or InstantID with source image
- IP-Adapter weight configurable per call (default from config, override per scene)
- Automatic seed tracking in `GeneratedImage.metadata` for reproducibility

**ComfyUIVideoProvider:**

- `generate()`: loads `video_generate.json` (Wan2.1 first-last-frame workflow), injects start image + motion prompt
- `edit()`: loads `video_correct.json`, feeds existing video + correction prompt for drift fix
- Extracts first/last frames via VideoHelperSuite nodes (or falls back to FFmpeg `extract_frame`)
- Duration control via frame count (`frames = duration_seconds * fps`)
- Fallback: if Wan2.1 unavailable, degrade to SVD-XT (shorter clips) + RIFE interpolation

**Deliverables:**

- [ ] `ComfyUIClient` connects, queues workflows, polls, downloads outputs
- [ ] `WorkflowTemplate` loads JSON templates and injects params without corrupting workflow structure
- [ ] All five workflow templates created and tested manually in ComfyUI first
- [ ] `ComfyUIImageProvider.generate()` produces character portraits from text prompts
- [ ] `ComfyUIImageProvider.edit()` composes multi-character scenes via IP-Adapter
- [ ] `ComfyUIImageProvider.stylize()` transforms reference photos into art style
- [ ] `ComfyUIVideoProvider.generate()` produces video clips from keyframe images
- [ ] `ComfyUIVideoProvider.edit()` corrects drift in generated clips
- [ ] Frame extraction works (VideoHelperSuite or FFmpeg fallback)
- [ ] Connection error handling: clear message if ComfyUI not running
- [ ] Test: generate 1 character sheet + 2 keyframes + 1 video clip locally

### Phase 5: Pipeline Integration & Hybrid Mode

**Files modified:**

| File | Change |
|---|---|
| `pipeline.py` | Hybrid provider routing — different providers per step |
| `__main__.py` | Add `--backend` CLI flag, backend-specific help text |
| `config.py` | Validate backend config, warn on missing local services |
| `video.json` | Add example `backends` section |

**CLI changes:**

```
--backend local      # Shorthand: all ComfyUI + Ollama
--backend grok       # Shorthand: all Grok (current default)
--backend config     # Use per-step config from video.json backends section
```

**Hybrid example** — Ollama for cheap/fast ideation, ComfyUI for uncensored images, Grok for video (better quality):

```json
{
  "backends": {
    "llm": { "provider": "ollama", "model": "mistral-nemo:12b-instruct" },
    "vision": { "provider": "ollama", "model": "llava:13b" },
    "image": { "provider": "comfyui", "model": "flux-dev" },
    "video": { "provider": "grok", "model": "grok-imagine-video" }
  }
}
```

**Moderation bypass**: When provider is not `grok`, skip moderation retry logic entirely (local models have no moderation). The `ImageProvider.generate()` contract doesn't include moderation — that's a Grok adapter concern.

**Deliverables:**

- [ ] `--backend` CLI flag works with `local`, `grok`, `config` presets
- [ ] Hybrid config routes different capabilities to different providers
- [ ] Pipeline runs end-to-end with pure local providers (no cloud calls)
- [ ] Pipeline runs end-to-end with mixed providers
- [ ] Grok-only mode (no `backends` config) behaves identically to pre-migration
- [ ] `--dry-run` works with all backend configurations
- [ ] Observer/dashboard works unchanged regardless of backend

### Phase 6: Testing, Polish & Documentation

**Deliverables:**

- [ ] Unit tests for `ProviderRegistry`, `ProviderFactory`
- [ ] Unit tests for `WorkflowTemplate.render()` param injection
- [ ] Integration test: Grok providers pass all existing test cases
- [ ] Integration test: Ollama providers produce valid `StoryPlan` and `ConsistencyScore`
- [ ] Integration test: ComfyUI providers generate images and video (requires running ComfyUI)
- [ ] End-to-end test: full pipeline with local-only config → `final_video.mp4`
- [ ] End-to-end test: hybrid config (mix of providers) → `final_video.mp4`
- [ ] Example configs in `examples/`:
  - `backends-local.json` — all local (ComfyUI + Ollama)
  - `backends-hybrid.json` — mixed cloud + local
  - `backends-grok.json` — explicit all-Grok (reference)
- [ ] Update `CLAUDE.md` with new architecture, provider docs, backend config schema

---

## Updated Project Structure

```
src/grok_spicy/
├── providers/
│   ├── __init__.py              # ProviderRegistry, ProviderFactory
│   ├── base.py                  # ABCs + GeneratedImage/GeneratedVideo
│   ├── grok/
│   │   ├── __init__.py
│   │   ├── image.py             # GrokImageProvider
│   │   ├── video.py             # GrokVideoProvider
│   │   ├── llm.py               # GrokLLMProvider
│   │   └── vision.py            # GrokVisionProvider
│   ├── comfyui/
│   │   ├── __init__.py
│   │   ├── client.py            # ComfyUI HTTP API client
│   │   ├── workflows.py         # Workflow template engine
│   │   ├── image.py             # ComfyUIImageProvider
│   │   └── video.py             # ComfyUIVideoProvider
│   ├── ollama/
│   │   ├── __init__.py
│   │   ├── llm.py               # OllamaLLMProvider
│   │   └── vision.py            # OllamaVisionProvider
│   └── workflows/               # ComfyUI workflow JSON templates
│       ├── character_sheet.json
│       ├── character_stylize.json
│       ├── keyframe_compose.json
│       ├── video_generate.json
│       └── video_correct.json
├── tasks/                       # Unchanged structure, updated to accept providers
│   ├── ideation.py              # Uses LLMProvider
│   ├── describe_ref.py          # Uses VisionProvider
│   ├── characters.py            # Uses ImageProvider + VisionProvider
│   ├── keyframes.py             # Uses ImageProvider + VisionProvider
│   ├── video.py                 # Uses VideoProvider + VisionProvider
│   └── assembly.py              # Unchanged (FFmpeg only)
├── schemas.py                   # + BackendConfig, ProviderConfig
├── config.py                    # + backends section parsing
├── client.py                    # Shared utils only (download, extract_frame, to_base64)
├── pipeline.py                  # ProviderFactory creation + provider injection
└── __main__.py                  # + --backend flag
```

## Pydantic Models

```python
class ProviderConfig(BaseModel):
    """Configuration for a single provider capability."""
    provider: str                          # "grok", "comfyui", "ollama"
    model: str                             # Provider-specific model identifier
    params: dict[str, Any] = {}            # Provider-specific parameters

class BackendConfig(BaseModel):
    """Per-capability backend selection."""
    image: ProviderConfig = ProviderConfig(provider="grok", model="grok-imagine-image")
    video: ProviderConfig = ProviderConfig(provider="grok", model="grok-imagine-video")
    llm: ProviderConfig = ProviderConfig(provider="grok", model="grok-4-1-fast-non-reasoning")
    vision: ProviderConfig = ProviderConfig(provider="grok", model="grok-4-1-fast-reasoning")
    comfyui_url: str = "http://127.0.0.1:8188"
    ollama_url: str = "http://127.0.0.1:11434"
```

## What Changes

| Area | Before | After |
|---|---|---|
| Model selection | Hardcoded constants in `client.py` | Config-driven per capability via `BackendConfig` |
| API calls in tasks | Direct `xai_sdk` calls | Provider interface method calls |
| Image generation | `grok-imagine-image` only | Any registered `ImageProvider` |
| Video generation | `grok-imagine-video` only | Any registered `VideoProvider` |
| LLM / structured output | `grok-4-1-fast-non-reasoning` only | Any registered `LLMProvider` |
| Vision / consistency | `grok-4-1-fast-reasoning` only | Any registered `VisionProvider` |
| Moderation retry | Applied to all image/video calls | Only in `GrokImageProvider` / `GrokVideoProvider` |
| `client.py` | Monolithic SDK wrapper + utils | Shared utils only; SDK logic moved to `providers/grok/` |

## What Does NOT Change

- **Pipeline step order** — same 7-step flow (0-6)
- **Pydantic contracts** — `StoryPlan`, `CharacterAsset`, `KeyframeAsset`, `VideoAsset`, `PipelineState` unchanged
- **Observer pattern** — `on_*()` hooks fire identically regardless of backend
- **Prompt construction** — `prompts.py` and `prompt_builder.py` untouched (prompts are backend-agnostic)
- **FFmpeg assembly** — Step 6 has no provider dependency
- **Script compilation** — Step 4 is pure Python
- **Dry-run mode** — works with any backend config (providers are not called)
- **Web dashboard** — no changes to `web.py`, `db.py`, `events.py`, templates
- **Spicy mode config** — `video.json` spicy section and `--spicy` flag work as before
- **`--ref` flag** — reference image handling unchanged
- **Frame chaining** — `prev_url` / last-frame extraction works via `GeneratedVideo.last_frame_path`

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| ComfyUI workflow fragility | Workflow JSONs break on ComfyUI updates | Pin ComfyUI version, validate workflows on startup |
| Ollama structured output quality | JSON mode may produce invalid schemas | Pydantic validation + 1 retry with error feedback in prompt |
| VRAM exhaustion | Large models OOM on consumer GPUs | Configurable model sizes, clear error messages, RunPod fallback |
| Provider interface too narrow | New backends need capabilities not in ABCs | Design ABCs with `**kwargs` escape hatch, extend interface when concrete need arises |
| Regression in Grok mode | Refactor breaks existing cloud pipeline | Phase 1 deliverable: all existing tests pass with Grok providers before any new providers are added |
| Workflow template complexity | ComfyUI workflows are large JSON blobs | `WorkflowTemplate` only patches specific node inputs, doesn't rewrite structure |

## Milestones

| Milestone | Phase | Validation |
|---|---|---|
| **M0: Abstraction complete** | Phase 1-2 | Pipeline runs identically with Grok providers via new interfaces |
| **M1: Local LLM working** | Phase 3 | Ideation + vision checks run via Ollama, no cloud calls for text |
| **M2: Local image gen** | Phase 4 | Character sheets + keyframes generated via ComfyUI |
| **M3: Local video gen** | Phase 4 | 30-60s chained video with no cloud calls |
| **M4: Full local pipeline** | Phase 5 | End-to-end `final_video.mp4` generated entirely locally |
| **M5: Hybrid mode** | Phase 5 | Mixed provider config produces valid output |
| **M6: Production ready** | Phase 6 | Tests pass, docs updated, example configs shipped |

## Acceptance Criteria

- [ ] Four abstract provider interfaces (`ImageProvider`, `VideoProvider`, `LLMProvider`, `VisionProvider`) defined with full type annotations
- [ ] `ProviderRegistry` supports decorator-based registration of new providers
- [ ] `ProviderFactory` creates correct provider instances from `BackendConfig`
- [ ] Grok providers wrap existing xAI SDK logic — zero behavioral regression
- [ ] Ollama providers produce valid `StoryPlan` (JSON mode) and `ConsistencyScore`
- [ ] ComfyUI providers generate images and video via HTTP API + workflow templates
- [ ] `BackendConfig` Pydantic model validates provider/model/params per capability
- [ ] `video.json` `backends` section is optional — absent means all-Grok (backward compatible)
- [ ] `--backend local|grok|config` CLI flag selects provider preset
- [ ] Hybrid config (different providers per capability) runs end-to-end
- [ ] Pipeline observer calls fire identically regardless of backend
- [ ] Dry-run mode works with all backend configurations
- [ ] Moderation retry logic only applies to Grok providers
- [ ] Shared utilities (`download`, `extract_frame`, `to_base64`) remain in `client.py`
- [ ] All prompt construction (`prompts.py`, `prompt_builder.py`) is backend-agnostic
- [ ] Example backend configs shipped in `examples/`
- [ ] Existing tests pass with Grok providers after refactor
