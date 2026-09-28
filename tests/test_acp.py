"""ACP form elicitation bridge tests."""

from __future__ import annotations

from cactus.acp import FormBridge, InvalidElicitation
from cactus.store import Store


def test_acp_enum_is_a_blocking_labeled_cactus_row(store: Store, project: str) -> None:
    bridge = FormBridge(store, project=project, cwd=project, agent="acp-agent")
    pending = bridge.post({
        "sessionId": "sess-7",
        "mode": "form",
        "message": "Which approach?",
        "requestedSchema": {
            "type": "object",
            "properties": {"strategy": {"type": "string", "oneOf": [
                {"const": "safe", "title": "Safe"},
                {"const": "fast", "title": "Fast"},
            ]}},
        },
    })

    q = store.get(pending.key, project=project)
    assert q is not None
    assert q.blocked is True
    assert q.source == "acp"
    assert q.thread == "acp:sess-7"
    assert q.allow_free is False
    assert [c.label for c in q.choices] == ["safe", "fast"]
    assert bridge.response(pending) is None

    store.answer(q.key, project=project, selected=["fast"])
    assert bridge.wait_response(pending, timeout=0) == {
        "action": "accept", "content": {"strategy": "fast"}
    }


def test_acp_skip_and_clear_map_to_decline_and_cancel(store: Store, project: str) -> None:
    bridge = FormBridge(store, project=project, cwd=project, agent="acp-agent")
    first = bridge.post({"sessionId": "s", "mode": "form", "message": "Name?", "requestedSchema": {
        "type": "object", "properties": {"name": {"type": "string"}},
    }})
    store.answer(first.key, project=project, skipped=True)
    assert bridge.response(first) == {"action": "decline"}

    second = bridge.post({"sessionId": "s", "mode": "form", "message": "Name?", "requestedSchema": {
        "type": "object", "properties": {"name": {"type": "string"}},
    }})
    store.clear(keys=[second.key], project=project, agent="acp-agent")
    assert bridge.response(second) == {"action": "cancel"}


def test_acp_bridge_refuses_a_multi_field_form(store: Store, project: str) -> None:
    bridge = FormBridge(store, project=project, cwd=project, agent="acp-agent")
    try:
        bridge.post({"mode": "form", "message": "Two things", "requestedSchema": {
            "type": "object", "properties": {"first": {"type": "string"}, "second": {"type": "string"}},
        }})
    except InvalidElicitation as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("multi-field ACP form was accepted")
