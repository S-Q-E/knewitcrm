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

    # Step 0 temporary protection, removed in step 2.
    basic_user: str = Field(alias="CRM_BASIC_USER")
    basic_pass: str = Field(alias="CRM_BASIC_PASS")

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
