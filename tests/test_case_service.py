import shutil
import tempfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.case_service import (
    add_document_to_case,
    create_case,
    delete_case,
    get_case,
    list_cases,
    update_case_status,
)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """Redirect storage to a temp dir for each test."""
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()
    yield tmp_path


def test_create_case():
    case = create_case("Test sag", "Testvej 1", "REF-001")
    assert case.case_id.startswith("case-")
    assert case.name == "Test sag"
    assert case.address == "Testvej 1"
    assert case.external_ref == "REF-001"
    assert case.status == "created"


def test_get_case():
    case = create_case("Hent test")
    loaded = get_case(case.case_id)
    assert loaded is not None
    assert loaded.case_id == case.case_id
    assert loaded.name == "Hent test"


def test_get_nonexistent_case():
    result = get_case("case-nonexistent")
    assert result is None


def test_list_cases():
    create_case("Sag 1")
    create_case("Sag 2")
    cases = list_cases()
    assert len(cases) == 2
    names = {c.name for c in cases}
    assert "Sag 1" in names
    assert "Sag 2" in names


def test_delete_case():
    case = create_case("Slet mig")
    result = delete_case(case.case_id)
    assert result is True
    assert get_case(case.case_id) is None


def test_delete_nonexistent_case():
    result = delete_case("case-ghost")
    assert result is False


def test_update_case_status():
    case = create_case("Status test")
    updated = update_case_status(case.case_id, "extracting")
    assert updated is not None
    assert updated.status == "extracting"
    # Verify persistence
    loaded = get_case(case.case_id)
    assert loaded.status == "extracting"


def test_add_document_to_case():
    case = create_case("Doc test")
    updated = add_document_to_case(case.case_id, "doc-abc12345")
    assert updated is not None
    assert "doc-abc12345" in updated.document_ids
    # No duplicates
    add_document_to_case(case.case_id, "doc-abc12345")
    loaded = get_case(case.case_id)
    assert loaded.document_ids.count("doc-abc12345") == 1


def test_storage_round_trip():
    case = create_case("Round trip", "Vej 42", "EXT-99")
    loaded = get_case(case.case_id)
    assert loaded.name == case.name
    assert loaded.address == case.address
    assert loaded.external_ref == case.external_ref
    assert loaded.created_at == case.created_at
