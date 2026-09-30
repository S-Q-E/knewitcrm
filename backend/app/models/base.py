from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base for all crm_* tables. Business models land in later steps."""

    pass
