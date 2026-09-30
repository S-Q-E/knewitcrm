from __future__ import annotations

import base64
import secrets
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .errors import error_payload
from .logging_utils import request_id_ctx


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        request_id_ctx.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Temporary step 0 protection, removed in step 2."""

    def __init__(self, app, username: str, password: str, public_paths: set[str]) -> None:
        super().__init__(app)
        self._username = username
        self._password = password
        self._public_paths = public_paths

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._public_paths:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("basic "):
            return self._unauthorized()
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
        except Exception:
            return self._unauthorized()
        username, sep, password = decoded.partition(":")
        if not sep:
            return self._unauthorized()
        user_ok = secrets.compare_digest(username, self._username)
        pass_ok = secrets.compare_digest(password, self._password)
        if not (user_ok and pass_ok):
            return self._unauthorized()
        return await call_next(request)

    def _unauthorized(self) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=error_payload("UNAUTHORIZED", "Unauthorized"),
            headers={"WWW-Authenticate": 'Basic realm="KnewIT CRM"'},
        )
