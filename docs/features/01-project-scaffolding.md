# Feature 01: Project Scaffolding

**Priority:** P0 — Foundation
**Depends on:** Nothing
**Blocks:** All other cards

---

## Goal

Set up the Python project structure, dependency management, and directory layout so all subsequent cards have a place to land.

## Deliverables

### 1. `pyproject.toml`

```toml
[project]
name = "grok-spicy"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "xai-sdk>=0.1",
    "prefect>=3.0",
    "pydantic>=2.0",
    "requests>=2.31",
]

[project.scripts]
grok-spicy = "grok_spicy.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 2. Directory structure

```
src/
└── grok_spicy/
    ├── __init__.py          # Package init, version
    ├── __main__.py          # Stub: parse args, call pipeline
    ├── schemas.py           # Stub: empty, filled in Card 02
    ├── client.py            # Stub: empty, filled in Card 03
    ├── tasks/
    │   ├── __init__.py
    │   ├── ideation.py      # Stub
    │   ├── characters.py    # Stub
    │   ├── keyframes.py     # Stub
    │   ├── script.py        # Stub
    │   ├── video.py         # Stub
    │   └── assembly.py      # Stub
    └── pipeline.py          # Stub
```

Every module gets a stub file with a module docstring and placeholder imports. This lets subsequent cards focus on implementation without directory setup.

### 3. `.env.example`

```
XAI_API_KEY=your-key-here
```

### 4. Verify

- `pip install -e .` succeeds
- `python -m grok_spicy` prints a usage message without crashing
- All stubs importable: `from grok_spicy.schemas import *` etc.

## Acceptance Criteria

- [ ] `pip install -e .` works cleanly
- [ ] All stub modules exist and are importable
- [ ] `python -m grok_spicy` runs without error
- [ ] `output/` directory is gitignored
