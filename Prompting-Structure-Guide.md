# Grok Spicy — Prompt File Structure Guide

How to write prompt files for `--prompt-file` so the pipeline produces exactly what you want instead of hallucinating random content.

---

## How Prompt Files Are Parsed

The parser reads your text file and splits it into **concept blocks** using blank lines as separators.

```
Consecutive non-blank lines  →  joined into ONE concept (one pipeline run)
Blank line                   →  separator between concepts
Lines starting with #        →  comments (ignored)
```

Each concept block becomes a separate pipeline run through all 6 steps. If your file has no blank lines, the entire file is ONE concept.

---

## How Scenes Are Created

You do NOT manually define scene boundaries in your prompt. The ideation LLM reads your entire concept and decides:

- How many scenes (typically 3-6)
- What happens in each scene
- Camera angles, lighting, mood
- Which characters appear

The more detail you provide, the less the LLM invents. Vague prompts = hallucinated content.

---

## The Golden Rule

**Everything you want in the video must be in the prompt text. Anything you leave out, the LLM will invent.**

You do NOT need to describe character appearance — that comes from `--ref` images automatically. Focus your prompt on:

- **What happens** (actions, events, interactions)
- **Where it happens** (setting, environment, props)
- **How it looks** (style, lighting, mood, color palette)
- **How it moves** (camera work, motion, pacing)

---

## Prompt File Formats

### Single Concept (one pipeline run, LLM splits into scenes)

```text
# my_prompt.txt
A dark industrial warehouse at night. Harsh spotlights cut through
haze, casting long shadows on concrete floors and steel beams.
Woman1 enters from the left, walking slowly with deliberate
confidence. Woman2 is seated on a metal chair in the center,
looking up as Woman1 approaches. They lock eyes — tension builds.
Woman1 reaches out and takes Woman2's hand, pulling her to stand.
They circle each other slowly under the shifting spotlights.
Style: cinematic noir, cold blue-steel palette, slow deliberate
camera movements, dramatic shadows, anime-influenced intensity.
```

All lines join into one concept. The LLM breaks it into 3-5 scenes.

### Multiple Concepts (multiple pipeline runs, one per block)

Separate blocks with blank lines. Each block = one complete pipeline run:

```text
# multi_scene_shoot.txt

# --- Run 1: The meeting scene ---
Dark industrial warehouse. Harsh spotlights on steel and concrete.
Woman1 walks in from the left with slow confidence. Woman2 sits
on a metal chair, looking up. They lock eyes, tension building.
Style: cinematic noir, cold blue palette, slow camera movements.

# --- Run 2: The confrontation ---
Same warehouse, tighter framing. Woman1 and Woman2 face each other,
inches apart. Woman1 reaches forward — Woman2 flinches but holds
her ground. A single spotlight narrows on their faces.
Style: extreme close-ups, shallow depth of field, warm highlights
breaking through cold shadows.

# --- Run 3: The resolution ---
Warehouse exterior at dawn. Woman1 and Woman2 walk out side by side
through a heavy steel door into pale morning light. They pause,
exchange a look, then walk separate directions without looking back.
Style: wide establishing shot, golden hour warmth replacing the
cold interior tones, slow dolly out.
```

This produces 3 separate videos (one per block).

---

## What To Include In Your Prompt

### Setting and Environment (critical)

The LLM needs a concrete location. Be specific:

```
BAD:  A room with some lighting
GOOD: A dim industrial warehouse with exposed steel beams, concrete
      floor, and harsh overhead spotlights cutting through haze
```

### Actions and Events (critical)

Describe what characters DO, not what they look like. Use strong verbs:

```
BAD:  The two women are in the room together
GOOD: Woman1 strides in from the left doorway and stops three
      paces from Woman2. She extends her hand palm-up. Woman2
      hesitates, then reaches forward and takes it.
```

### Style and Visual Tone (recommended)

Give the LLM explicit style cues so it doesn't default to generic realism:

```
Style: cinematic noir with anime-influenced motion, cold blue-steel
color palette, dramatic rim lighting, slow tracking shots,
shallow depth of field on faces during close-ups
```

### Camera Direction (optional but helps)

If you care about specific shots:

