"""Unit tests for Pydantic schemas."""

from grok_spicy.schemas import (
    Character,
    CharacterAsset,
    ConsistencyScore,
    KeyframeAsset,
    PipelineState,
    Scene,
    StoryPlan,
    VideoAsset,
)


def _make_plan() -> StoryPlan:
    return StoryPlan(
        title="Test Story",
        style="Pixar-style 3D animation with soft volumetric lighting",
        color_palette="deep forest greens, amber, moonlight silver",
        characters=[
            Character(
                name="Fox",
                role="protagonist",
                visual_description="A " * 40,  # 80 words
                personality_cues=["brave", "curious"],
            ),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="Forest Encounter",
                description="Fox enters the forest.",
                characters_present=["Fox"],
                setting="Dense autumn forest, late afternoon",
                camera="medium shot, slow dolly forward",
                mood="warm golden hour, soft shadows",
                action="Fox walks cautiously through fallen leaves",
                duration_seconds=8,
            ),
        ],
    )


def test_story_plan_schema():
    schema = StoryPlan.model_json_schema()
    assert "characters" in schema["properties"]
    assert "scenes" in schema["properties"]


def test_story_plan_round_trip():
    plan = _make_plan()
    json_str = plan.model_dump_json()
    restored = StoryPlan.model_validate_json(json_str)
    assert restored.title == plan.title
    assert len(restored.characters) == 1
    assert len(restored.scenes) == 1


def test_pipeline_state_round_trip():
    plan = _make_plan()
    state = PipelineState(
        plan=plan,
        characters=[
            CharacterAsset(
                name="Fox",
                portrait_url="https://example.com/fox.jpg",
                portrait_path="output/character_sheets/Fox_v1.jpg",
                visual_description="A " * 40,
                consistency_score=0.85,
                generation_attempts=1,
            ),
        ],
        keyframes=[
            KeyframeAsset(
                scene_id=1,
                keyframe_url="https://example.com/kf1.jpg",
                keyframe_path="output/keyframes/scene_1_v1.jpg",
                consistency_score=0.90,
                generation_attempts=1,
                edit_passes=0,
                video_prompt="medium shot. Fox walks. warm lighting.",
            ),
        ],
        videos=[
            VideoAsset(
                scene_id=1,
                video_url="https://example.com/v1.mp4",
                video_path="output/videos/scene_1.mp4",
                duration=8.0,
                first_frame_path="output/frames/scene_1_first.jpg",
                last_frame_path="output/frames/scene_1_last.jpg",
                consistency_score=0.88,
                correction_passes=0,
            ),
        ],
        final_video_path="output/final_video.mp4",
    )
    json_str = state.model_dump_json(indent=2)
    restored = PipelineState.model_validate_json(json_str)
    assert restored.plan.title == "Test Story"
    assert len(restored.characters) == 1
    assert len(restored.videos) == 1
    assert restored.final_video_path == "output/final_video.mp4"


def test_consistency_score_bounds():
    score = ConsistencyScore(overall_score=0.85)
    assert 0.0 <= score.overall_score <= 1.0
    assert score.issues == []
    assert score.fix_prompt is None


def test_scene_duration_bounds():
    scene = Scene(
        scene_id=1,
        title="Test",
        description="Test",
        characters_present=["Fox"],
        setting="forest",
        camera="wide",
        mood="warm",
        action="walks",
        duration_seconds=8,
    )
    assert 3 <= scene.duration_seconds <= 15
