"""Unit tests for FastAPI dashboard routes."""

import io
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from grok_spicy.db import (
    init_db,
    insert_characters,
    insert_run,
    insert_scenes,
    update_run,
)
from grok_spicy.events import Event, EventBus
from grok_spicy.web import app, get_db, set_db


@pytest.fixture(autouse=True)
def _setup_db():
    """Provide an in-memory DB for each test."""
    conn = init_db(":memory:")
    set_db(conn)
    yield
    conn.close()
    set_db(None)


@pytest.fixture()
def client():
    return TestClient(app)


# ─── Health check ─────────────────────────────────────────────


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ─── HTML routes ─────────────────────────────────────────────


def test_index_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Grok Spicy" in resp.text


def test_index_with_runs(client):
    conn = get_db()
    insert_run(conn, "Fox meets Owl")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Fox meets Owl" in resp.text


def test_new_run_form(client):
    resp = client.get("/new")
    assert resp.status_code == 200
    assert "concept" in resp.text.lower()


def test_run_detail_not_found(client):
    resp = client.get("/run/999")
    assert resp.status_code == 404


def test_run_detail_found(client):
    conn = get_db()
    run_id = insert_run(conn, "Test concept")
    update_run(conn, run_id, title="Test Title")
    resp = client.get(f"/run/{run_id}")
    assert resp.status_code == 200
    assert "Test Title" in resp.text


# ─── JSON API ────────────────────────────────────────────────


def test_api_list_runs_empty(client):
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_list_runs(client):
    conn = get_db()
    insert_run(conn, "first")
    insert_run(conn, "second")
    resp = client.get("/api/runs")
    data = resp.json()
    assert len(data) == 2
    assert data[0]["concept"] == "second"  # newest first


def test_api_get_run(client):
    conn = get_db()
    run_id = insert_run(conn, "test")
    resp = client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["concept"] == "test"
    assert "characters" in data
    assert "scenes" in data


def test_api_get_run_not_found(client):
    resp = client.get("/api/runs/999")
    assert resp.status_code == 200
    assert resp.json() is None


def test_api_get_run_includes_all_nested(client):
    """Verify the JSON response has all 6 nested arrays."""
    conn = get_db()
    run_id = insert_run(conn, "nested test")
    resp = client.get(f"/api/runs/{run_id}")
    data = resp.json()
    for key in (
        "characters",
        "scenes",
        "reference_images",
        "character_assets",
        "keyframe_assets",
        "video_assets",
    ):
        assert key in data, f"Missing nested key: {key}"
        assert isinstance(data[key], list)


# ─── POST /api/runs (create run) ─────────────────────────────


def _patch_video_config(monkeypatch):
    """Patch load_video_config to return a minimal config with story_plan."""
    from grok_spicy.schemas import (
        Character,
        Scene,
        SpicyMode,
        StoryPlan,
        VideoConfig,
    )

    cfg = VideoConfig(
        spicy_mode=SpicyMode(
            enabled_modifiers=[], intensity="low", global_prefix=""
        ),
        story_plan=StoryPlan(
            title="Test Plan",
            style="cinematic",
            color_palette="warm",
            characters=[
                Character(
                    name="Fox",
                    role="protagonist",
                    visual_description="A " * 40,
                    personality_cues=["brave"],
                )
            ],
            scenes=[
                Scene(
                    scene_id=1,
                    title="Scene 1",
                    description="Fox enters.",
                    characters_present=["Fox"],
                    setting="forest",
                    camera="wide",
                    mood="warm",
                    action="Fox walks",
                    prompt_summary="Fox walks.",
                    duration_seconds=8,
                )
            ],
        ),
    )
    monkeypatch.setattr("grok_spicy.config.load_video_config", lambda *a, **kw: cfg)
    return cfg


