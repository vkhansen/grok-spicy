# Testing Guide

## Unit Tests

Run all unit tests (no server, no API key needed):

```bash
python -m pytest tests/ --tb=short -q
```

Run a specific test file:

```bash
python -m pytest tests/test_web.py -v
```

## Live Server Integration Tests

These tests start a real uvicorn server on a random port and hit it with HTTP requests.
They are marked with `@pytest.mark.live` and **skipped by default** in normal test runs.

```bash
# Run live tests only
python -m pytest tests/test_web_live.py -v -m live

# Run everything including live tests
python -m pytest tests/ -v -m "live or not live"
```

**Requirements:** `pip install -e ".[web]"` (needs FastAPI, uvicorn, etc.)

## Manual Server Testing

Start the dashboard server:

```bash
python -m grok_spicy --web --port 8420
```

Verify it's running:

```bash
curl http://localhost:8420/health
# Expected: {"status":"ok"}
```

Browse to `http://localhost:8420/` for the dashboard.

## Common Issues

| Problem | Fix |
|---|---|
| "Connection refused" on port 8505 | Default port is **8420**, not 8505. Use `--port 8505` if you want that port. |
| Can't connect to `127.0.0.1` | The server binds to `0.0.0.0` — try `localhost` or `127.0.0.1`. Check firewall. |
| "Module not found" for FastAPI | Install web extras: `pip install -e ".[web]"` |
| Tests fail with import errors | Ensure `pip install -e .` was run from project root |
