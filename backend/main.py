"""Backward-compatible entrypoint, use backend.app.main:app instead."""

from .app.main import app  # noqa: F401
