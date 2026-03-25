from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.attest import AttestPipelineState, AttestSegment, DeclarationBlock
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


def test_delete_document_removes_pending_document(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        user = create_user(session, email="delete-doc@example.com", password="secret123")
        case = create_case(session, "API delete document", user_id=user.id)
        doc_id = "doc-delete"
        pdf_path = storage_service.get_document_pdf_path(case.case_id, doc_id)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        doc = Document(
            document_id=doc_id,
            case_id=case.case_id,
            filename="akt.pdf",
            file_path=str(pdf_path),
            document_type="akt",
            parse_status="pending",
        )
        storage_service.save_document(session, doc)
        token = build_access_token(user)

    response = client.delete(
        f"/cases/{case.case_id}/documents/{doc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204

    with get_session_ctx() as session:
        saved_doc = storage_service.load_document(session, case.case_id, doc_id)

    assert saved_doc is None
    assert not pdf_path.exists()


def test_delete_document_rejects_ocr_started_document(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        user = create_user(session, email="delete-doc-locked@example.com", password="secret123")
        case = create_case(session, "API delete locked document", user_id=user.id)
        doc_id = "doc-locked"
        pdf_path = storage_service.get_document_pdf_path(case.case_id, doc_id)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        doc = Document(
            document_id=doc_id,
            case_id=case.case_id,
            filename="akt.pdf",
            file_path=str(pdf_path),
            document_type="akt",
            parse_status="ocr_done",
        )
        storage_service.save_document(session, doc)
        token = build_access_token(user)

    response = client.delete(
        f"/cases/{case.case_id}/documents/{doc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


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


def test_get_attest_debug_returns_pipeline_summary(tmp_path, monkeypatch):
    with get_session_ctx() as session:
        user = create_user(session, email="attest-debug@example.com", password="secret123")
        case = create_case(session, "API Attest Debug", user_id=user.id)
        doc_id = "doc-attest"
        pdf_path = storage_service.get_document_pdf_path(case.case_id, doc_id)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        doc = Document(
            document_id=doc_id,
            case_id=case.case_id,
            filename="attest.pdf",
            file_path=str(pdf_path),
            document_type="tinglysningsattest",
        )
        storage_service.save_document(session, doc)
        storage_service.save_attest_pipeline_state(
            session,
            case.case_id,
            doc_id,
            AttestPipelineState(
                version=2,
                case_id=case.case_id,
                document_id=doc_id,
                source_signature="sig",
                page_count=4,
                segment_strategy="page_window_v2",
                segments=[
                    AttestSegment(
                        segment_id="seg-1",
                        case_id=case.case_id,
                        document_id=doc_id,
                        segment_index=0,
                        page_start=1,
                        page_end=2,
                        page_numbers=[1, 2],
                        text="Prioritet 1\nDato/løbenummer: 01.01.2020-123456",
                        text_hash="hash-1",
                        heading="Deklaration",
                        candidate_date_references=["01.01.2020-123456"],
                        block_type="declaration_start",
                    )
                ],
                declaration_blocks=[
                    DeclarationBlock(
                        block_id="block-1",
                        case_id=case.case_id,
                        document_id=doc_id,
                        page_start=1,
                        page_end=2,
                        source_segment_ids=["seg-1"],
                        priority_number="1",
                        title="Deklaration",
                        archive_number="A-1",
                        raw_scope_text="Vedr. matr 1a",
                        raw_parcel_references=["1a"],
                        status="aktiv",
                        fanout_date_refs=["01.01.2020-123456"],
                    )
                ],
            ),
        )
        token = build_access_token(user)

    response = client.get(
        f"/cases/{case.case_id}/documents/{doc_id}/attest-debug",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == doc_id
    assert payload["segment_count"] == 1
    assert payload["declaration_block_count"] == 1
    assert payload["block_type_counts"]["declaration_start"] == 1
    assert payload["declaration_blocks"][0]["fanout_date_reference_count"] == 1
