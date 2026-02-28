"""FastAPI dashboard app — routes, SSE, static files."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, PackageLoader

from grok_spicy.db import (
    get_run,
    init_db,
    insert_reference_image,
    insert_run,
    list_runs,
)
from grok_spicy.events import Event, EventBus

app = FastAPI(title="Grok Spicy Dashboard")

# ─── Globals shared with CLI bootstrap ────────────────────────

event_bus = EventBus()
_conn = None


def get_db():
    """Get or create the shared DB connection."""
    global _conn
    if _conn is None:
        _conn = init_db()
    return _conn


def set_db(conn):
    """Allow CLI to inject a pre-initialized connection."""
    global _conn
    _conn = conn


# ─── Templates ────────────────────────────────────────────────

templates = Environment(
    loader=PackageLoader("grok_spicy", "templates"),
    autoescape=True,
)

# ─── Static files (output/ directory for images/videos) ──────

os.makedirs("output", exist_ok=True)
app.mount("/output", StaticFiles(directory="output"), name="output")


# ─── Health check ─────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


# ─── HTML routes ──────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index():
    runs = list_runs(get_db())
    return templates.get_template("index.html").render(runs=runs)


@app.get("/new", response_class=HTMLResponse)
async def new_run_form():
    return templates.get_template("new_run.html").render()


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: int):
    run = get_run(get_db(), run_id)
    if not run:
        return HTMLResponse("<h1>Run not found</h1>", status_code=404)
    return templates.get_template("run.html").render(run=run)


# ─── JSON API ─────────────────────────────────────────────────


@app.get("/api/runs")
async def api_list_runs():
    return list_runs(get_db())


@app.get("/api/runs/{run_id}")
async def api_get_run(run_id: int) -> dict[str, Any] | None:
    return get_run(get_db(), run_id)


# ─── Create run (with optional reference images) ─────────────


_FILE_NONE = File(None)


@app.post("/api/runs")
async def create_run(
    concept: str = Form(...),
    ref_name_1: str = Form(""),
    ref_image_1: UploadFile | None = _FILE_NONE,
    ref_name_2: str = Form(""),
    ref_image_2: UploadFile | None = _FILE_NONE,
):
    conn = get_db()
    run_id = insert_run(conn, concept)

    # Save uploaded reference images
    ref_map: dict[str, str] = {}
    for name, upload in [(ref_name_1, ref_image_1), (ref_name_2, ref_image_2)]:
        name = name.strip() if name else ""
        if name and upload and upload.filename:
            safe_name = name.replace(" ", "_")
            path = f"output/references/{run_id}_{safe_name}.jpg"
            os.makedirs("output/references", exist_ok=True)
            content = await upload.read()
            with open(path, "wb") as f:
                f.write(content)
            insert_reference_image(conn, run_id, name, upload.filename, path)
            ref_map[name] = path

    # Start pipeline in background thread
    _start_pipeline_thread(concept, run_id, ref_map)

    return RedirectResponse(f"/run/{run_id}", status_code=303)


def _start_pipeline_thread(
    concept: str,
    run_id: int,
    ref_map: dict[str, str],
) -> None:
    """Launch the pipeline in a daemon thread."""
    from grok_spicy.observer import WebObserver

    observer = WebObserver(get_db(), event_bus)

    def _patched_run_start(concept: str) -> int:
        from grok_spicy.db import update_run

        update_run(get_db(), run_id, status="ideation")
        event_bus.publish(
            Event(type="run_start", run_id=run_id, data={"concept": concept})
        )
        return run_id

    observer.on_run_start = _patched_run_start  # type: ignore[assignment]

    def _run():
        from grok_spicy.pipeline import video_pipeline

        character_refs = ref_map if ref_map else None
        video_pipeline(concept, observer=observer, character_refs=character_refs)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ─── SSE stream ──────────────────────────────────────────────


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

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
