from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.config import Settings  # noqa: E402
from backend.app.migrations import VERSION_TABLE, include_object  # noqa: E402
from backend.app.models import (  # noqa: E402,F401
    CrmActivityLog,
    CrmAutomation,
    CrmContact,
    CrmConversationState,
    CrmCustomField,
    CrmDeal,
    CrmDealStageHistory,
    CrmEntityTag,
    CrmImport,
    CrmLostReason,
    CrmNote,
    CrmNotification,
    CrmOutbox,
    CrmPipeline,
    CrmQuickReply,
    CrmSavedView,
    CrmSession,
    CrmSetting,
    CrmStage,
    CrmTag,
    CrmTask,
    CrmUser,
)
from backend.app.models.base import Base  # noqa: E402

config = context.config
settings = Settings()

# Serializes concurrent `upgrade head` runs (several containers booting at
# once after a deploy). Same numeric namespace as the worker locks
# (91030001-91030003 in workers/); this key is used only here.
MIGRATION_LOCK_KEY = 91030000


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.sqlalchemy_url, connect_args=settings.connect_args)
    try:
        # The lock holder migrates; the rest block here and no-op after.
        # Session-level lock on its own connection, released explicitly
        # (and implicitly when the connection closes).
        async with engine.connect() as lock_connection:
            await lock_connection.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_KEY})"))
            try:
                async with engine.connect() as connection:
                    await connection.run_sync(do_run_migrations)
            finally:
                await lock_connection.execute(
                    text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_KEY})")
                )
    finally:
        await engine.dispose()


asyncio.run(run_migrations_online())
