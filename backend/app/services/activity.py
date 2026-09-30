from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrmActivityLog

_SLIM_FIELDS = (
    "name",
    "title",
    "email",
    "phone",
    "whatsapp_id",
    "status",
    "stage_id",
    "pipeline_id",
    "owner_id",
    "role",
    "is_active",
    "body",
    "pinned",
    "label",
    "key",
    "type",
    "kind",
    "sort",
    "color",
)


def slim(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep a small JSON-safe snapshot for the activity diff."""
    out: dict[str, Any] = {}
    for name in _SLIM_FIELDS:
        if name in payload:
            out[name] = _json_safe(payload[name])
    if "custom" in payload and isinstance(payload["custom"], dict):
        out["custom"] = {k: _json_safe(v) for k, v in payload["custom"].items()}
    return out


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def diff_payload(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """Diff two slim snapshots: {field: {old, new}} plus created/deleted markers."""
    old = old or {}
    new = new or {}
    if not old:
        return {"created": slim(new)}
    if not new:
        return {"deleted": slim(old)}
    changed: dict[str, Any] = {}
    for name in sorted(set(old) | set(new)):
        before = _json_safe(old.get(name))
        after = _json_safe(new.get(name))
        if before != after:
            changed[name] = {"old": before, "new": after}
    return {"changed": changed}


async def log_activity(
    session: AsyncSession,
    actor_id: uuid.UUID | None,
    entity: str,
    entity_id: uuid.UUID | None,
    action: str,
    diff: dict[str, Any] | None = None,
) -> CrmActivityLog:
    entry = CrmActivityLog(
        actor_id=actor_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        diff={k: _json_safe(v) for k, v in (diff or {}).items()},
    )
    session.add(entry)
    return entry
