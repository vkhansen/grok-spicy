"""Unit tests for PipelineObserver implementations."""

from grok_spicy.db import get_run, init_db
from grok_spicy.events import EventBus
from grok_spicy.observer import NullObserver, PipelineObserver, WebObserver
from grok_spicy.schemas import (
    Character,
    CharacterAsset,
    KeyframeAsset,
    Scene,
    StoryPlan,
    VideoAsset,
)


def _make_plan():
    return StoryPlan(
        title="Test Story",
        style="Pixar-style 3D",
        color_palette="greens, amber",
        characters=[
            Character(
                name="Fox",
                role="protagonist",
                visual_description="A " * 40,
                personality_cues=["brave"],
            ),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="Forest",
                description="Fox walks.",
                characters_present=["Fox"],
                setting="forest",
                camera="wide",
                mood="warm",
                action="walks",
                prompt_summary="Fox walks through the forest.",
                duration_seconds=8,
            ),
        ],
    )


def _make_char_asset():
    return CharacterAsset(
        name="Fox",
        portrait_url="https://example.com/fox.jpg",
        portrait_path="output/fox.jpg",
        visual_description="A " * 40,
        consistency_score=0.85,
        generation_attempts=1,
    )


def _make_kf_asset():
    return KeyframeAsset(
        scene_id=1,
        keyframe_url="https://example.com/kf.jpg",
        keyframe_path="output/kf.jpg",
        consistency_score=0.90,
        generation_attempts=1,
        edit_passes=0,
        video_prompt="Fox walks",
    )


def _make_video_asset():
    return VideoAsset(
        scene_id=1,
        video_url="https://example.com/v.mp4",
        video_path="output/v.mp4",
        duration=8.0,
        first_frame_path="output/first.jpg",
        last_frame_path="output/last.jpg",
        consistency_score=0.88,
        correction_passes=0,
    )


# ─── Protocol conformance ────────────────────────────────────


def test_null_observer_is_pipeline_observer():
    assert isinstance(NullObserver(), PipelineObserver)


def test_web_observer_is_pipeline_observer():
    conn = init_db(":memory:")
    bus = EventBus()
    assert isinstance(WebObserver(conn, bus), PipelineObserver)
    conn.close()


# ─── NullObserver ─────────────────────────────────────────────


def test_null_observer_returns_zero():
    obs = NullObserver()
    assert obs.on_run_start("concept") == 0


def test_null_observer_methods_are_noop():
    obs = NullObserver()
    plan = _make_plan()
    # None of these should raise
    obs.on_plan(0, plan)
    obs.on_character(0, _make_char_asset())
    obs.on_keyframe(0, _make_kf_asset())
    obs.on_script(0, "output/script.md")
    obs.on_video(0, _make_video_asset())
    obs.on_complete(0, "output/final.mp4")
    obs.on_error(0, "something went wrong")


# ─── WebObserver ──────────────────────────────────────────────


def test_web_observer_on_run_start():
    conn = init_db(":memory:")
    bus = EventBus()
    q = bus.subscribe()
    obs = WebObserver(conn, bus)

    run_id = obs.on_run_start("test concept")
    assert run_id >= 1

    # Check DB
    run = get_run(conn, run_id)
    assert run["concept"] == "test concept"
    assert run["status"] == "ideation"

    # Check event
    assert q.qsize() == 1
    event = q.get_nowait()
    assert event.type == "run_start"
    assert event.run_id == run_id
    conn.close()


def test_web_observer_on_plan():
    conn = init_db(":memory:")
    bus = EventBus()
    q = bus.subscribe()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    plan = _make_plan()
    obs.on_plan(run_id, plan)

    run = get_run(conn, run_id)
    assert run["title"] == "Test Story"
    assert run["style"] == "Pixar-style 3D"
    assert run["status"] == "characters"
    assert len(run["characters"]) == 1
    assert len(run["scenes"]) == 1

    # run_start + plan = 2 events
    assert q.qsize() == 2
    conn.close()


def test_web_observer_on_character():
    conn = init_db(":memory:")
    bus = EventBus()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    obs.on_character(run_id, _make_char_asset())

    run = get_run(conn, run_id)
    assert len(run["character_assets"]) == 1
    assert run["character_assets"][0]["name"] == "Fox"
    conn.close()


def test_web_observer_on_keyframe():
    conn = init_db(":memory:")
    bus = EventBus()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    obs.on_keyframe(run_id, _make_kf_asset())

    run = get_run(conn, run_id)
    assert run["status"] == "keyframes"
    assert len(run["keyframe_assets"]) == 1
    conn.close()


def test_web_observer_on_script():
    conn = init_db(":memory:")
    bus = EventBus()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    obs.on_script(run_id, "output/script.md")

    run = get_run(conn, run_id)
    assert run["status"] == "videos"
    assert run["script_path"] == "output/script.md"
    conn.close()


def test_web_observer_on_video():
    conn = init_db(":memory:")
    bus = EventBus()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    obs.on_video(run_id, _make_video_asset())

    run = get_run(conn, run_id)
    assert len(run["video_assets"]) == 1
    conn.close()


def test_web_observer_on_complete():
    conn = init_db(":memory:")
    bus = EventBus()
    q = bus.subscribe()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    obs.on_complete(run_id, "output/final.mp4")

    run = get_run(conn, run_id)
    assert run["status"] == "complete"
    assert run["final_video_path"] == "output/final.mp4"
    assert run["completed_at"] is not None

    # Check the "complete" event was published
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e.type == "complete" for e in events)
    conn.close()


def test_web_observer_on_error():
    conn = init_db(":memory:")
    bus = EventBus()
    q = bus.subscribe()
    obs = WebObserver(conn, bus)
    run_id = obs.on_run_start("test")

    obs.on_error(run_id, "something broke")

    run = get_run(conn, run_id)
    assert run["status"] == "failed"
    assert run["completed_at"] is not None

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].data["error"] == "something broke"
    conn.close()


def test_web_observer_error_handling_does_not_crash():
    """Observer methods should swallow exceptions and log warnings."""
    conn = init_db(":memory:")
    bus = EventBus()
    obs = WebObserver(conn, bus)

    # Close the connection to force errors
    conn.close()

    # None of these should raise despite the closed connection
    obs.on_plan(999, _make_plan())
    obs.on_character(999, _make_char_asset())
    obs.on_keyframe(999, _make_kf_asset())
    obs.on_script(999, "path")
    obs.on_video(999, _make_video_asset())
    obs.on_complete(999, "path")
    obs.on_error(999, "error")
