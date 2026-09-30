from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import CrmCustomField

FIELD_TYPES = ("text", "number", "date", "select", "multiselect", "bool")


def validate_field_definition_key(key: str) -> str:
    import re

    normalized = key.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{1,64}", normalized):
        raise ApiError(
            "INVALID_FIELD_KEY",
            "Field key must match [a-z0-9_]{1,64}",
            422,
        )
    return normalized


async def load_definitions(session: AsyncSession, entity: str) -> list[CrmCustomField]:
    rows = (
        await session.execute(
            select(CrmCustomField)
            .where(CrmCustomField.entity == entity)
            .order_by(CrmCustomField.sort)
        )
    ).scalars()
    return list(rows)


def validate_custom_values(
    entity: str,
    custom: dict[str, Any],
    definitions: list[CrmCustomField],
) -> dict[str, Any]:
    """Validate known fields by type; unknown keys pass through untouched.

    Unknown keys are kept because the bot sync mirrors lead attributes
    (direction, goal, ...) into the same payload (see D10).
    """
    by_key = {f.key: f for f in definitions if f.entity == entity}
    errors: dict[str, str] = {}
    for field in by_key.values():
        if field.required and (field.key not in custom or custom[field.key] is None):
            errors[field.key] = "required"
    for key, value in custom.items():
        field = by_key.get(key)
        if field is None or value is None:
            continue
        problem = _check_value(field, value)
        if problem is not None:
            errors[key] = problem
    if errors:
        raise ApiError("INVALID_CUSTOM_FIELD", "Custom field validation failed", 422, errors)
    return custom


def _check_value(field: CrmCustomField, value: Any) -> str | None:
    kind = field.type
    if kind == "text":
        return None if isinstance(value, str) else "must be a string"
    if kind == "number":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return None if ok else "must be a number"
    if kind == "bool":
        return None if isinstance(value, bool) else "must be a boolean"
    if kind == "date":
        if not isinstance(value, str):
            return "must be a YYYY-MM-DD string"
        try:
            date.fromisoformat(value)
        except ValueError:
            return "must be a YYYY-MM-DD string"
        return None
    options = field.options or []
    option_list = options if isinstance(options, list) else []
    if kind == "select":
        return None if value in option_list else f"must be one of {option_list}"
    if kind == "multiselect":
        if not isinstance(value, list) or any(v not in option_list for v in value):
            return f"must be a list of {option_list}"
        return None
    return f"unknown field type {kind}"
