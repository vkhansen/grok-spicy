# Feature 12: SQLite Database + FastAPI + Live Dashboard

**Priority:** P2 — Polish
**Depends on:** Card 02 (Data Models), Card 10 (Pipeline flow), Card 11 (CLI entry point)
**Blocks:** Nothing

---

## Goal

Add a web-based dashboard that lets the user watch the pipeline run in real time and browse past runs. Today everything lives in flat files under `output/` with a single `state.json` that's overwritten each run. There's no history, no way to view assets as they're generated, and no live progress.

This card delivers three layers:

1. **SQLite database** — persistent structured storage for every run, replacing `state.json` as the source of truth
2. **FastAPI server** — serves a JSON API, an SSE event stream, and HTML pages
3. **htmx + SSE dashboard** — zero-JavaScript live-reloading frontend that updates as assets are generated

The design uses an **observer pattern** so the existing CLI-only pipeline is untouched. A `NullObserver` (default) drops all events; a `WebObserver` writes to SQLite and pushes SSE events.

## Architecture Overview

```
                     ┌────────────────────────────────┐
                     │     video_pipeline() flow       │
                     │                                 │
                     │  plan_story ──► observer.on_plan│
                     │  gen_char   ──► observer.on_char│
                     │  keyframe   ──► observer.on_kf  │
                     │  ...        ──► observer.on_*   │
                     └──────────────┬─────────────────┘
                                    │ PipelineObserver
                        ┌───────────┴───────────┐
                        ▼                       ▼
                  NullObserver            WebObserver
                  (no-op, CLI)         ┌─────────────┐
                                       │  SQLite DB   │
                                       │  EventBus    │
                                       └──────┬──────┘
                                              │ SSE
                                       ┌──────▼──────┐
                                       │  FastAPI app │
                                       │  /api/*      │
                                       │  /sse        │
                                       │  / (HTML)    │
                                       └──────┬──────┘
                                              │
                                       ┌──────▼──────┐
                                       │   Browser    │
                                       │ htmx + SSE   │
                                       └─────────────┘
```

---

## Deliverables

### 1. SQLite Schema — `src/grok_spicy/db.py`

Six tables mirroring the Pydantic models in `schemas.py`, plus a top-level `runs` table:

```sql
CREATE TABLE runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    concept         TEXT NOT NULL,
    title           TEXT,
    style           TEXT,
    aspect_ratio    TEXT,
    color_palette   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    script_path     TEXT,
    final_video_path TEXT,
    started_at      TEXT NOT NULL,  -- ISO-8601
    completed_at    TEXT
);

CREATE TABLE characters (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER NOT NULL REFERENCES runs(id),
    name               TEXT NOT NULL,
    role               TEXT NOT NULL,
    visual_description TEXT NOT NULL,
    personality_cues   TEXT NOT NULL  -- JSON array
);

CREATE TABLE scenes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    scene_id            INTEGER NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    characters_present  TEXT NOT NULL,  -- JSON array
    setting             TEXT NOT NULL,
    camera              TEXT NOT NULL,
    mood                TEXT NOT NULL,
    action              TEXT NOT NULL,
    duration_seconds    INTEGER NOT NULL,
    transition          TEXT NOT NULL DEFAULT 'cut'
);

CREATE TABLE character_assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    name                TEXT NOT NULL,
    portrait_url        TEXT NOT NULL,
    portrait_path       TEXT NOT NULL,
    visual_description  TEXT NOT NULL,
    consistency_score   REAL NOT NULL,
    generation_attempts INTEGER NOT NULL
);

CREATE TABLE keyframe_assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    scene_id            INTEGER NOT NULL,
    keyframe_url        TEXT NOT NULL,
    keyframe_path       TEXT NOT NULL,
    consistency_score   REAL NOT NULL,
    generation_attempts INTEGER NOT NULL,
    edit_passes         INTEGER NOT NULL,
    video_prompt        TEXT NOT NULL
);

CREATE TABLE video_assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    scene_id            INTEGER NOT NULL,
    video_url           TEXT NOT NULL,
    video_path          TEXT NOT NULL,
    duration            REAL NOT NULL,
    first_frame_path    TEXT NOT NULL,
    last_frame_path     TEXT NOT NULL,
    consistency_score   REAL NOT NULL,
    correction_passes   INTEGER NOT NULL
);
```

**Status enum values for `runs.status`:**

