import pytest

from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.case import Case
from app.models.document import Document, PageData
from app.models.servitut import Servitut
from app.services import matrikel_service, storage_service


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


def test_parse_matrikler_from_text_extracts_unique_entries():
    text = """
    Landsejerlav: Aalborg Markjorder
    Matrikelnummer: 0005ay
    Areal: 20033 m2
    Landsejerlav: Aalborg Bygrunde
    Matrikelnummer: 0518p
    Areal: 30 m2
    Landsejerlav: Aalborg Markjorder
    Matrikelnummer: 0005ay
    Areal: 20033 m2
    """

    parcels = matrikel_service.parse_matrikler_from_text(text)

    assert [m.parcel_number for m in parcels] == ["0005ay", "0518p"]
    assert parcels[0].cadastral_district == "Aalborg Markjorder"
    assert parcels[0].area_sqm == 20033


def test_sync_case_matrikler_sets_default_target(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        case = Case(case_id="case-test", name="Test sag")
        storage_service.save_case(session, case)
        storage_service.save_document(
            session,
            Document(
                document_id="doc-attest",
                case_id="case-test",
                filename="Tinglysningsattest.pdf",
                file_path="storage/cases/case-test/documents/doc-attest/original.pdf",
                document_type="tinglysningsattest",
            )
        )
        storage_service.save_ocr_pages(
            session,
            "case-test",
            "doc-attest",
            [
                PageData(
                    page_number=1,
                    text=(
                        "Landsejerlav: Aalborg Markjorder\n"
                        "Matrikelnummer: 0005ay\n"
                        "Areal: 20033 m2\n"
                        "Landsejerlav: Aalborg Bygrunde\n"
                        "Matrikelnummer: 0518p\n"
                        "Areal: 30 m2"
                    ),
                ),
            ],
        )

        updated = matrikel_service.sync_case_matrikler(session, "case-test")

    assert updated is not None
    assert [m.parcel_number for m in updated.parcels] == ["0005ay", "0518p"]
    assert updated.primary_parcel_number == "0005ay"


def test_resolve_target_matrikel_scope_is_deterministic():
    assert matrikel_service.resolve_target_matrikel_scope(["0005ay", "0518p"], ["0005ay"]) is True
    assert matrikel_service.resolve_target_matrikel_scope(["0518p"], ["0005ay"]) is False
    assert matrikel_service.resolve_target_matrikel_scope([], ["0005ay"]) is None


def test_resolve_target_matrikel_scope_multi_matrikel():
    # Matches when any target matrikel is in applies_to_parcel_numbers
    assert matrikel_service.resolve_target_matrikel_scope(["1o"], ["1o", "1v"]) is True
    assert matrikel_service.resolve_target_matrikel_scope(["1v"], ["1o", "1v"]) is True
    assert matrikel_service.resolve_target_matrikel_scope(["38b"], ["1o", "1v"]) is False
    assert matrikel_service.resolve_target_matrikel_scope([], ["1o", "1v"]) is None


def test_resolve_target_matrikel_scope_normalizes_zero_padded_values():
    assert matrikel_service.resolve_target_matrikel_scope(["69f"], ["0069f"]) is True
    assert (
        matrikel_service.resolve_target_matrikel_scope(
            ["38b"],
            ["0001o", "0001v"],
            available_parcel_numbers=["0038b", "0001o", "0001v"],
        )
        is False
    )
    assert (
        matrikel_service.resolve_target_matrikel_scope(
            ["22a"],
            ["0001o", "0001v"],
            available_parcel_numbers=["0022a", "0001o", "0001v"],
        )
        is False
    )


def test_resolve_matching_target_matrikler_preserves_target_format():
    matches = matrikel_service.resolve_matching_target_matrikler(
        ["1o", "1v"],
        ["0001o", "0001v"],
    )

    assert matches == ["0001o", "0001v"]


def test_filter_servitutter_for_target_accepts_single_target_string():
    servitutter = [
        Servitut(
            easement_id="srv-1",
            case_id="case-test",
            source_document="doc-1",
            applies_to_parcel_numbers=["0005ay"],
        )
    ]
    filtered = matrikel_service.filter_servitutter_for_target(servitutter, "0005ay")

    assert len(filtered) == 1
    assert filtered[0].applies_to_primary_parcel is True


def test_update_target_matrikel_accepts_unpadded_match(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        case = Case(
            case_id="case-test",
            name="Test sag",
            parcels=[
                {"parcel_number": "0001o", "cadastral_district": "Test By"},
                {"parcel_number": "0001v", "cadastral_district": "Test By"},
            ],
        )
        storage_service.save_case(session, case)

        updated = matrikel_service.update_target_matrikel(session, "case-test", "1o")

    assert updated is not None
    assert updated.primary_parcel_number == "0001o"


def test_list_documents_is_metadata_only_by_default(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        case = Case(case_id="case-test", name="Test sag")
        storage_service.save_case(session, case)
        storage_service.save_document(
            session,
            Document(
                document_id="doc-attest",
                case_id="case-test",
                filename="Tinglysningsattest.pdf",
                file_path="storage/cases/case-test/documents/doc-attest/original.pdf",
                document_type="tinglysningsattest",
                page_count=2,
                chunk_count=3,
                ocr_blank_pages=1,
                ocr_low_conf_pages=0,
                parse_status="ocr_done",
            )
        )
        storage_service.save_ocr_pages(
            session,
            "case-test",
            "doc-attest",
            [
                PageData(page_number=1, text="A", confidence=0.9),
                PageData(page_number=2, text="", confidence=0.0),
            ],
        )

        docs = storage_service.list_documents(session, "case-test")
        full_doc = storage_service.load_document(session, "case-test", "doc-attest")

    assert len(docs) == 1
    assert docs[0].pages == []
    assert docs[0].page_count == 2
    assert docs[0].chunk_count == 3
    assert docs[0].ocr_blank_pages == 1
    assert len(full_doc.pages) == 2
