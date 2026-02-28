"""Pydantic data models — contracts between pipeline steps."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# STEP 1 OUTPUT: Story Plan
# ═══════════════════════════════════════════════════════════════


class Character(BaseModel):
    """A character in the story. visual_description is the SOLE source
    of truth for appearance — used verbatim in every downstream prompt."""

    name: str = Field(description="Short unique name, e.g. 'Luna'")
    role: str = Field(description="protagonist / antagonist / supporting")
    visual_description: str = Field(
        description=(
            "Exhaustive visual description, minimum 80 words. Include: "
            "age range, gender, ethnicity/skin tone, hair (color, style, length), "
            "eye color, facial features (nose shape, jawline), body build, "
            "exact clothing (colors, materials, accessories), "
            "any distinguishing marks (scars, tattoos, glasses). "
            "This text is copy-pasted into every image prompt — be precise."
        )
    )
    personality_cues: list[str] = Field(
        description="3-5 adjective/phrases for expression guidance"
    )


class Scene(BaseModel):
    scene_id: int
    title: str = Field(description="Brief scene title, 3-6 words")
    description: str = Field(
        description=(
            "Vivid, concept-faithful description of what happens in this scene "
            "(2-3 sentences). This text is injected directly into image and video "
            "generation prompts — make it rich and specific to the user's concept, "
            "not generic. Include the key visual moment, character actions, and "
            "environmental details that make this scene unique."
        )
    )
    characters_present: list[str] = Field(
        description="Character names (must match Character.name exactly)"
    )
    setting: str = Field(description="Physical environment, time of day, weather")
    camera: str = Field(
        description="Shot type + movement: 'medium shot, slow dolly forward'"
    )
    mood: str = Field(
        description="Lighting/atmosphere: 'warm golden hour, soft shadows'"
    )
    action: str = Field(
        description="Primary motion for video: 'fox leaps over a fallen log'"
    )
    duration_seconds: int = Field(
        ge=3, le=15, description="Video duration, 8 is a good default"
    )
    transition: str = Field(default="cut", description="cut / crossfade / match-cut")


class StoryPlan(BaseModel):
    title: str
    style: str = Field(
        description=(
            "Visual style for ALL images/videos. Be specific: "
            "'Pixar-style 3D animation with soft volumetric lighting' "
            "not just 'animated'. This prefix starts every prompt."
        )
    )
    aspect_ratio: str = Field(default="16:9", description="16:9 / 9:16 / 1:1 / 4:3")
    color_palette: str = Field(
        description="Dominant colors: 'deep forest greens, amber, moonlight silver'"
    )
    characters: list[Character]
    scenes: list[Scene]


# ═══════════════════════════════════════════════════════════════
# STEP 2-3-5: Consistency Scoring (used by Vision checks)
# ═══════════════════════════════════════════════════════════════


class ConsistencyScore(BaseModel):
    overall_score: float = Field(
        ge=0.0,
        le=1.0,
        description="0 = completely wrong, 1 = perfect match",
    )
    per_character: dict[str, float] = Field(
        default_factory=dict,
        description="Score per character name",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems: 'hair is brown, should be red'",
    )
    fix_prompt: str | None = Field(
        default=None,
        description="Surgical edit prompt to fix issues if any",
    )


# ═══════════════════════════════════════════════════════════════
# PIPELINE STATE (resumability + script generation)
# ═══════════════════════════════════════════════════════════════


class CharacterAsset(BaseModel):
    name: str
    portrait_url: str
    portrait_path: str
    visual_description: str
    consistency_score: float
    generation_attempts: int


class KeyframeAsset(BaseModel):
    scene_id: int
    keyframe_url: str
    keyframe_path: str
    consistency_score: float
    generation_attempts: int
    edit_passes: int
    video_prompt: str


class VideoAsset(BaseModel):
    scene_id: int
    video_url: str
    video_path: str
    duration: float
    first_frame_path: str
    last_frame_path: str
    consistency_score: float
    correction_passes: int


class CharacterRefMapping(BaseModel):
    """LLM-generated mapping from uploaded reference labels to story character names."""

    mapping: dict[str, str] = Field(
        description=(
            "Map each uploaded reference label to the matching character name "
            "from the story. Keys are the uploaded labels, values are Character.name "
            "values. If a label has no match, omit it."
        )
    )


class CharacterDescription(BaseModel):
    """Vision-extracted description of a person in a reference photo."""

    name: str = Field(description="The character name label provided by the user")
    visual_description: str = Field(
        description=(
            "Exhaustive visual description extracted from the photo, minimum 80 words. "
            "Include: age range, gender, ethnicity/skin tone, hair (color, style, length), "
            "eye color, facial features (nose shape, jawline), body build, "
            "exact clothing (colors, materials, accessories), "
            "any distinguishing marks (scars, tattoos, glasses). "
            "Describe ONLY what you see — do not invent or embellish."
        )
    )


class PipelineState(BaseModel):
    plan: StoryPlan
    characters: list[CharacterAsset] = []
    keyframes: list[KeyframeAsset] = []
    videos: list[VideoAsset] = []
    final_video_path: str | None = None