| Value | Meaning |
|---|---|
| `pending` | Run created, pipeline not started |
| `ideation` | Step 1 in progress |
| `characters` | Step 2 in progress |
| `keyframes` | Step 3 in progress |
| `script` | Step 4 in progress |
| `videos` | Step 5 in progress |
| `assembly` | Step 6 in progress |
| `complete` | All done, `final_video_path` populated |
| `failed` | Pipeline errored out |

**Implementation notes:**

- Use `sqlite3` from the stdlib — no ORM, no SQLAlchemy
- Single `init_db(db_path: str) -> sqlite3.Connection` function that creates tables if they don't exist
- Default DB path: `output/grok_spicy.db` (colocated with assets)
- All JSON array columns (`personality_cues`, `characters_present`) stored via `json.dumps()` / `json.loads()`
- WAL mode enabled for concurrent reads (dashboard) while the pipeline writes

**Key functions:**

| Function | Signature | Purpose |
|---|---|---|
| `init_db` | `(db_path: str) -> sqlite3.Connection` | Create tables, enable WAL mode |
| `insert_run` | `(conn, concept: str) -> int` | Insert new run row, return `run_id` |
| `update_run` | `(conn, run_id: int, **fields) -> None` | Partial update on runs table |
| `insert_characters` | `(conn, run_id: int, chars: list[Character]) -> None` | Bulk insert from StoryPlan |
| `insert_scenes` | `(conn, run_id: int, scenes: list[Scene]) -> None` | Bulk insert from StoryPlan |
| `upsert_character_asset` | `(conn, run_id: int, asset: CharacterAsset) -> None` | Insert or replace by (run_id, name) |
| `upsert_keyframe_asset` | `(conn, run_id: int, asset: KeyframeAsset) -> None` | Insert or replace by (run_id, scene_id) |
| `upsert_video_asset` | `(conn, run_id: int, asset: VideoAsset) -> None` | Insert or replace by (run_id, scene_id) |
| `get_run` | `(conn, run_id: int) -> dict` | Full run with nested characters, scenes, assets |
| `list_runs` | `(conn) -> list[dict]` | Summary list for dashboard index |

### 2. Observer Protocol — `src/grok_spicy/observer.py`

A `Protocol` class that the pipeline calls at each step boundary. Two implementations ship by default:

```python
from typing import Protocol, runtime_checkable
from grok_spicy.schemas import (
    StoryPlan, CharacterAsset, KeyframeAsset, VideoAsset
)


@runtime_checkable
class PipelineObserver(Protocol):
    def on_run_start(self, concept: str) -> int:
        """Called when the pipeline begins. Returns a run_id."""
        ...

    def on_plan(self, run_id: int, plan: StoryPlan) -> None:
        """Called after Step 1 ideation completes."""
        ...

    def on_character(self, run_id: int, asset: CharacterAsset) -> None:
        """Called after each character sheet is accepted."""
        ...

    def on_keyframe(self, run_id: int, asset: KeyframeAsset) -> None:
        """Called after each keyframe is accepted."""
        ...

    def on_script(self, run_id: int, script_path: str) -> None:
        """Called after Step 4 script compilation."""
        ...

    def on_video(self, run_id: int, asset: VideoAsset) -> None:
        """Called after each scene video is generated."""
        ...

    def on_complete(self, run_id: int, final_path: str) -> None:
        """Called after Step 6 assembly completes."""
        ...

    def on_error(self, run_id: int, error: str) -> None:
        """Called if the pipeline fails."""
        ...
```

**`NullObserver`** — default, all methods are no-ops. Returns `run_id=0` from `on_run_start`. Used for CLI-only runs. Zero overhead.

**`WebObserver`** — writes to SQLite via `db.py` functions and pushes events to the `EventBus`. Constructed with a `sqlite3.Connection` and an `EventBus` instance.

### Pipeline integration

The `video_pipeline()` flow gains an optional `observer: PipelineObserver = NullObserver()` parameter:

```python
@flow(name="grok-video-pipeline", retries=1,
      retry_delay_seconds=60, log_prints=True)
def video_pipeline(concept: str, observer: PipelineObserver | None = None) -> str:
    if observer is None:
        observer = NullObserver()

    run_id = observer.on_run_start(concept)

    plan = plan_story(concept)
    observer.on_plan(run_id, plan)

    # ... existing logic unchanged ...

    observer.on_complete(run_id, final)
    return final
```

The observer calls are **fire-and-forget** — they never affect pipeline control flow. If the observer raises, catch and log a warning but don't abort the pipeline.

### 3. Event Bus — `src/grok_spicy/events.py`

