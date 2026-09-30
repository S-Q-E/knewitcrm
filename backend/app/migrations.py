from __future__ import annotations

VERSION_TABLE = "crm_alembic_version"
CRM_PREFIX = "crm_"


def include_object(obj, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    """Alembic sees only crm_* objects, never knewit_* or other n8n tables."""
    if type_ == "table":
        return bool(name) and name.startswith(CRM_PREFIX)
    table = getattr(obj, "table", None)
    if table is not None:
        return table.name.startswith(CRM_PREFIX)
    return True
