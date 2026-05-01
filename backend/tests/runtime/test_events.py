from __future__ import annotations

import json

from app.agent_framework.runtime import cancelled_event, done_event, error_event, format_sse


def test_cancelled_event_type_and_payload():
    event = cancelled_event("stopped")
    assert event.type == "cancelled"
    assert event.data == {"status": "cancelled", "reason": "stopped"}


def test_format_sse_outputs_valid_event_and_json_data():
    event = cancelled_event("stopped")
    payload = format_sse(event)

    assert payload.startswith("event: cancelled\n")
    assert payload.endswith("\n\n")
    data_line = next(line for line in payload.splitlines() if line.startswith("data: "))
    parsed = json.loads(data_line.removeprefix("data: "))
    assert parsed["type"] == "cancelled"
    assert parsed["data"]["reason"] == "stopped"


def test_done_and_error_events_unchanged():
    assert done_event().type == "done"
    error = error_event("boom")
    assert error.type == "error"
    assert error.data["message"] == "boom"
