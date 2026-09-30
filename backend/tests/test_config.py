from __future__ import annotations

from backend.app.config import Settings


def test_sqlalchemy_url_rewrites_postgres_scheme():
    s = Settings(
        DATABASE_URL="postgres://u:p@host:5432/db",
        SECRET_KEY="x",
        CRM_BASIC_USER="u",
        CRM_BASIC_PASS="p",
    )
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_sqlalchemy_url_keeps_postgresql_scheme():
    s = Settings(
        DATABASE_URL="postgresql://u:p@host:5432/db",
        SECRET_KEY="x",
        CRM_BASIC_USER="u",
        CRM_BASIC_PASS="p",
    )
    assert s.sqlalchemy_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_dsn_falls_back_to_pg_parts():
    s = Settings(
        DATABASE_URL="",
        SECRET_KEY="x",
        CRM_BASIC_USER="u",
        CRM_BASIC_PASS="p",
        PGHOST="pg",
        PGPORT="5433",
        PGUSER="bob",
        PGPASSWORD="pw",
        PGDATABASE="mydb",
    )
    assert s.dsn == "postgresql://bob:pw@pg:5433/mydb"


def test_ssl_forced_by_pgssl():
    base = {"SECRET_KEY": "x", "CRM_BASIC_USER": "u", "CRM_BASIC_PASS": "p"}
    on = Settings(DATABASE_URL="postgresql://h/db", PGSSL="true", **base)
    off = Settings(DATABASE_URL="postgresql://h/db", PGSSL="false", **base)
    assert on.connect_args["ssl"] is True
    assert off.connect_args["ssl"] is False


def test_ssl_autodetect_railway_proxy():
    base = {"SECRET_KEY": "x", "CRM_BASIC_USER": "u", "CRM_BASIC_PASS": "p"}
    public = Settings(DATABASE_URL="postgresql://u@proxy.rlwy.net:1/db", **base)
    local = Settings(DATABASE_URL="postgresql://u@localhost/db", **base)
    assert public.connect_args["ssl"] is True
    assert local.connect_args["ssl"] is False


def test_locale_defaults():
    s = Settings(
        DATABASE_URL="postgresql://h/db",
        SECRET_KEY="x",
        CRM_BASIC_USER="u",
        CRM_BASIC_PASS="p",
    )
    assert s.default_timezone == "Asia/Almaty"
    assert s.default_currency == "KZT"
