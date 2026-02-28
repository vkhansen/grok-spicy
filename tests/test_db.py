"""Unit tests for SQLite database layer."""

import json

import pytest

from grok_spicy.db import (
    _now,
    get_reference_images,
    get_run,
    init_db,
    insert_characters,
    insert_reference_image,
    insert_run,
    insert_scenes,
    list_runs,
    update_run,
    upsert_character_asset,
    upsert_keyframe_asset,
    upsert_video_asset,
)
from grok_spicy.schemas import (
    Character,
    CharacterAsset,
    KeyframeAsset,
    Scene,
    VideoAsset,
)


@pytest.fixture()
def conn():
    """In-memory SQLite database for each test."""
    c = init_db(":memory:")
    yield c
    c.close()


# ─── init_db ────────────────────────────────────────────────


def test_init_db_creates_tables(conn):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "runs",
        "characters",
        "scenes",
        "reference_images",
        "character_assets",
        "keyframe_assets",
        "video_assets",
    }
    assert expected.issubset(tables)


def test_init_db_idempotent(conn):
    """Calling init_db again on the same DB shouldn't fail."""
    # Re-execute schema on existing connection
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "concept TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
        "started_at TEXT NOT NULL, title TEXT, style TEXT, "
        "aspect_ratio TEXT, color_palette TEXT, script_path TEXT, "
        "final_video_path TEXT, completed_at TEXT);"
    )
    conn.commit()


def test_init_db_row_factory(conn):
    row = conn.execute(
        "INSERT INTO runs (concept, status, started_at) VALUES ('test', 'pending', 'now') RETURNING *"
    ).fetchone()
    assert row["concept"] == "test"


# ─── insert_run / list_runs ─────────────────────────────────


def test_insert_run_returns_id(conn):
    run_id = insert_run(conn, "A fox meets an owl")
    assert isinstance(run_id, int)
    assert run_id >= 1


def test_insert_run_sets_defaults(conn):
    run_id = insert_run(conn, "concept")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "pending"
    assert row["started_at"] is not None


def test_list_runs_returns_newest_first(conn):
    id1 = insert_run(conn, "first")
    id2 = insert_run(conn, "second")
    runs = list_runs(conn)
    assert len(runs) == 2
    assert runs[0]["id"] == id2
    assert runs[1]["id"] == id1


def test_list_runs_empty(conn):
    assert list_runs(conn) == []


# ─── update_run ──────────────────────────────────────────────


def test_update_run_partial(conn):
    run_id = insert_run(conn, "concept")
    update_run(conn, run_id, status="ideation", title="My Title")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "ideation"
    assert row["title"] == "My Title"
    assert row["concept"] == "concept"  # unchanged


def test_update_run_ignores_unknown_fields(conn):
    run_id = insert_run(conn, "concept")
    update_run(conn, run_id, unknown_field="value")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "pending"  # unchanged


def test_update_run_empty_fields(conn):
    run_id = insert_run(conn, "concept")
    update_run(conn, run_id)  # no fields — should be a no-op


# ─── insert_characters / insert_scenes ───────────────────────


def _make_character(name="Fox"):
    return Character(
        name=name,
        role="protagonist",
        visual_description="A " * 40,
        personality_cues=["brave", "curious"],
    )


def _make_scene(scene_id=1):
    return Scene(
        scene_id=scene_id,
        title="Forest Encounter",
        description="Fox enters the forest.",
        characters_present=["Fox"],
        setting="Dense autumn forest",
        camera="medium shot",
        mood="warm golden hour",
        action="Fox walks cautiously",
        duration_seconds=8,
    )


