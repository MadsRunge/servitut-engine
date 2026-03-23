import pytest

from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.services.case_service import (
    add_document_to_case,
    create_case,
    delete_case,
    get_case,
    list_cases,
    update_target_matrikel,
    update_case_status,
)


@pytest.fixture(autouse=True)
def db_env(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()
    reset_engine_cache()
    create_tables()
    yield tmp_path
    reset_engine_cache()


def test_create_case():
    with get_session_ctx() as session:
        case = create_case(session, "Test sag", "Testvej 1", "REF-001")
        assert case.case_id.startswith("case-")
        assert case.name == "Test sag"
        assert case.address == "Testvej 1"
        assert case.external_ref == "REF-001"
        assert case.status == "created"

def test_get_case():
    with get_session_ctx() as session:
        case = create_case(session, "Hent test")
        loaded = get_case(session, case.case_id)
        assert loaded is not None
        assert loaded.case_id == case.case_id
        assert loaded.name == "Hent test"


def test_get_nonexistent_case():
    with get_session_ctx() as session:
        result = get_case(session, "case-nonexistent")
        assert result is None


def test_list_cases():
    with get_session_ctx() as session:
        create_case(session, "Sag 1")
        create_case(session, "Sag 2")
        cases = list_cases(session)
        assert len(cases) == 2
        names = {c.name for c in cases}
        assert "Sag 1" in names
        assert "Sag 2" in names


def test_delete_case():
    with get_session_ctx() as session:
        case = create_case(session, "Slet mig")
        result = delete_case(session, case.case_id)
        assert result is True
        assert get_case(session, case.case_id) is None


def test_delete_nonexistent_case():
    with get_session_ctx() as session:
        result = delete_case(session, "case-ghost")
        assert result is False


def test_update_case_status():
    with get_session_ctx() as session:
        case = create_case(session, "Status test")
        updated = update_case_status(session, case.case_id, "extracting")
        assert updated is not None
        assert updated.status == "extracting"
        loaded = get_case(session, case.case_id)
        assert loaded.status == "extracting"


def test_add_document_to_case():
    with get_session_ctx() as session:
        case = create_case(session, "Doc test")
        updated = add_document_to_case(session, case.case_id, "doc-abc12345")
        assert updated is not None
        assert updated.document_ids == []


def test_storage_round_trip():
    with get_session_ctx() as session:
        case = create_case(session, "Round trip", "Vej 42", "EXT-99")
        loaded = get_case(session, case.case_id)
        assert loaded.name == case.name
        assert loaded.address == case.address
        assert loaded.external_ref == case.external_ref
        assert loaded.created_at == case.created_at


def test_update_target_matrikel():
    with get_session_ctx() as session:
        case = create_case(session, "Matrikel test")
        case.matrikler = []
        loaded = update_target_matrikel(session, case.case_id, "0005ay")
        assert loaded is not None
        assert loaded.target_matrikel == "0005ay"
