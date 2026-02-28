"""SQLite database layer for pipeline run persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from grok_spicy.schemas import (
        Character,
        CharacterAsset,
        KeyframeAsset,
        Scene,
        VideoAsset,
    )

_DEFAULT_DB_PATH = "output/grok_spicy.db"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    concept          TEXT NOT NULL,
    title            TEXT,
    style            TEXT,
    aspect_ratio     TEXT,
    color_palette    TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    script_path      TEXT,
    final_video_path TEXT,
    started_at       TEXT NOT NULL,
    completed_at     TEXT
);

CREATE TABLE IF NOT EXISTS characters (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER NOT NULL REFERENCES runs(id),
    name               TEXT NOT NULL,
    role               TEXT NOT NULL,
    visual_description TEXT NOT NULL,
    personality_cues   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    scene_id            INTEGER NOT NULL,
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    characters_present  TEXT NOT NULL,
    setting             TEXT NOT NULL,
    camera              TEXT NOT NULL,
    mood                TEXT NOT NULL,
    action              TEXT NOT NULL,
    duration_seconds    INTEGER NOT NULL,
    transition          TEXT NOT NULL DEFAULT 'cut'
);

CREATE TABLE IF NOT EXISTS reference_images (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES runs(id),
    character_name    TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    uploaded_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_assets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    name                TEXT NOT NULL,
    portrait_url        TEXT NOT NULL,
    portrait_path       TEXT NOT NULL,
    visual_description  TEXT NOT NULL,
    consistency_score   REAL NOT NULL,
    generation_attempts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS keyframe_assets (
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

CREATE TABLE IF NOT EXISTS video_assets (
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
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def init_db(db_path: str = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create tables if they don't exist and enable WAL mode."""
    import os

    logger.info("Initialising database at %s", db_path)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    logger.debug("Database initialised (WAL mode, 7 tables)")
    return conn


# ─── Runs ─────────────────────────────────────────────────────


def insert_run(conn: sqlite3.Connection, concept: str) -> int:
    """Insert a new run and return its id."""
    cur = conn.execute(
        "INSERT INTO runs (concept, status, started_at) VALUES (?, 'pending', ?)",
        (concept, _now()),
    )
    conn.commit()
    run_id = cur.lastrowid
    logger.info("Inserted run id=%d, concept=%r", run_id, concept[:80])
    return run_id  # type: ignore[return-value]


def update_run(conn: sqlite3.Connection, run_id: int, **fields: object) -> None:
    """Partial update on the runs table."""
    if not fields:
        return
    allowed = {
        "title",
        "style",
        "aspect_ratio",
        "color_palette",
        "status",
        "script_path",
        "final_video_path",
        "completed_at",
    }
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    vals = [fields[c] for c in cols]
    conn.execute(f"UPDATE runs SET {set_clause} WHERE id = ?", vals + [run_id])
    conn.commit()
    logger.debug("Updated run %d: %s", run_id, {c: fields[c] for c in cols})


# ─── Story plan children ─────────────────────────────────────


def insert_characters(
    conn: sqlite3.Connection,
    run_id: int,
    chars: list[Character],
) -> None:
    """Bulk insert Character models from a StoryPlan."""
    conn.executemany(
        "INSERT INTO characters (run_id, name, role, visual_description, personality_cues) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                run_id,
                c.name,
                c.role,
                c.visual_description,
                json.dumps(c.personality_cues),
            )
            for c in chars
        ],
    )
    conn.commit()


def insert_scenes(
    conn: sqlite3.Connection,
    run_id: int,
    scenes: list[Scene],
) -> None:
    """Bulk insert Scene models from a StoryPlan."""
    conn.executemany(
        "INSERT INTO scenes (run_id, scene_id, title, description, "
        "characters_present, setting, camera, mood, action, duration_seconds, transition) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                s.scene_id,
                s.title,
                s.description,
                json.dumps(s.characters_present),
                s.setting,
                s.camera,
                s.mood,
                s.action,
                s.duration_seconds,
                s.transition,
            )
            for s in scenes
        ],
    )
    conn.commit()


# ─── Reference images ────────────────────────────────────────


def insert_reference_image(
    conn: sqlite3.Connection,
    run_id: int,
    char_name: str,
    filename: str,
    path: str,
) -> None:
    """Store an uploaded reference image record."""
    conn.execute(
        "INSERT INTO reference_images (run_id, character_name, original_filename, "
        "stored_path, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (run_id, char_name, filename, path, _now()),
    )
    conn.commit()
    logger.debug(
        "Inserted reference image: run=%d, char=%r, file=%r, path=%s",
        run_id,
        char_name,
        filename,
        path,
    )


