"""Validate generated n8n workflow JSON before import.

Checks: valid JSON, non-empty workflow name, unique node ids and names, every
connection source/target points to an existing node.

Run: python scripts/validate_workflow.py [file ...]
Default: the three Phase 4 workflow files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = (
    ROOT / "docs" / "n8n" / "tcs-send-message-telegram.workflow.json",
    ROOT / "workflows" / "tcs_bot.json",
    ROOT / "workflows" / "tcs_reminders.json",
)


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return [f"{path}: top level must be an object"]

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{path}: missing workflow name")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return errors + [f"{path}: 'nodes' must be a non-empty list"]

    ids: set[str] = set()
    names: set[str] = set()
    for node in nodes:
        node_name = node.get("name")
        node_id = node.get("id")
        if not isinstance(node_name, str) or not node_name:
            errors.append(f"{path}: node without a name: {node!r}")
            continue
        if not node.get("type"):
            errors.append(f"{path}: node {node_name!r} has no type")
        if isinstance(node_id, str) and node_id:
            if node_id in ids:
                errors.append(f"{path}: duplicate node id {node_id!r}")
            ids.add(node_id)
        else:
            errors.append(f"{path}: node {node_name!r} has no id")
        if node_name in names:
            errors.append(f"{path}: duplicate node name {node_name!r}")
        names.add(node_name)

    connections = data.get("connections", {})
    if not isinstance(connections, dict):
        return errors + [f"{path}: 'connections' must be an object"]
    for source, outputs in connections.items():
        if source not in names:
            errors.append(f"{path}: connections reference unknown source {source!r}")
        if not isinstance(outputs, dict):
            errors.append(f"{path}: connections for {source!r} must be an object")
            continue
        for output_type, branches in outputs.items():
            if not isinstance(branches, list):
                errors.append(f"{path}: {source!r}.{output_type} must be a list")
                continue
            for branch in branches:
                for target in branch or []:
                    target_name = target.get("node")
                    if target_name not in names:
                        errors.append(f"{path}: {source!r} -> unknown target {target_name!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    files = [Path(arg) for arg in args] or list(DEFAULT_FILES)
    failed = False
    for path in files:
        errors = validate(path)
        if errors:
            failed = True
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            print(f"OK: {path} ({len(data['nodes'])} nodes)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
