"""Prefect flow — main pipeline orchestration."""

from __future__ import annotations

import os

from prefect import flow

from grok_spicy.schemas import PipelineState
from grok_spicy.tasks.assembly import assemble_final_video
from grok_spicy.tasks.characters import generate_character_sheet
from grok_spicy.tasks.ideation import plan_story
from grok_spicy.tasks.keyframes import compose_keyframe
from grok_spicy.tasks.script import compile_script
from grok_spicy.tasks.video import generate_scene_video


def _save_state(state: PipelineState) -> None:
    """Persist pipeline state to output/state.json."""
    os.makedirs("output", exist_ok=True)
    with open("output/state.json", "w") as f:
        f.write(state.model_dump_json(indent=2))


@flow(
    name="grok-video-pipeline",
    retries=1,
    retry_delay_seconds=60,
    log_prints=True,
)
def video_pipeline(concept: str) -> str:
    """End-to-end video generation pipeline.

    Takes a concept string and produces a final assembled video.
    """

    # ═══ STEP 1: IDEATION ═══
    print("=== STEP 1: Planning story ===")
    plan = plan_story(concept)
    print(
        f"-> {plan.title}: {len(plan.characters)} chars, " f"{len(plan.scenes)} scenes"
    )

    # ═══ STEP 2: CHARACTER SHEETS (parallel) ═══
    print("=== STEP 2: Character sheets ===")
    char_futures = [
        generate_character_sheet.submit(c, plan.style, plan.aspect_ratio)
        for c in plan.characters
    ]
    characters = [f.result() for f in char_futures]
    char_map = {c.name: c for c in characters}
    for c in characters:
        print(
            f"  {c.name}: score={c.consistency_score:.2f}, "
            f"attempts={c.generation_attempts}"
        )

    # ═══ STEP 3: KEYFRAMES (sequential for frame chaining) ═══
    print("=== STEP 3: Keyframes ===")
    keyframes = []
    prev_url = None
    for scene in plan.scenes:
        kf = compose_keyframe(scene, plan, char_map, prev_url)
        keyframes.append(kf)
        prev_url = kf.keyframe_url
        print(
            f"  Scene {scene.scene_id}: score={kf.consistency_score:.2f}, "
            f"edits={kf.edit_passes}"
        )

    # ═══ STEP 4: SCRIPT ═══
    print("=== STEP 4: Script ===")
    script = compile_script(plan, characters, keyframes)
    print(f"-> {script}")

    # Save intermediate state
    state = PipelineState(plan=plan, characters=characters, keyframes=keyframes)
    _save_state(state)

    # ═══ STEP 5: VIDEOS (sequential) ═══
    print("=== STEP 5: Videos ===")
    videos = []
    for scene, kf in zip(plan.scenes, keyframes, strict=True):
        v = generate_scene_video(kf, scene, char_map)
        videos.append(v)
        print(
            f"  Scene {scene.scene_id}: score={v.consistency_score:.2f}, "
            f"corrections={v.correction_passes}"
        )

    # ═══ STEP 6: ASSEMBLY ═══
    print("=== STEP 6: Assembly ===")
    final = assemble_final_video(videos)
    print(f"-> {final}")

    # Save final state
    state.videos = videos
    state.final_video_path = final
    _save_state(state)

    return final
