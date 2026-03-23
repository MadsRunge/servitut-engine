from app.core.config import settings
from app.db import database


def test_uses_sqlite_detects_sqlite_urls():
    assert database.uses_sqlite("sqlite:///test.db") is True
    assert database.uses_sqlite("postgresql://postgres:postgres@localhost:5432/servitut") is False


def test_initialize_database_creates_tables_for_sqlite(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///test.db")
    calls: list[str] = []

    def fake_create_tables():
        calls.append("create_tables")

    monkeypatch.setattr(database, "create_tables", fake_create_tables)

    database.initialize_database()

    assert calls == ["create_tables"]


def test_initialize_database_skips_create_tables_for_postgres(monkeypatch):
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/servitut",
    )
    calls: list[str] = []

    def fake_create_tables():
        calls.append("create_tables")

    monkeypatch.setattr(database, "create_tables", fake_create_tables)

    database.initialize_database()

    assert calls == []
