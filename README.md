# Grok Spicy

This project is a pipeline for generating videos from text prompts, using a series of steps to create a complete story with characters, scenes, and finally, a video.

## Program Flow

The main program flow is orchestrated using Prefect, as defined in `src/grok_spicy/pipeline.py`. The pipeline consists of the following steps:

1.  **Ideation**: This is the first step where the initial story idea is generated based on a user-provided concept. It creates a `StoryPlan` which includes the title, style, aspect ratio, color palette, characters, and scenes. This is done by the `plan_story` function in `src/grok_spicy/tasks/ideation.py`.

2.  **Character Generation**: For each character in the `StoryPlan`, a character sheet is generated. This includes a detailed visual description and a reference portrait. The process involves a vision verification loop to ensure the generated portrait is consistent with the description. This is handled by the `generate_character_sheet` function in `src/grok_spicy/tasks/characters.py`.

3.  **Keyframe Generation**: A keyframe image is composed for each scene. This step uses the character reference sheets to maintain character consistency. It also includes a vision-check and fix loop to ensure the quality of the keyframe. The `compose_keyframe` function in `src/grok_spicy/tasks/keyframes.py` is responsible for this.

4.  **Script Generation**: The assets generated in the previous steps (story plan, character sheets, and keyframes) are compiled into a human-readable markdown storyboard. This is a pure Python process with no API calls. The `compile_script` function in `src/grok_spicy/tasks/script.py` handles this.

5.  **Video Generation**: A video clip is generated for each scene from its keyframe image. This step includes a drift correction mechanism to ensure character consistency throughout the video. The `generate_scene_video` function in `src/grok_spicy/tasks/video.py` is used for this step.

6.  **Video Assembly**: In the final step, all the generated video clips are normalized and concatenated into a single video file using FFmpeg. This is done by the `assemble_final_video` function in `src/grok_spicy/tasks/assembly.py`.

## How to Run

1.  **Install dependencies**:
    ```bash
    pip install -e .
    ```

2.  **Set up environment variables**:
    Copy `.env.example` to `.env` and fill in the required values.

3.  **Run the pipeline**:
    ```bash
    python -m grok_spicy "your story prompt"
    ```

## How to Test

To run the tests, use the following command:

```bash
pytest
```