def test_insert_characters(conn):
    run_id = insert_run(conn, "concept")
    chars = [_make_character("Fox"), _make_character("Owl")]
    insert_characters(conn, run_id, chars)
    rows = conn.execute(
        "SELECT * FROM characters WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"Fox", "Owl"}


def test_insert_characters_json_personality(conn):
    run_id = insert_run(conn, "concept")
    insert_characters(conn, run_id, [_make_character()])
    row = conn.execute(
        "SELECT personality_cues FROM characters WHERE run_id = ?", (run_id,)
    ).fetchone()
    cues = json.loads(row["personality_cues"])
    assert cues == ["brave", "curious"]


def test_insert_scenes(conn):
    run_id = insert_run(conn, "concept")
    scenes = [_make_scene(1), _make_scene(2)]
    insert_scenes(conn, run_id, scenes)
    rows = conn.execute(
        "SELECT * FROM scenes WHERE run_id = ? ORDER BY scene_id", (run_id,)
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["scene_id"] == 1
    assert rows[1]["scene_id"] == 2


def test_insert_scenes_json_characters_present(conn):
    run_id = insert_run(conn, "concept")
    insert_scenes(conn, run_id, [_make_scene()])
    row = conn.execute(
        "SELECT characters_present FROM scenes WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert json.loads(row["characters_present"]) == ["Fox"]


# ─── reference_images ────────────────────────────────────────


def test_insert_and_get_reference_images(conn):
    run_id = insert_run(conn, "concept")
    insert_reference_image(conn, run_id, "Fox", "fox.jpg", "output/refs/fox.jpg")
    insert_reference_image(conn, run_id, "Owl", "owl.jpg", "output/refs/owl.jpg")
    refs = get_reference_images(conn, run_id)
    assert refs == {"Fox": "output/refs/fox.jpg", "Owl": "output/refs/owl.jpg"}


def test_get_reference_images_empty(conn):
    run_id = insert_run(conn, "concept")
    assert get_reference_images(conn, run_id) == {}


# ─── upsert_character_asset ──────────────────────────────────


def _make_character_asset(name="Fox"):
    return CharacterAsset(
        name=name,
        portrait_url="https://example.com/fox.jpg",
        portrait_path="output/character_sheets/Fox_v1.jpg",
        visual_description="A " * 40,
        consistency_score=0.85,
        generation_attempts=1,
    )


def test_upsert_character_asset_insert(conn):
    run_id = insert_run(conn, "concept")
    upsert_character_asset(conn, run_id, _make_character_asset())
    rows = conn.execute(
        "SELECT * FROM character_assets WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Fox"
    assert rows[0]["consistency_score"] == 0.85


def test_upsert_character_asset_replaces(conn):
    run_id = insert_run(conn, "concept")
    upsert_character_asset(conn, run_id, _make_character_asset())
    updated = _make_character_asset()
    updated.consistency_score = 0.95
    updated.generation_attempts = 2
    upsert_character_asset(conn, run_id, updated)
    rows = conn.execute(
        "SELECT * FROM character_assets WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["consistency_score"] == 0.95
    assert rows[0]["generation_attempts"] == 2


# ─── upsert_keyframe_asset ───────────────────────────────────


def _make_keyframe_asset(scene_id=1):
    return KeyframeAsset(
        scene_id=scene_id,
        keyframe_url="https://example.com/kf.jpg",
        keyframe_path="output/keyframes/scene_1.jpg",
        consistency_score=0.90,
        generation_attempts=1,
        edit_passes=0,
        video_prompt="medium shot, Fox walks",
    )


def test_upsert_keyframe_asset_insert(conn):
    run_id = insert_run(conn, "concept")
    upsert_keyframe_asset(conn, run_id, _make_keyframe_asset())
    rows = conn.execute(
        "SELECT * FROM keyframe_assets WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["scene_id"] == 1


def test_upsert_keyframe_asset_replaces(conn):
    run_id = insert_run(conn, "concept")
    upsert_keyframe_asset(conn, run_id, _make_keyframe_asset())
    updated = _make_keyframe_asset()
    updated.consistency_score = 0.99
    upsert_keyframe_asset(conn, run_id, updated)
    rows = conn.execute(
        "SELECT * FROM keyframe_assets WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["consistency_score"] == 0.99


# ─── upsert_video_asset ──────────────────────────────────────


def _make_video_asset(scene_id=1):
    return VideoAsset(
        scene_id=scene_id,
        video_url="https://example.com/v1.mp4",
        video_path="output/videos/scene_1.mp4",
        duration=8.0,
        first_frame_path="output/frames/scene_1_first.jpg",
        last_frame_path="output/frames/scene_1_last.jpg",
        consistency_score=0.88,
        correction_passes=0,
    )


def test_upsert_video_asset_insert(conn):
    run_id = insert_run(conn, "concept")
    upsert_video_asset(conn, run_id, _make_video_asset())
    rows = conn.execute(
        "SELECT * FROM video_assets WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["duration"] == 8.0


def test_upsert_video_asset_replaces(conn):
    run_id = insert_run(conn, "concept")
    upsert_video_asset(conn, run_id, _make_video_asset())
    updated = _make_video_asset()
    updated.correction_passes = 2
    upsert_video_asset(conn, run_id, updated)
    rows = conn.execute(
        "SELECT * FROM video_assets WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["correction_passes"] == 2


# ─── get_run (full nested query) ─────────────────────────────


def test_get_run_not_found(conn):
    assert get_run(conn, 999) is None


def test_get_run_full(conn):
    run_id = insert_run(conn, "test concept")
    update_run(conn, run_id, title="My Title", style="cartoon")

    insert_characters(conn, run_id, [_make_character()])
    insert_scenes(conn, run_id, [_make_scene()])
    insert_reference_image(conn, run_id, "Fox", "fox.jpg", "output/refs/fox.jpg")
    upsert_character_asset(conn, run_id, _make_character_asset())
    upsert_keyframe_asset(conn, run_id, _make_keyframe_asset())
    upsert_video_asset(conn, run_id, _make_video_asset())

    run = get_run(conn, run_id)
    assert run is not None
    assert run["concept"] == "test concept"
    assert run["title"] == "My Title"
    assert len(run["characters"]) == 1
    assert run["characters"][0]["personality_cues"] == ["brave", "curious"]
    assert len(run["scenes"]) == 1
    assert run["scenes"][0]["characters_present"] == ["Fox"]
    assert len(run["reference_images"]) == 1
    assert len(run["character_assets"]) == 1
    assert len(run["keyframe_assets"]) == 1
    assert len(run["video_assets"]) == 1


# ─── _now helper ─────────────────────────────────────────────


def test_now_returns_iso_format():
    ts = _now()
    assert "T" in ts
    assert "+" in ts or ts.endswith("Z") or "UTC" in ts or "+00:00" in ts
