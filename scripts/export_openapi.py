"""Dump the FastAPI OpenAPI schema to a JSON file (for frontend type generation)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Type generation never touches the DB; dummy values satisfy required settings.
os.environ.setdefault("SECRET_KEY", "openapi-export")
os.environ.setdefault("ADMIN_EMAIL", "export@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "export-password-1")

from backend.app.main import create_app  # noqa: E402


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "frontend" / "openapi.json"
    schema = create_app().openapi()
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