A thread-safe pub/sub bridge between the synchronous pipeline thread and the async SSE endpoint:

```python
import asyncio
import threading
from dataclasses import dataclass, field


@dataclass
class Event:
    type: str       # "plan", "character", "keyframe", "script", "video", "complete", "error"
    run_id: int
    data: dict      # JSON-serializable payload


class EventBus:
    """Thread-safe event bus bridging sync pipeline → async SSE."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue[Event]:
        """Create a new subscriber queue (called from async SSE endpoint)."""
        q: asyncio.Queue[Event] = asyncio.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        """Remove a subscriber queue."""
        with self._lock:
            self._subscribers.remove(q)

    def publish(self, event: Event) -> None:
        """Push event to all subscribers (called from sync pipeline thread)."""
        with self._lock:
            for q in self._subscribers:
                q.put_nowait(event)
```

**Design decisions:**

- Uses `asyncio.Queue` so the SSE endpoint can `await q.get()` without blocking the event loop
- `publish()` is called from the pipeline thread (sync) — `put_nowait()` is thread-safe on `asyncio.Queue`
- One queue per connected browser tab — cleans up on disconnect via `unsubscribe()`
- No persistence in the bus — historical events are fetched from SQLite on page load; the bus only pushes live deltas

### 4. FastAPI App — `src/grok_spicy/web.py`

A single-file FastAPI application with 6 routes:

| Route | Method | Response | Purpose |
|---|---|---|---|
| `/` | GET | HTML | Dashboard index — list of all runs |
| `/run/{run_id}` | GET | HTML | Single run detail page |
| `/api/runs` | GET | JSON | List all runs (summary) |
| `/api/runs/{run_id}` | GET | JSON | Full run detail with nested assets |
| `/sse/{run_id}` | GET | SSE stream | Live event stream for a specific run |
| `/output/{path:path}` | GET | File | Static file serving for images/videos |

**Implementation outline:**

```python
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader
import json

app = FastAPI(title="Grok Spicy Dashboard")

# Jinja2 templates from src/grok_spicy/templates/
templates = Environment(loader=PackageLoader("grok_spicy", "templates"))

# Serve output/ directory for images and videos
app.mount("/output", StaticFiles(directory="output"), name="output")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    runs = list_runs(get_db())
    template = templates.get_template("index.html")
    return template.render(runs=runs)


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: int):
    run = get_run(get_db(), run_id)
    template = templates.get_template("run.html")
    return template.render(run=run)


@app.get("/api/runs")
async def api_list_runs():
    return list_runs(get_db())


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: int):
    return get_run(get_db(), run_id)


@app.get("/sse/{run_id}")
async def sse_stream(run_id: int):
    queue = event_bus.subscribe()
    async def generate():
        try:
            while True:
                event = await queue.get()
                if event.run_id == run_id:
                    yield f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"
                    if event.type in ("complete", "error"):
                        break
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Startup / shutdown:**

- On startup: `init_db()` to ensure tables exist, create `EventBus` instance
- The `EventBus` and `sqlite3.Connection` are module-level singletons — the FastAPI app and the `WebObserver` share them
- Uvicorn runs in a background thread when `--serve` is used, or as the main process when `--web` is used standalone

### 5. Frontend — Jinja2 + htmx + SSE Templates

Templates live in `src/grok_spicy/templates/`:

```
templates/
├── base.html       # Layout shell, htmx + SSE script tags
├── index.html      # Run list
└── run.html        # Single run detail (live-updating)
```

**`base.html`** — minimal layout:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{% block title %}Grok Spicy{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://unpkg.com/htmx-ext-sse@2.3.0/sse.js"></script>
    <style>
        /* Minimal inline CSS — dark theme, grid layout, no build step */
        :root { --bg: #0f0f0f; --fg: #e0e0e0; --accent: #4f9; --card: #1a1a1a; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: var(--bg); color: var(--fg); padding: 2rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
        .card { background: var(--card); border-radius: 8px; padding: 1rem; }
        .status { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
        .status-complete { background: #1a3a1a; color: #4f9; }
        .status-running { background: #3a3a1a; color: #ff9; }
        .status-failed { background: #3a1a1a; color: #f66; }
        video { width: 100%; border-radius: 4px; }
        img { max-width: 100%; border-radius: 4px; }
        h1, h2, h3 { margin-bottom: 0.5rem; }
        a { color: var(--accent); }
    </style>
</head>
<body>
    {% block content %}{% endblock %}
</body>
</html>
```

