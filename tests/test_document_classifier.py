from app.models.document import PageData
from app.services.document_classifier import classify_document, validate_document_type


def test_validate_document_type_accepts_known_types():
    assert validate_document_type("akt") == "akt"
    assert validate_document_type("tinglysningsattest") == "tinglysningsattest"


def test_classify_document_prefers_explicit_type():
    pages = [PageData(page_number=1, text="Tinglysningsattest Matrikelnummer: 0005ay")]
    assert classify_document("ukendt.pdf", pages=pages, requested_type="akt") == "akt"


def test_classify_document_detects_tinglysningsattest_from_text():
    pages = [
        PageData(
            page_number=1,
            text="Tinglysningsattest\nLandsejerlav: Aalborg Markjorder\nMatrikelnummer: 0005ay",
        )
    ]
    assert classify_document("scan.pdf", pages=pages) == "tinglysningsattest"


def test_classify_document_detects_tinglysningsattest_from_filename():
    assert classify_document("Min Tinglysningsattest.pdf") == "tinglysningsattest"


def test_classify_document_defaults_to_akt():
    pages = [PageData(page_number=1, text="Deklaration vedrørende færdselsret og servitut.")]
    assert classify_document("bilag.pdf", pages=pages) == "akt"
