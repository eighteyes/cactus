"""Bridge ACP form elicitations onto Cactus's blocking question queue.

An ACP client owns the JSON-RPC transport.  It gives each incoming
``elicitation/create`` form request to :class:`FormBridge`, keeps the ACP
request open, then returns ``response`` when the Cactus row is answered.
This module deliberately has no transport of its own: embedding it in an ACP
host avoids competing with the editor/client that already owns the connection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .store import Choice, Question, Store


class InvalidElicitation(ValueError):
    """The request cannot be represented safely by the first Cactus bridge."""


@dataclass(frozen=True)
class PendingElicitation:
    """The durable Cactus identity for one outstanding ACP request."""

    key: str
    project: str
    field: str
    values: dict[str, Any] | None
    value_type: str


def _label(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


class FormBridge:
    """Turn a single-field ACP form into a blocking, visibly ACP Cactus row.

    ACP forms may contain multiple fields.  Cactus's present answer surface is
    one field per row, so this deliberately rejects multi-field forms instead
    of silently flattening them into an ambiguous text prompt.  An embedding
    client must advertise form support only when it applies this bridge to the
    supported single-field subset.
    """

    def __init__(self, store: Store, *, project: str, cwd: str, agent: str) -> None:
        self.store = store
        self.project = project
        self.cwd = cwd
        self.agent = agent

    def post(self, params: dict[str, Any]) -> PendingElicitation:
        if params.get("mode") != "form":
            raise InvalidElicitation("Cactus ACP bridge supports form mode only")
        message = params.get("message")
        schema = params.get("requestedSchema")
        if not isinstance(message, str) or not message.strip():
            raise InvalidElicitation("form elicitation needs a non-empty message")
        if not isinstance(schema, dict) or schema.get("type", "object") != "object":
            raise InvalidElicitation("requestedSchema must be an object")
        properties = schema.get("properties")
        if not isinstance(properties, dict) or len(properties) != 1:
            raise InvalidElicitation("Cactus ACP bridge currently requires exactly one form field")
        field, prop = next(iter(properties.items()))
        if not isinstance(field, str) or not isinstance(prop, dict):
            raise InvalidElicitation("form field must be a named schema object")

        value_type = prop.get("type", "string")
        if value_type not in ("string", "number", "integer", "boolean"):
            raise InvalidElicitation(f"unsupported ACP field type: {value_type!r}")
        values = self._values(prop)
        choices = [Choice(label, str(prop.get("description") or "")) for label in values] if values else []
        context = self._context(schema, field, prop)
        scope = params.get("sessionId") or params.get("requestId") or "request"
        q = self.store.ask(
            message,
            project=self.project,
            cwd=self.cwd,
            kind="choice" if choices else "text",
            act="ask",
            agent=self.agent,
            blocked=True,
            source="acp",
            thread=f"acp:{scope}",
            choices=choices,
            allow_free=not choices,
            context=context,
            asked_by="ACP",
        )
        return PendingElicitation(q.key, self.project, field, values or None, value_type)

    @staticmethod
    def _values(prop: dict[str, Any]) -> dict[str, Any]:
        raw = prop.get("enum")
        if raw is None:
            options = prop.get("oneOf", prop.get("anyOf"))
            if options is not None:
                if not isinstance(options, list) or not all(isinstance(v, dict) and "const" in v for v in options):
                    raise InvalidElicitation("oneOf/anyOf options must each provide const")
                raw = [v["const"] for v in options]
        if raw is None:
            return {}
        if not isinstance(raw, list) or not raw:
            raise InvalidElicitation("enum must be a non-empty list")
        values = {_label(value): value for value in raw}
        if len(values) != len(raw):
            raise InvalidElicitation("enum choices must have distinct values")
        return values

    @staticmethod
    def _context(schema: dict[str, Any], field: str, prop: dict[str, Any]) -> str:
        lines = [f"ACP response field: {field}"]
        if isinstance(schema.get("title"), str):
            lines.append(schema["title"])
        if isinstance(schema.get("description"), str):
            lines.append(schema["description"])
        if isinstance(prop.get("title"), str):
            lines.append(prop["title"])
        if isinstance(prop.get("description"), str):
            lines.append(prop["description"])
        return "\n".join(lines)

    def response(self, pending: PendingElicitation) -> dict[str, Any] | None:
        """Return an ACP result once the row is resolved, else ``None``.

        A skipped Cactus row is an explicit decline; a cleared row is a cancel.
        """
        q = self.store.get(pending.key, project=pending.project)
        if q is None:
            raise KeyError(f"Cactus row disappeared: {pending.key}")
        if q.status in ("open", "elaborate"):
            return None
        if q.status == "cleared":
            return {"action": "cancel"}
        if q.answer is None or q.answer.skipped:
            return {"action": "decline"}
        return {"action": "accept", "content": {pending.field: self._answer_value(q, pending)}}

    def wait_response(
        self, pending: PendingElicitation, *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        """Wait for the Cactus answer, exactly as ACP waits for its response.

        ``None`` means the caller's own timeout elapsed; a resolved row always
        maps to one of ACP's explicit accept/decline/cancel actions.
        """
        resolved = self.store.wait_for_answer(
            pending.key, project=pending.project, timeout=timeout
        )
        return self.response(pending) if resolved is not None else None

    @staticmethod
    def _answer_value(q: Question, pending: PendingElicitation) -> Any:
        if pending.values is not None:
            if len(q.answer.selected) != 1:
                raise InvalidElicitation("an ACP choice row needs one selected value")
            return pending.values[q.answer.selected[0]]
        raw = (q.answer.text or "").strip()
        if pending.value_type == "string":
            return raw
        if pending.value_type == "integer":
            return int(raw)
        if pending.value_type == "number":
            return float(raw)
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        raise InvalidElicitation("boolean ACP fields must be answered true or false")
