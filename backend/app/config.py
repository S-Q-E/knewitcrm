from __future__ import annotations

from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = Field(default="", alias="DATABASE_URL")
    secret_key: str = Field(alias="SECRET_KEY")
    app_env: str = Field(default="local", alias="APP_ENV")
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    allowed_origins: list[str] = Field(default_factory=list, alias="ALLOWED_ORIGINS")
    default_timezone: str = Field(default="Asia/Almaty", alias="DEFAULT_TIMEZONE")
    default_currency: str = Field(default="KZT", alias="DEFAULT_CURRENCY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Step 2 bootstrap: used once to create the first admin, then ignored.
    admin_email: str = Field(default="", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")

    # Step 3 bot sync worker.
    sync_enabled: bool = Field(default=True, alias="SYNC_ENABLED")
    sync_interval_seconds: int = Field(default=5, ge=1, alias="SYNC_INTERVAL_SECONDS")

    # Step 9 manager outbox: n8n webhook that actually sends WhatsApp messages.
    n8n_send_webhook_url: str = Field(default="", alias="N8N_SEND_WEBHOOK_URL")
    n8n_webhook_secret: str = Field(default="", alias="N8N_WEBHOOK_SECRET")
    outbox_interval_seconds: int = Field(default=5, ge=1, alias="OUTBOX_INTERVAL_SECONDS")

    # How many trailing X-Forwarded-For entries are appended by our own
    # trusted proxies (outermost last). The client IP is the entry just
    # before them; 0 means "no proxy, always use the direct peer".
    trusted_proxy_hops: int = Field(default=1, ge=0, alias="TRUSTED_PROXY_HOPS")

    # Fallbacks used when DATABASE_URL is not set (local dev).
    pghost: str = Field(default="localhost", alias="PGHOST")
    pgport: str = Field(default="5432", alias="PGPORT")
    pguser: str = Field(default="postgres", alias="PGUSER")
    pgpassword: str = Field(default="", alias="PGPASSWORD")
    pgdatabase: str = Field(default="railway", alias="PGDATABASE")
    pgssl: str = Field(default="", alias="PGSSL")

    @cached_property
    def dsn(self) -> str:
        url = self.database_url or (
            f"postgresql://{self.pguser}:{self.pgpassword}"
            f"@{self.pghost}:{self.pgport}/{self.pgdatabase}"
        )
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://") :]
        return url

    @cached_property
    def sqlalchemy_url(self) -> str:
        dsn = self.dsn
        if dsn.startswith("postgresql://"):
            return "postgresql+asyncpg://" + dsn[len("postgresql://") :]
        return dsn

    @cached_property
    def connect_args(self) -> dict:
        return {"ssl": self._ssl_setting(), "command_timeout": 30}

    def _ssl_setting(self) -> bool:
        val = self.pgssl.lower()
        if val in ("1", "true", "yes"):
            return True
        if val in ("0", "false", "no"):
            return False
        # Public Railway proxy requires SSL, internal network does not.
        dsn = self.dsn
        if "proxy.rlwy.net" in dsn or "railway.app" in dsn:
            return True
        return False
