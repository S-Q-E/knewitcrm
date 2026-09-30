from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from backend.app.migrations import VERSION_TABLE, include_object

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_version_table_name():
    assert VERSION_TABLE == "crm_alembic_version"


def test_include_object_allows_crm_tables():
    assert include_object(None, "crm_users", "table", False, None) is True
    assert include_object(None, "crm_alembic_version", "table", False, None) is True


def test_include_object_blocks_bot_and_foreign_tables():
    assert include_object(None, "knewit_leads", "table", True, None) is False
    assert include_object(None, "knewit_messages", "table", True, None) is False
    assert include_object(None, "knewit_events", "table", True, None) is False
    assert include_object(None, "knewit_followups", "table", True, None) is False
    assert include_object(None, "n8n_workflows", "table", True, None) is False


def test_include_object_indexes_follow_parent_table():
    crm_index = SimpleNamespace(table=SimpleNamespace(name="crm_deals"))
    bot_index = SimpleNamespace(table=SimpleNamespace(name="knewit_messages"))
    assert include_object(crm_index, "ix_crm_deals_x", "index", True, None) is True
    assert include_object(bot_index, "idx_messages_x", "index", True, None) is False


def test_baseline_migration_is_empty():
    path = REPO_ROOT / "backend" / "alembic" / "versions" / "0001_baseline.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert funcs["upgrade"].body and all(isinstance(s, ast.Pass) for s in funcs["upgrade"].body)
    assert funcs["downgrade"].body and all(isinstance(s, ast.Pass) for s in funcs["downgrade"].body)
    source = path.read_text(encoding="utf-8")
    assert "create_table" not in source
    assert "knewit_" not in source


def test_env_uses_crm_version_table_and_filter():
    source = (REPO_ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "VERSION_TABLE" in source
    assert "include_object" in source