def test_create_run_redirects(client, monkeypatch):
    """POST → 303 redirect to /run/{id}."""
    _patch_video_config(monkeypatch)
    resp = client.post(
        "/api/runs",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/run/")


def test_create_run_saves_to_db(client, monkeypatch):
    """POST → run appears in list_runs() with plan title as concept."""
    from grok_spicy.db import list_runs

    _patch_video_config(monkeypatch)
    client.post(
        "/api/runs",
        data={},
        follow_redirects=False,
    )
    runs = list_runs(get_db())
    assert len(runs) == 1
    assert runs[0]["concept"] == "Test Plan"


def test_create_run_with_ref_images(client, monkeypatch):
    """POST with file uploads → reference_images table populated."""
    _patch_video_config(monkeypatch)
    fake_image = io.BytesIO(b"\xff\xd8\xff\xe0fake-jpeg-data")
    resp = client.post(
        "/api/runs",
        data={
            "ref_name_1": "Alex",
            "ref_name_2": "",
        },
        files={"ref_image_1": ("alex.jpg", fake_image, "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    conn = get_db()
    rows = conn.execute("SELECT * FROM reference_images").fetchall()
    assert len(rows) == 1
    assert rows[0]["character_name"] == "Alex"
    assert rows[0]["original_filename"] == "alex.jpg"


# ─── SSE / EventBus unit tests ────────────────────────────────


def test_event_bus_subscribe_and_publish():
    """Verify EventBus delivers events to subscribers."""
    bus = EventBus()
    q = bus.subscribe()
    bus.publish(Event(type="plan", run_id=1, data={"title": "test"}))
    assert not q.empty()
    event = q.get_nowait()
    assert event.type == "plan"
    assert event.run_id == 1


def test_event_bus_unsubscribe():
    """After unsubscribe, no more events delivered."""
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.publish(Event(type="plan", run_id=1, data={}))
    assert q.empty()


def test_event_bus_multiple_subscribers():
    """All subscribers receive the same event."""
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish(Event(type="complete", run_id=1, data={}))
    assert not q1.empty()
    assert not q2.empty()


def test_event_bus_publish_delivers_correct_data():
    """Verify published event data is preserved through the bus."""
    bus = EventBus()
    q = bus.subscribe()
    bus.publish(Event(type="video", run_id=42, data={"scene_id": 3, "path": "/a.mp4"}))
    event = q.get_nowait()
    assert event.type == "video"
    assert event.run_id == 42
    assert event.data["scene_id"] == 3
    assert event.data["path"] == "/a.mp4"


# ─── Run detail with full data ────────────────────────────────


def test_run_detail_with_full_data(client):
    """Insert run + characters + scenes, verify all sections render."""
    from grok_spicy.schemas import Character, Scene

    conn = get_db()
    run_id = insert_run(conn, "Full data test")
    update_run(conn, run_id, title="Full Story", style="cinematic")

    insert_characters(
        conn,
        run_id,
        [
            Character(
                name="Fox",
                role="protagonist",
                visual_description="A red fox with green eyes",
                personality_cues=["curious", "brave"],
            ),
        ],
    )
    insert_scenes(
        conn,
        run_id,
        [
            Scene(
                scene_id=1,
                title="The Meeting",
                description="Fox meets Owl in the forest",
                characters_present=["Fox"],
                setting="enchanted forest",
                camera="wide shot",
                mood="mysterious",
                action="Fox walks slowly",
                prompt_summary="Fox walks slowly through enchanted forest.",
                duration_seconds=6,
                transition="cut",
            ),
        ],
    )

    resp = client.get(f"/run/{run_id}")
    assert resp.status_code == 200
    assert "Full Story" in resp.text


# ─── DB connection edge cases ─────────────────────────────────


def test_get_db_auto_initializes():
    """Call get_db() when _conn is None, verify it creates one."""
    set_db(None)

    with patch("grok_spicy.web.init_db") as mock_init:
        import sqlite3

        mock_conn = sqlite3.connect(":memory:")
        mock_init.return_value = mock_conn

        result = get_db()
        mock_init.assert_called_once()
        assert result is mock_conn

        mock_conn.close()


# ─── Static file serving ─────────────────────────────────────


def test_output_static_serves_files(client):
    """Create a temp file in output/, verify it's served."""
    os.makedirs("output", exist_ok=True)
    test_path = "output/_test_static_serve.txt"
    try:
        with open(test_path, "w") as f:
            f.write("hello from static")

        resp = client.get("/output/_test_static_serve.txt")
        assert resp.status_code == 200
        assert "hello from static" in resp.text
    finally:
        if os.path.exists(test_path):
            os.remove(test_path)
