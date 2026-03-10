from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.services.case_service import create_case


client = TestClient(app)


def test_upload_document_accepts_explicit_document_type(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()

    case = create_case("API upload")

    response = client.post(
        f"/cases/{case.case_id}/documents",
        files={"file": ("attest.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"document_type": "tinglysningsattest"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document_type"] == "tinglysningsattest"


def test_upload_document_infers_tinglysningsattest_from_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    (tmp_path / "cases").mkdir()

    case = create_case("API upload infer")

    response = client.post(
        f"/cases/{case.case_id}/documents",
        files={"file": ("Min Tinglysningsattest.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document_type"] == "tinglysningsattest"