def get_reference_images(
    conn: sqlite3.Connection,
    run_id: int,
) -> dict[str, str]:
    """Return {character_name: stored_path} for a run."""
    rows = conn.execute(
        "SELECT character_name, stored_path FROM reference_images WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    return {r["character_name"]: r["stored_path"] for r in rows}


# ─── Asset upserts ────────────────────────────────────────────


def upsert_character_asset(
    conn: sqlite3.Connection,
    run_id: int,
    asset: CharacterAsset,
) -> None:
    """Insert or replace a character asset by (run_id, name)."""
    conn.execute(
        "DELETE FROM character_assets WHERE run_id = ? AND name = ?",
        (run_id, asset.name),
    )
    conn.execute(
        "INSERT INTO character_assets "
        "(run_id, name, portrait_url, portrait_path, visual_description, "
        "consistency_score, generation_attempts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            asset.name,
            asset.portrait_url,
            asset.portrait_path,
            asset.visual_description,
            asset.consistency_score,
            asset.generation_attempts,
        ),
    )
    conn.commit()
    logger.debug(
        "Upserted character asset: run=%d, name=%r, score=%.2f",
        run_id,
        asset.name,
        asset.consistency_score,
    )


def upsert_keyframe_asset(
    conn: sqlite3.Connection,
    run_id: int,
    asset: KeyframeAsset,
) -> None:
    """Insert or replace a keyframe asset by (run_id, scene_id)."""
    conn.execute(
        "DELETE FROM keyframe_assets WHERE run_id = ? AND scene_id = ?",
        (run_id, asset.scene_id),
    )
    conn.execute(
        "INSERT INTO keyframe_assets "
        "(run_id, scene_id, keyframe_url, keyframe_path, consistency_score, "
        "generation_attempts, edit_passes, video_prompt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            asset.scene_id,
            asset.keyframe_url,
            asset.keyframe_path,
            asset.consistency_score,
            asset.generation_attempts,
            asset.edit_passes,
            asset.video_prompt,
        ),
    )
    conn.commit()
    logger.debug(
        "Upserted keyframe asset: run=%d, scene=%d, score=%.2f",
        run_id,
        asset.scene_id,
        asset.consistency_score,
    )


def upsert_video_asset(
    conn: sqlite3.Connection,
    run_id: int,
    asset: VideoAsset,
) -> None:
    """Insert or replace a video asset by (run_id, scene_id)."""
    conn.execute(
        "DELETE FROM video_assets WHERE run_id = ? AND scene_id = ?",
        (run_id, asset.scene_id),
    )
    conn.execute(
        "INSERT INTO video_assets "
        "(run_id, scene_id, video_url, video_path, duration, first_frame_path, "
        "last_frame_path, consistency_score, correction_passes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            asset.scene_id,
            asset.video_url,
            asset.video_path,
            asset.duration,
            asset.first_frame_path,
            asset.last_frame_path,
            asset.consistency_score,
            asset.correction_passes,
        ),
    )
    conn.commit()
    logger.debug(
        "Upserted video asset: run=%d, scene=%d, score=%.2f, corrections=%d",
        run_id,
        asset.scene_id,
        asset.consistency_score,
        asset.correction_passes,
    )


# ─── Queries ──────────────────────────────────────────────────


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def list_runs(conn: sqlite3.Connection) -> list[dict]:
    """Summary list of all runs, newest first."""
    rows = conn.execute(
        "SELECT id, concept, title, status, started_at, completed_at "
        "FROM runs ORDER BY id DESC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """Full run with nested characters, scenes, and assets."""
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    run = _row_to_dict(row)

    run["characters"] = [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM characters WHERE run_id = ?", (run_id,)
        ).fetchall()
    ]
    for c in run["characters"]:
        c["personality_cues"] = json.loads(c["personality_cues"])

    run["scenes"] = [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM scenes WHERE run_id = ? ORDER BY scene_id", (run_id,)
        ).fetchall()
    ]
    for s in run["scenes"]:
        s["characters_present"] = json.loads(s["characters_present"])

    run["reference_images"] = [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM reference_images WHERE run_id = ?", (run_id,)
        ).fetchall()
    ]

    run["character_assets"] = [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM character_assets WHERE run_id = ?", (run_id,)
        ).fetchall()
    ]

    run["keyframe_assets"] = [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM keyframe_assets WHERE run_id = ? ORDER BY scene_id",
            (run_id,),
        ).fetchall()
    ]

    run["video_assets"] = [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM video_assets WHERE run_id = ? ORDER BY scene_id",
            (run_id,),
        ).fetchall()
    ]

    return run
