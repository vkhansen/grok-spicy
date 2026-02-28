# Testing Guide

## Quick Reference

```bash
# Run all unit tests (no server, no API key needed)
python -m pytest tests/ --tb=short -q

# Run a specific test file
python -m pytest tests/test_web.py -v

# Run live server integration tests
python -m pytest tests/test_web_live.py -v -m live

# Run everything including live tests
python -m pytest tests/ -v -m "live or not live"
```

## Test Files

| File | Tests | What It Covers |
|---|---|---|
| `test_schemas.py` | 5 | Pydantic model validation, JSON round-trips, field bounds |
| `test_client.py` | 2 | Constants verification, base64 encoding helper |
| `test_db.py` | 25 | SQLite schema creation, CRUD, upserts, JSON fields, timestamps |
| `test_events.py` | 9 | EventBus subscribe/unsubscribe, publish to single/multiple, queue ordering |
| `test_observer.py` | 10 | NullObserver no-ops, WebObserver event writing, error resilience |
| `test_pipeline_helpers.py` | 8 | `_notify()` fire-and-forget, `_match_character_refs()` exact + partial matching |
| `test_cli.py` | 10 | `--ref` parsing, `--prompt-file` reading, missing file handling |
| `test_web.py` | 22 | All HTTP routes, JSON API, file uploads, health check, static files, SSE bus |
| `test_web_live.py` | 5 | Real uvicorn server: startup, index, create run, SSE connection, JSON API |

## Unit Tests (no server needed)

All test files except `test_web_live.py` run without starting a server. They use in-memory
SQLite databases and FastAPI's `TestClient` (synchronous, no real HTTP).

```bash
python -m pytest tests/ --tb=short -q
```

No API key or network access required. These run in CI on every push.

## Live Server Integration Tests

`test_web_live.py` starts a **real uvicorn server** on a random free port and hits it with
actual HTTP requests via `requests`. These tests are marked with `@pytest.mark.live` and
**skipped by default** in normal test runs.

```bash
# Run live tests only
python -m pytest tests/test_web_live.py -v -m live

# Run everything including live tests
python -m pytest tests/ -v -m "live or not live"
```

**Requirements:** `pip install -e ".[web]"` (needs FastAPI, uvicorn, Jinja2, python-multipart)

## Manual Server Testing

### Start the dashboard

```bash
# Dashboard only (browse past runs, launch new runs from web)
python -m grok_spicy --web

# Dashboard + pipeline
python -m grok_spicy "A fox and owl adventure" --serve

# Custom port
python -m grok_spicy --web --port 9000
```

### Verify it's running

```bash
curl http://localhost:8420/health
# Expected: {"status":"ok"}

curl http://localhost:8420/
# Expected: HTML page with run list
```

Browse to `http://localhost:8420/` for the dashboard UI.

## Two Servers — Don't Get Confused

When you run with `--serve`, **two servers** start:

| Server | Port | Purpose |
|---|---|---|
| **Prefect temporary server** | Random (e.g., 8736, 8981) | Internal workflow orchestration. Serves Prefect's own API only. |
| **Your dashboard** | 8420 (default, or `--port`) | The actual web UI with runs, forms, SSE live updates. |

Prefect prints its URL first:
```
Starting temporary server on http://127.0.0.1:8736   <-- IGNORE THIS
```

Your dashboard URL is printed right after in a banner:
```
============================================================
  DASHBOARD: http://localhost:8420                     <-- USE THIS
  (ignore the Prefect server URL above — that is internal)
============================================================
```

If you go to Prefect's port in a browser, you'll get `{"detail":"Not Found"}` because
it only serves Prefect's internal API — that's expected, it's not your dashboard.

## Common Issues

| Problem | Fix |
|---|---|
| `{"detail":"Not Found"}` at some port | You're hitting Prefect's internal server. Use port **8420** (or your `--port` value). |
| "Connection refused" | Server isn't running. Start it with `--web` or `--serve`. |
| `127.0.0.1` doesn't work but `localhost` does | They should be equivalent. Check firewall or hosts file. |
| "Module not found" for FastAPI | Install web extras: `pip install -e ".[web]"` |
| Tests fail with import errors | Run `pip install -e .` from project root first. |

## Logging

Logs are written to `output/grok_spicy.log` (DEBUG level, every decision and prompt).

Console output defaults to INFO level. Use `-v` / `--verbose` for DEBUG on the console:

```bash
python -m grok_spicy "concept" --serve -v
```

All LLM prompts (ideation, character, keyframe, video, vision checks) are logged in full
at INFO level — visible on console without needing `-v`.