```
Camera: Opens with a wide establishing shot of the warehouse.
Slow dolly in as Woman1 enters. Cut to medium two-shot when
they face each other. Push in to extreme close-up on hands
touching.
```

### Mood and Lighting (optional but helps)

```
Mood: Tense, electric anticipation. Harsh spotlights create
pools of light surrounded by deep shadow. Faint haze drifts
through the beams. Cold steel blues dominate with occasional
warm amber accents on skin.
```

---

## What NOT To Include

### Character Appearance

The `--ref` flag and reference photo analysis handle this. The pipeline extracts a detailed visual description from each reference image and injects it automatically. Writing appearance in your prompt wastes tokens and can conflict:

```
BAD:  Woman1 has long black hair, brown eyes, wearing a black outfit...
GOOD: Woman1 enters from the left with slow deliberate steps.
```

### Scene Numbers or Boundaries

The LLM decides scene structure. Explicitly numbering scenes in your prompt confuses the parser and the LLM:

```
BAD:  Scene 1: The Drop (0-8 seconds)
      Scene 2: The Confrontation (8-16 seconds)

GOOD: The sequence begins with Woman1 entering the warehouse.
      After they lock eyes, the tension escalates into a
      physical confrontation under shifting spotlights.
```

### Technical Pipeline Instructions

Don't tell the LLM about video durations, aspect ratios, or pipeline steps — those are handled by the system prompt and schemas:

```
BAD:  Generate a 16:9 video at 720p, 8 seconds per scene...
GOOD: A fast-paced sequence with rapid cuts and dynamic motion.
```

---

## Prompt Length Guidelines

| Length | Result |
|---|---|
| 1-2 sentences | LLM invents almost everything. High hallucination risk. |
| 1 paragraph (50-100 words) | LLM fills in details but follows your direction. Good for simple scenes. |
| 2-4 paragraphs (100-300 words) | Sweet spot. Enough detail to control the output, enough room for the LLM to add cinematic polish. |
| 5+ paragraphs (300+ words) | Very precise control. The LLM mostly follows your script verbatim. Best for complex multi-scene narratives. |

---

## Character Naming

Character names in your prompt must match the `--ref` flag labels for automatic matching:

```bash
python -m grok_spicy --prompt-file prompt.txt \
  --ref "woman1=source_images/alice.jpg" \
  --ref "woman2=source_images/bob.jpg"
```

In your prompt file, use `woman1` and `woman2` (case-insensitive match):

```text
Woman1 enters from the left. Woman2 is already seated.
```

If names don't match exactly, the pipeline falls back to LLM-based fuzzy matching, but exact matches are more reliable.

---

## Complete Example

```bash
python -m grok_spicy --prompt-file my_scene.txt \
  --ref "woman1=source_images/alice.jpg" \
  --ref "woman2=source_images/eve.jpg" \
  --serve -v
```

```text
# my_scene.txt
#
# Noir warehouse confrontation — two characters, single location
#
A vast industrial warehouse at night, steel beams overhead,
concrete floor stained with oil, harsh white spotlights creating
isolated pools of light surrounded by deep impenetrable shadow.
Thin haze drifts through the light beams. Cold, oppressive silence.

Woman1 pushes through a heavy steel door on the left and walks
slowly into the nearest pool of light, her footsteps echoing.
She stops and stares into the darkness ahead. A beat of silence.

Woman2 steps forward from the shadows on the right, entering
her own pool of light ten feet away. They lock eyes across the
gap. Neither moves. The tension is electric — both waiting for
the other to break first.

Woman1 takes one deliberate step forward. Woman2 holds her ground
but her expression shifts from defiance to uncertainty. Woman1
extends her hand palm-up. Woman2 looks down at it, then back up
at Woman1's face. Slowly, she reaches out and takes it.

Style: cinematic noir with anime-influenced energy and sharp
dynamic lines. Cold blue-steel palette with warm amber accents
on skin. Dramatic rim lighting. Slow tracking camera with
occasional rapid cuts on key moments. Shallow depth of field
during close-ups. Subtle particle haze in light beams.
```

With `-v` you'll see in the logs:
```
Loaded 1 concept(s) from my_scene.txt
  Concept 1 (1247 chars): A vast industrial warehouse at night...
```

This confirms the entire file was read as one concept and passed intact to the ideation LLM.
