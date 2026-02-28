"""Pipeline observer protocol and implementations."""

from __future__ import annotations

import logging
import sqlite3
from typing import Protocol, runtime_checkable

from grok_spicy.db import (
    insert_characters,
    insert_run,
    insert_scenes,
    update_run,
    upsert_character_asset,
    upsert_keyframe_asset,
    upsert_video_asset,
)
from grok_spicy.events import Event, EventBus
from grok_spicy.schemas import (
    CharacterAsset,
    KeyframeAsset,
    StoryPlan,
    VideoAsset,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineObserver(Protocol):
    """Protocol for observing pipeline step completions."""

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


class NullObserver:
    """No-op observer for CLI-only runs. Zero overhead."""

    def on_run_start(self, concept: str) -> int:
        return 0

    def on_plan(self, run_id: int, plan: StoryPlan) -> None:
        pass

    def on_character(self, run_id: int, asset: CharacterAsset) -> None:
        pass

    def on_keyframe(self, run_id: int, asset: KeyframeAsset) -> None:
        pass

    def on_script(self, run_id: int, script_path: str) -> None:
        pass

    def on_video(self, run_id: int, asset: VideoAsset) -> None:
        pass

    def on_complete(self, run_id: int, final_path: str) -> None:
        pass

    def on_error(self, run_id: int, error: str) -> None:
        pass


class WebObserver:
    """Observer that writes to SQLite and pushes events to the EventBus."""

    def __init__(self, conn: sqlite3.Connection, bus: EventBus) -> None:
        self._conn = conn
        self._bus = bus

    def on_run_start(self, concept: str) -> int:
        run_id = insert_run(self._conn, concept)
        update_run(self._conn, run_id, status="ideation")
        self._bus.publish(
            Event(type="run_start", run_id=run_id, data={"concept": concept})
        )
        return run_id

    def on_plan(self, run_id: int, plan: StoryPlan) -> None:
        try:
            update_run(
                self._conn,
                run_id,
                title=plan.title,
                style=plan.style,
                aspect_ratio=plan.aspect_ratio,
                color_palette=plan.color_palette,
                status="characters",
            )
            insert_characters(self._conn, run_id, plan.characters)
            insert_scenes(self._conn, run_id, plan.scenes)
            self._bus.publish(
                Event(
                    type="plan",
                    run_id=run_id,
                    data={"title": plan.title, "style": plan.style},
                )
            )
        except Exception:
            logger.warning("WebObserver.on_plan failed", exc_info=True)

    def on_character(self, run_id: int, asset: CharacterAsset) -> None:
        try:
            upsert_character_asset(self._conn, run_id, asset)
            self._bus.publish(
                Event(
                    type="character",
                    run_id=run_id,
                    data={
                        "name": asset.name,
                        "portrait_path": asset.portrait_path,
                        "consistency_score": asset.consistency_score,
                    },
                )
            )
        except Exception:
            logger.warning("WebObserver.on_character failed", exc_info=True)

    def on_keyframe(self, run_id: int, asset: KeyframeAsset) -> None:
        try:
            update_run(self._conn, run_id, status="keyframes")
            upsert_keyframe_asset(self._conn, run_id, asset)
            self._bus.publish(
                Event(
                    type="keyframe",
                    run_id=run_id,
                    data={
                        "scene_id": asset.scene_id,
                        "keyframe_path": asset.keyframe_path,
                        "consistency_score": asset.consistency_score,
                    },
                )
            )
        except Exception:
            logger.warning("WebObserver.on_keyframe failed", exc_info=True)

    def on_script(self, run_id: int, script_path: str) -> None:
        try:
            update_run(self._conn, run_id, status="videos", script_path=script_path)
            self._bus.publish(
                Event(
                    type="script",
                    run_id=run_id,
                    data={"script_path": script_path},
                )
            )
        except Exception:
            logger.warning("WebObserver.on_script failed", exc_info=True)

    def on_video(self, run_id: int, asset: VideoAsset) -> None:
        try:
            upsert_video_asset(self._conn, run_id, asset)
            self._bus.publish(
                Event(
                    type="video",
                    run_id=run_id,
                    data={
                        "scene_id": asset.scene_id,
                        "video_path": asset.video_path,
                        "consistency_score": asset.consistency_score,
                    },
                )
            )
        except Exception:
            logger.warning("WebObserver.on_video failed", exc_info=True)

    def on_complete(self, run_id: int, final_path: str) -> None:
        try:
            from grok_spicy.db import _now

            update_run(
                self._conn,
                run_id,
                status="complete",
                final_video_path=final_path,
                completed_at=_now(),
            )
            self._bus.publish(
                Event(
                    type="complete",
                    run_id=run_id,
                    data={"final_video_path": final_path},
                )
            )
        except Exception:
            logger.warning("WebObserver.on_complete failed", exc_info=True)

    def on_error(self, run_id: int, error: str) -> None:
        try:
            from grok_spicy.db import _now

            update_run(
                self._conn,
                run_id,
                status="failed",
                completed_at=_now(),
            )
            self._bus.publish(Event(type="error", run_id=run_id, data={"error": error}))
        except Exception:
            logger.warning("WebObserver.on_error failed", exc_info=True)
