"""Unit tests for the thread-safe EventBus."""

import asyncio

from grok_spicy.events import Event, EventBus

# ─── Event dataclass ─────────────────────────────────────────


def test_event_defaults():
    e = Event(type="plan", run_id=1)
    assert e.type == "plan"
    assert e.run_id == 1
    assert e.data == {}


def test_event_with_data():
    e = Event(type="character", run_id=2, data={"name": "Fox"})
    assert e.data["name"] == "Fox"


# ─── EventBus subscribe/unsubscribe ─────────────────────────


def test_subscribe_returns_queue():
    bus = EventBus()
    q = bus.subscribe()
    assert isinstance(q, asyncio.Queue)


def test_unsubscribe_removes_queue():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    assert q not in bus._subscribers


def test_unsubscribe_nonexistent_is_safe():
    bus = EventBus()
    q = asyncio.Queue()
    bus.unsubscribe(q)  # should not raise


# ─── EventBus publish ────────────────────────────────────────


def test_publish_delivers_to_subscriber():
    bus = EventBus()
    q = bus.subscribe()
    event = Event(type="plan", run_id=1, data={"title": "Test"})
    bus.publish(event)
    assert q.qsize() == 1
    received = q.get_nowait()
    assert received.type == "plan"
    assert received.data["title"] == "Test"


def test_publish_delivers_to_multiple_subscribers():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    event = Event(type="complete", run_id=1)
    bus.publish(event)
    assert q1.qsize() == 1
    assert q2.qsize() == 1


def test_publish_after_unsubscribe():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.unsubscribe(q1)
    bus.publish(Event(type="test", run_id=1))
    assert q1.qsize() == 0
    assert q2.qsize() == 1


def test_publish_no_subscribers():
    bus = EventBus()
    bus.publish(Event(type="test", run_id=1))  # should not raise


def test_multiple_events_queued():
    bus = EventBus()
    q = bus.subscribe()
    bus.publish(Event(type="a", run_id=1))
    bus.publish(Event(type="b", run_id=1))
    bus.publish(Event(type="c", run_id=1))
    assert q.qsize() == 3
    assert q.get_nowait().type == "a"
    assert q.get_nowait().type == "b"
    assert q.get_nowait().type == "c"
