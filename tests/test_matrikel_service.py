from app.models.case import Case
from app.models.document import Document, PageData
from app.services import matrikel_service, storage_service


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

    matrikler = matrikel_service.parse_matrikler_from_text(text)

    assert [m.matrikelnummer for m in matrikler] == ["0005ay", "0518p"]
    assert matrikler[0].landsejerlav == "Aalborg Markjorder"
    assert matrikler[0].areal_m2 == 20033


def test_sync_case_matrikler_sets_default_target(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()

    case = Case(case_id="case-test", name="Test sag")
    storage_service.save_case(case)
    storage_service.save_document(
        Document(
            document_id="doc-attest",
            case_id="case-test",
            filename="Tinglysningsattest.pdf",
            file_path="storage/cases/case-test/documents/doc-attest/original.pdf",
            document_type="tinglysningsattest",
        )
    )
    storage_service.save_ocr_pages(
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
            )
        ],
    )

    updated = matrikel_service.sync_case_matrikler("case-test")

    assert updated is not None
    assert [m.matrikelnummer for m in updated.matrikler] == ["0005ay", "0518p"]
    assert updated.target_matrikel == "0005ay"


def test_resolve_target_matrikel_scope_is_deterministic():
    assert matrikel_service.resolve_target_matrikel_scope(["0005ay", "0518p"], "0005ay") is True
    assert matrikel_service.resolve_target_matrikel_scope(["0518p"], "0005ay") is False
    assert matrikel_service.resolve_target_matrikel_scope([], "0005ay") is None
