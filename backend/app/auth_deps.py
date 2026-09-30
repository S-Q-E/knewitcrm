from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Request

from .errors import ApiError
from .models import ROLE_ADMIN


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def get_current_user(request: Request) -> CurrentUser | None:
    return getattr(request.state, "current_user", None)


def require_user(request: Request) -> CurrentUser:
    user = get_current_user(request)
    if user is None:
        raise ApiError("UNAUTHORIZED", "Authentication required", 401)
    return user


def require_role(role: str):
    def _check(request: Request) -> CurrentUser:
        user = require_user(request)
        if user.role != role:
            raise ApiError("FORBIDDEN", "Insufficient permissions", 403)
        return user

    return _check
