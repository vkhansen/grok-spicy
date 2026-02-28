"""Live server integration tests — start a real uvicorn server and hit it with HTTP.

These tests are marked with @pytest.mark.live so they don't run in normal CI.
Run them explicitly:

    pytest tests/test_web_live.py -v -m live
"""

import socket
import threading
import time

import pytest
import requests
import uvicorn

from grok_spicy.db import init_db, insert_run
from grok_spicy.web import app, set_db

pytestmark = pytest.mark.live


def _free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live_server():
    """Start uvicorn on a random free port, yield the base URL, then shut down."""
    conn = init_db(":memory:")
    set_db(conn)

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to start accepting connections
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            requests.get(f"{base_url}/health", timeout=0.5)
            break
        except requests.ConnectionError:
            time.sleep(0.1)
    else:
        pytest.fail("Live server did not start within 5 seconds")

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)
    conn.close()
    set_db(None)


def test_live_server_starts_and_responds(live_server):
    """GET /health returns 200 with status ok."""
    resp = requests.get(f"{live_server}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_live_server_index_page(live_server):
    """GET / returns HTML."""
    resp = requests.get(f"{live_server}/", timeout=5)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Grok Spicy" in resp.text


def test_live_server_create_and_view_run(live_server):
    """POST /api/runs creates a run and redirects to the run page."""
    resp = requests.post(
        f"{live_server}/api/runs",
        data={"concept": "Live test concept"},
        allow_redirects=False,
        timeout=5,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/run/")

    # Follow the redirect manually
    run_resp = requests.get(f"{live_server}{location}", timeout=5)
    assert run_resp.status_code == 200


def test_live_server_sse_connection(live_server):
    """Connect to /sse/{id}, verify SSE headers."""
    from grok_spicy.events import Event
    from grok_spicy.web import event_bus, get_db

    conn = get_db()
    run_id = insert_run(conn, "sse live test")

    # Publish a complete event so the stream terminates
    event_bus.publish(Event(type="complete", run_id=run_id, data={"done": True}))

    resp = requests.get(
        f"{live_server}/sse/{run_id}",
        stream=True,
        timeout=5,
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    resp.close()


def test_live_server_api_runs_json(live_server):
    """GET /api/runs returns JSON list."""
    resp = requests.get(f"{live_server}/api/runs", timeout=5)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
