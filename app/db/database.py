from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings


@lru_cache(maxsize=4)
def _build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=False, connect_args=connect_args)


def get_engine():
    return _build_engine(settings.DATABASE_URL)


def reset_engine_cache() -> None:
    _build_engine.cache_clear()


def uses_sqlite(database_url: str | None = None) -> bool:
    url = database_url or settings.DATABASE_URL
    return url.startswith("sqlite")


def create_tables() -> None:
    """Opretter alle tabeller defineret i app/db/models.py (idempotent)."""
    # Sørg for at alle tabelmodeller er importeret, inden SQLModel.metadata køres
    from app.db import models  # noqa: F401
    from app.models import user  # noqa: F401

    SQLModel.metadata.create_all(get_engine())


def initialize_database() -> None:
    """Initialiser lokale SQLite-miljøer. PostgreSQL styres via Alembic migrations."""
    if uses_sqlite():
        create_tables()


def check_database_connection() -> tuple[bool, str | None]:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:
        return False, str(exc)


def get_session():
    """FastAPI Depends-generator. Giver én session per request."""
    with Session(get_engine()) as session:
        yield session


@contextmanager
def get_session_ctx():
    """Kontekst-manager til brug uden for FastAPI (Streamlit, baggrundstråde)."""
    with Session(get_engine()) as session:
        yield session
