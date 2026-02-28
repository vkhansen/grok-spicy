"""Step 1: Story ideation — concept string to structured StoryPlan."""

from __future__ import annotations

from datetime import timedelta

from prefect import task
from prefect.tasks import task_input_hash

from grok_spicy.client import MODEL_STRUCTURED, get_client
from grok_spicy.schemas import StoryPlan

SYSTEM_PROMPT = (
    "You are a visual storytelling director. Create a production plan for a "
    "short animated video. Rules:\n"
    "- Every character needs an exhaustive visual description (minimum 80 words). "
    "Include: age range, gender, ethnicity/skin tone, hair (color, style, length), "
    "eye color, facial features, body build, exact clothing (colors, materials, "
    "accessories), and any distinguishing marks. This description is the SOLE "
    "appearance reference used for all image generation — be precise.\n"
    "- Design scenes for 8-second video clips with simple, clear, single actions.\n"
    "- Limit: 2-3 characters, 3-5 scenes for best visual quality.\n"
    "- The style field must be specific (e.g. 'Pixar-style 3D animation with "
    "soft volumetric lighting'), not vague ('animated').\n"
    "- Each scene's action should describe one clear motion suitable for video."
)


@task(
    name="plan-story",
    retries=2,
    retry_delay_seconds=10,
    cache_key_fn=task_input_hash,
    cache_expiration=timedelta(hours=1),
)
def plan_story(concept: str) -> StoryPlan:
    """Generate a structured StoryPlan from a concept string."""
    from xai_sdk.chat import system, user

    client = get_client()
    chat = client.chat.create(model=MODEL_STRUCTURED)
    chat.append(system(SYSTEM_PROMPT))
    chat.append(user(f"Create a visual story plan for: {concept}"))
    _, plan = chat.parse(StoryPlan)
    return plan