**`index.html`** — run list:

```html
{% extends "base.html" %}
{% block title %}Grok Spicy — Runs{% endblock %}
{% block content %}
<h1>Grok Spicy — Pipeline Runs</h1>
<div class="grid">
    {% for run in runs %}
    <a href="/run/{{ run.id }}" class="card" style="text-decoration: none; color: inherit;">
        <h3>{{ run.title or run.concept[:50] }}</h3>
        <span class="status status-{{ 'complete' if run.status == 'complete' else 'running' if run.status not in ('failed', 'complete', 'pending') else run.status }}">
            {{ run.status }}
        </span>
        <p style="margin-top: 0.5rem; font-size: 0.85em; opacity: 0.7;">{{ run.started_at }}</p>
    </a>
    {% endfor %}
</div>
{% endblock %}
```

**`run.html`** — live-updating run detail:

```html
{% extends "base.html" %}
{% block title %}Run #{{ run.id }} — {{ run.title or run.concept[:30] }}{% endblock %}
{% block content %}
<h1>{{ run.title or run.concept }}</h1>
<p><strong>Style:</strong> {{ run.style }}</p>
<p><strong>Status:</strong>
    <span class="status status-{{ 'complete' if run.status == 'complete' else 'running' if run.status not in ('failed', 'complete', 'pending') else run.status }}">
        {{ run.status }}
    </span>
</p>

<!-- SSE live updates — htmx swaps new content into these containers -->
<div hx-ext="sse" sse-connect="/sse/{{ run.id }}">

    <h2>Characters</h2>
    <div class="grid" id="characters"
         sse-swap="character" hx-swap="beforeend">
        {% for c in run.character_assets %}
        <div class="card">
            <img src="/output/{{ c.portrait_path }}" alt="{{ c.name }}">
            <h3>{{ c.name }}</h3>
            <p>Score: {{ "%.0f"|format(c.consistency_score * 100) }}%</p>
        </div>
        {% endfor %}
    </div>

    <h2>Keyframes</h2>
    <div class="grid" id="keyframes"
         sse-swap="keyframe" hx-swap="beforeend">
        {% for kf in run.keyframe_assets %}
        <div class="card">
            <img src="/output/{{ kf.keyframe_path }}" alt="Scene {{ kf.scene_id }}">
            <h3>Scene {{ kf.scene_id }}</h3>
            <p>Score: {{ "%.0f"|format(kf.consistency_score * 100) }}%</p>
        </div>
        {% endfor %}
    </div>

    <h2>Videos</h2>
    <div class="grid" id="videos"
         sse-swap="video" hx-swap="beforeend">
        {% for v in run.video_assets %}
        <div class="card">
            <video src="/output/{{ v.video_path }}" autoplay loop muted playsinline></video>
            <h3>Scene {{ v.scene_id }}</h3>
            <p>Score: {{ "%.0f"|format(v.consistency_score * 100) }}%</p>
        </div>
        {% endfor %}
    </div>

    {% if run.final_video_path %}
    <h2>Final Video</h2>
    <video src="/output/{{ run.final_video_path }}" controls autoplay loop style="max-width: 720px;"></video>
    {% endif %}

    <!-- Status updates replace this span -->
    <div sse-swap="complete" hx-swap="innerHTML" hx-target=".status"></div>

</div>
{% endblock %}
```

**How SSE + htmx live reload works:**

1. Browser connects to `/sse/{run_id}` via `hx-ext="sse"` + `sse-connect`
2. Each `sse-swap="character"` attribute tells htmx: "when an SSE event named `character` arrives, swap the `data` (HTML fragment) into this container"
3. The `WebObserver` pushes events; the SSE endpoint yields them; htmx swaps them in — no custom JavaScript
4. The SSE `data` payload for each event type is a pre-rendered HTML card fragment (rendered server-side by Jinja2), so htmx can directly swap it into the DOM
5. On `complete` or `error`, the SSE stream closes

**Zero npm/build requirement:** htmx and htmx-ext-sse are loaded from CDN `<script>` tags. All CSS is inline in `base.html`. No node_modules, no bundler, no build step.

### 6. CLI Integration — `src/grok_spicy/__main__.py`

Two new flags added to the existing argument parser:

| Flag | Type | Default | Description |
|---|---|---|---|
| `--serve` | flag | `False` | Start the dashboard server alongside the pipeline |
| `--web` | flag | `False` | Start the dashboard server only (browse past runs) |
| `--port` | int | `8420` | Port for the dashboard server |

