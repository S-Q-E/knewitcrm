from __future__ import annotations

import pytest
from asgi_lifespan import LifespanManager

from backend.app.config import Settings
from backend.app.main import create_app

pytestmark = pytest.mark.usefixtures("db_available")


def _settings(**overrides) -> Settings:
    base: dict = {
        "cookie_secure": False,
        "sync_enabled": True,
        "outbox_enabled": True,
        "notifications_enabled": True,
        "realtime_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


async def test_disabling_one_worker_keeps_others_running():
    app = create_app(_settings(outbox_enabled=False))
    async with LifespanManager(app):
        assert app.state.sync_task is not None
        assert app.state.outbox_task is None
        assert app.state.notify_task is not None
        assert app.state.realtime_task is not None

    app = create_app(
        _settings(sync_enabled=False, notifications_enabled=False, realtime_enabled=False)
    )
    async with LifespanManager(app):
        assert app.state.sync_task is None
        assert app.state.outbox_task is not None
        assert app.state.notify_task is None
        assert app.state.realtime_task is None
