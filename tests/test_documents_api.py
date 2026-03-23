from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.document import Document
from app.services.auth_service import build_access_token, create_user
from app.services import storage_service
from app.services.case_service import add_document_to_case, create_case


client = TestClient(app)


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


def test_upload_document_accepts_explicit_document_type(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        user = create_user(session, email="upload-explicit@example.com", password="secret123")
        case = create_case(session, "API upload", user_id=user.id)
        token = build_access_token(user)

    response = client.post(
        f"/cases/{case.case_id}/documents",
        files={"file": ("attest.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"document_type": "tinglysningsattest"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document_type"] == "tinglysningsattest"


def test_upload_document_infers_tinglysningsattest_from_filename(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        user = create_user(session, email="upload-infer@example.com", password="secret123")
        case = create_case(session, "API upload infer", user_id=user.id)
        token = build_access_token(user)

    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        f"/cases/{case.case_id}/documents",
        files={"file": ("Min Tinglysningsattest.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["document_type"] == "tinglysningsattest"


def test_run_ocr_route_uses_shared_pipeline(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        user = create_user(session, email="ocr@example.com", password="secret123")
        case = create_case(session, "API OCR", user_id=user.id)
        doc_id = "doc-test"
        pdf_path = storage_service.get_document_pdf_path(case.case_id, doc_id)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        doc = Document(
            document_id=doc_id,
            case_id=case.case_id,
            filename="akt.pdf",
            file_path=str(pdf_path),
            document_type="akt",
        )
        storage_service.save_document(session, doc)
        add_document_to_case(session, case.case_id, doc_id)
        token = build_access_token(user)

    with patch("app.api.routes.ocr.run_ocr_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/documents/{doc_id}/ocr",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["task_type"] == "ocr"
    assert payload["status"] == "pending"
    assert payload["case_id"] == case.case_id
    assert payload["result_data"]["document_id"] == doc_id
    mock_delay.assert_called_once_with(payload["id"], case.case_id, doc_id)

    with get_session_ctx() as session:
        saved_doc = storage_service.load_document(session, case.case_id, doc_id)
        saved_job = storage_service.load_job(session, case.case_id, payload["id"])

    assert saved_doc is not None
    assert saved_doc.parse_status == "processing"
    assert saved_job is not None
    assert saved_job.status == "pending"