**Behavior matrix:**

| Command | Pipeline | Server |
|---|---|---|
| `python -m grok_spicy "concept"` | runs | no |
| `python -m grok_spicy "concept" --serve` | runs | starts in background thread |
| `python -m grok_spicy --web` | no | runs as main process |

**`--serve` mode:**

1. Initialize SQLite database
2. Create `EventBus` and `WebObserver`
3. Start Uvicorn in a background `threading.Thread(daemon=True)`
4. Run `video_pipeline(concept, observer=web_observer)`
5. After pipeline completes, print URL and keep server alive until Ctrl+C

**`--web` mode:**

1. Initialize SQLite database
2. Start Uvicorn as the main process (blocking)
3. No pipeline execution — just browse past runs

```python
if args.web:
    import uvicorn
    from grok_spicy.web import app
    from grok_spicy.db import init_db
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
    sys.exit(0)

if args.serve:
    import threading
    import uvicorn
    from grok_spicy.web import app, event_bus
    from grok_spicy.db import init_db
    from grok_spicy.observer import WebObserver

    conn = init_db()
    observer = WebObserver(conn, event_bus)

    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "0.0.0.0", "port": args.port},
        daemon=True
    )
    server_thread.start()
    print(f"Dashboard: http://localhost:{args.port}")

    result = video_pipeline(args.concept, observer=observer)
    print(f"\nDone: {result}")
    print(f"Dashboard still running at http://localhost:{args.port} — Ctrl+C to stop")
    server_thread.join()
else:
    result = video_pipeline(args.concept)
    print(f"\nDone: {result}")
```

---

## New Dependencies

Added to `pyproject.toml` under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
]
```

Install with `pip install -e ".[web]"`. The core pipeline has **zero new dependencies** — SQLite and threading are stdlib. FastAPI/uvicorn/Jinja2 are only imported when `--serve` or `--web` flags are used.

---

## New File Summary

| File | Purpose |
|---|---|
| `src/grok_spicy/db.py` | SQLite schema init, insert/query functions |
| `src/grok_spicy/observer.py` | `PipelineObserver` protocol, `NullObserver`, `WebObserver` |
| `src/grok_spicy/events.py` | Thread-safe `EventBus` for sync→async bridging |
| `src/grok_spicy/web.py` | FastAPI app (routes, SSE endpoint, static files) |
| `src/grok_spicy/templates/base.html` | Layout shell with htmx + dark theme CSS |
| `src/grok_spicy/templates/index.html` | Run list page |
| `src/grok_spicy/templates/run.html` | Live-updating run detail page |
| `docs/features/Feature-plan-frontend.md` | This feature card |

## Modified Files

| File | Change |
|---|---|
| `src/grok_spicy/pipeline.py` | Add optional `observer` parameter, call observer methods at each step boundary |
| `src/grok_spicy/__main__.py` | Add `--serve`, `--web`, `--port` flags |
| `pyproject.toml` | Add `[project.optional-dependencies] web = [...]` |

---

## Acceptance Criteria

- [ ] SQLite schema has tables for runs, characters, scenes, character_assets, keyframe_assets, video_assets
- [ ] All fields from `schemas.py` models are represented in the schema
- [ ] `init_db()` creates tables idempotently (IF NOT EXISTS)
- [ ] WAL mode enabled for concurrent read/write
- [ ] `PipelineObserver` is a Protocol with methods for each pipeline step
- [ ] `NullObserver` is the default — existing CLI-only behavior is unchanged
- [ ] `WebObserver` writes to SQLite and pushes events to `EventBus`
- [ ] Observer errors are caught and logged, never crash the pipeline
- [ ] `EventBus` is thread-safe — sync `publish()` from pipeline thread, async `subscribe()` for SSE
- [ ] FastAPI serves HTML pages at `/` and `/run/{run_id}`
- [ ] JSON API at `/api/runs` and `/api/runs/{run_id}`
- [ ] SSE stream at `/sse/{run_id}` delivers live events
- [ ] Static files served from `/output/` for images and videos
- [ ] htmx live-swaps new character/keyframe/video cards as they're generated
- [ ] Video elements autoplay and loop
- [ ] `--serve` starts server in background thread alongside pipeline
- [ ] `--web` starts server as standalone process
- [ ] No npm, no build step — htmx loaded from CDN, CSS inline
- [ ] FastAPI/uvicorn/Jinja2 only imported when `--serve` or `--web` is used
- [ ] Core pipeline has zero new runtime dependencies
