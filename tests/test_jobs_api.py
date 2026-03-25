from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.attest import AttestPipelineState
from app.models.chunk import Chunk
from app.models.declaration import Servituterklaring
from app.models.document import Document
from app.models.job import Job
from app.models.report import Report
from app.models.servitut import Servitut
from app.services import storage_service
from app.services.auth_service import build_access_token, create_user
from app.services.case_service import create_case

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


def test_extract_route_enqueues_background_job():
    with get_session_ctx() as session:
        user = create_user(session, email="extract@example.com", password="secret123")
        case = create_case(session, "Extraction job", user_id=user.id)
        document = Document(
            document_id="doc-1",
            case_id=case.case_id,
            filename="attest.pdf",
            file_path="storage/cases/doc-1/original.pdf",
            document_type="tinglysningsattest",
        )
        storage_service.save_document(session, document)
        storage_service.save_chunks(
            session,
            case.case_id,
            document.document_id,
            [
                Chunk(
                    chunk_id="chunk-1",
                    document_id=document.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Servitut tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=14,
                )
            ],
        )
        token = build_access_token(user)

    with patch("app.api.routes.extraction.run_extraction_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["task_type"] == "extraction"
    assert payload["status"] == "pending"
    assert payload["result_data"]["chunk_count"] == 1
    mock_delay.assert_called_once_with(payload["id"], case.case_id)

    with get_session_ctx() as session:
        saved_case = storage_service.load_case(session, case.case_id)
        saved_job = storage_service.load_job(session, case.case_id, payload["id"])

    assert saved_case is not None
    assert saved_case.status == "extracting"
    assert saved_job is not None
    assert saved_job.status == "pending"


def test_extract_route_requires_tinglysningsattest():
    with get_session_ctx() as session:
        user = create_user(session, email="extract-no-attest@example.com", password="secret123")
        case = create_case(session, "Extraction without attest", user_id=user.id)
        document = Document(
            document_id="doc-akt",
            case_id=case.case_id,
            filename="akt.pdf",
            file_path="storage/cases/doc-akt/original.pdf",
            document_type="akt",
        )
        storage_service.save_document(session, document)
        storage_service.save_chunks(
            session,
            case.case_id,
            document.document_id,
            [
                Chunk(
                    chunk_id="chunk-akt-1",
                    document_id=document.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Servitut tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=14,
                )
            ],
        )
        token = build_access_token(user)

    with patch("app.api.routes.extraction.run_extraction_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert "tinglysningsattest" in response.json()["error"]["message"]
    mock_delay.assert_not_called()


def test_get_job_status_returns_case_scoped_job():
    with get_session_ctx() as session:
        user = create_user(session, email="job-status@example.com", password="secret123")
        case = create_case(session, "Job status", user_id=user.id)
        job = Job(
            id="job-1234",
            case_id=case.case_id,
            task_type="ocr",
            status="processing",
            result_data={"document_id": "doc-1", "message": "Working"},
        )
        storage_service.save_job(session, job)
        token = build_access_token(user)

    response = client.get(
        f"/cases/{case.case_id}/jobs/{job.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == job.id
    assert payload["status"] == "processing"
    assert payload["result_data"]["message"] == "Working"


def test_extract_route_force_rebuild_clears_previous_outputs():
    with get_session_ctx() as session:
        user = create_user(session, email="extract-rebuild@example.com", password="secret123")
        case = create_case(session, "Extraction rebuild job", user_id=user.id)
        document = Document(
            document_id="doc-attest",
            case_id=case.case_id,
            filename="attest.pdf",
            file_path="storage/cases/doc-attest/original.pdf",
            document_type="tinglysningsattest",
        )
        storage_service.save_document(session, document)
        storage_service.save_chunks(
            session,
            case.case_id,
            document.document_id,
            [
                Chunk(
                    chunk_id="chunk-1",
                    document_id=document.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Servitut tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=14,
                )
            ],
        )
        storage_service.save_servitut(
            session,
            Servitut(
                easement_id="srv-1",
                case_id=case.case_id,
                source_document=document.document_id,
                title="Eksisterende",
            ),
        )
        storage_service.save_report(session, Report(report_id="rep-1", case_id=case.case_id))
        storage_service.save_declaration(
            session,
            Servituterklaring(declaration_id="decl-1", case_id=case.case_id, created_at=document.created_at),
        )
        storage_service.save_canonical_list(
            session,
            case.case_id,
            [Servitut(easement_id="srv-1", case_id=case.case_id, source_document=document.document_id)],
        )
        storage_service.save_attest_pipeline_state(
            session,
            case.case_id,
            document.document_id,
            AttestPipelineState(
                case_id=case.case_id,
                document_id=document.document_id,
                source_signature="sig",
            ),
        )
        token = build_access_token(user)

    with patch("app.api.routes.extraction.run_extraction_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/extract?force_rebuild=true&clear_attest_pipeline=true",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["result_data"]["force_rebuild"] is True
    assert payload["result_data"]["clear_attest_pipeline"] is True
    assert payload["result_data"]["reset_summary"]["servitutter_deleted"] == 1
    assert payload["result_data"]["reset_summary"]["reports_deleted"] == 1
    assert payload["result_data"]["reset_summary"]["declarations_deleted"] == 1
    assert payload["result_data"]["reset_summary"]["attest_states_cleared"] == 1
    mock_delay.assert_called_once_with(payload["id"], case.case_id)

    with get_session_ctx() as session:
        assert storage_service.list_servitutter(session, case.case_id) == []
        assert storage_service.list_reports(session, case.case_id) == []
        assert storage_service.list_declarations(session, case.case_id) == []
        assert storage_service.load_canonical_list(session, case.case_id) is None
        assert (
            storage_service.load_attest_pipeline_state(session, case.case_id, document.document_id)
            is None
        )


def test_extract_attest_route_enqueues_background_job():
    with get_session_ctx() as session:
        user = create_user(session, email="extract-attest@example.com", password="secret123")
        case = create_case(session, "Attest extraction job", user_id=user.id)
        attest = Document(
            document_id="doc-attest",
            case_id=case.case_id,
            filename="attest.pdf",
            file_path="storage/cases/doc-attest/original.pdf",
            document_type="tinglysningsattest",
        )
        storage_service.save_document(session, attest)
        storage_service.save_chunks(
            session,
            case.case_id,
            attest.document_id,
            [
                Chunk(
                    chunk_id="chunk-attest-1",
                    document_id=attest.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Servitut tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=14,
                )
            ],
        )
        token = build_access_token(user)

    with patch("app.api.routes.extraction.run_attest_extraction_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/extract-attest",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["task_type"] == "extraction_attest"
    assert payload["status"] == "pending"
    assert payload["result_data"]["chunk_count"] == 1
    mock_delay.assert_called_once_with(payload["id"], case.case_id)


def test_extract_akt_route_requires_canonical_attest_list():
    with get_session_ctx() as session:
        user = create_user(session, email="extract-akt-missing@example.com", password="secret123")
        case = create_case(session, "Akt extraction job", user_id=user.id)
        attest = Document(
            document_id="doc-attest",
            case_id=case.case_id,
            filename="attest.pdf",
            file_path="storage/cases/doc-attest/original.pdf",
            document_type="tinglysningsattest",
        )
        akt = Document(
            document_id="doc-akt",
            case_id=case.case_id,
            filename="akt.pdf",
            file_path="storage/cases/doc-akt/original.pdf",
            document_type="akt",
        )
        storage_service.save_document(session, attest)
        storage_service.save_document(session, akt)
        storage_service.save_chunks(
            session,
            case.case_id,
            attest.document_id,
            [
                Chunk(
                    chunk_id="chunk-attest-1",
                    document_id=attest.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Attest tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=11,
                )
            ],
        )
        storage_service.save_chunks(
            session,
            case.case_id,
            akt.document_id,
            [
                Chunk(
                    chunk_id="chunk-akt-1",
                    document_id=akt.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Akt tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=8,
                )
            ],
        )
        token = build_access_token(user)

    with patch("app.api.routes.extraction.run_akt_extraction_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/extract-akt",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert "extract-attest" in response.json()["error"]["message"]
    mock_delay.assert_not_called()


def test_extract_akt_route_enqueues_background_job():
    with get_session_ctx() as session:
        user = create_user(session, email="extract-akt@example.com", password="secret123")
        case = create_case(session, "Akt extraction queued", user_id=user.id)
        attest = Document(
            document_id="doc-attest",
            case_id=case.case_id,
            filename="attest.pdf",
            file_path="storage/cases/doc-attest/original.pdf",
            document_type="tinglysningsattest",
        )
        akt = Document(
            document_id="doc-akt",
            case_id=case.case_id,
            filename="akt.pdf",
            file_path="storage/cases/doc-akt/original.pdf",
            document_type="akt",
        )
        storage_service.save_document(session, attest)
        storage_service.save_document(session, akt)
        storage_service.save_chunks(
            session,
            case.case_id,
            attest.document_id,
            [
                Chunk(
                    chunk_id="chunk-attest-1",
                    document_id=attest.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Attest tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=11,
                )
            ],
        )
        storage_service.save_chunks(
            session,
            case.case_id,
            akt.document_id,
            [
                Chunk(
                    chunk_id="chunk-akt-1",
                    document_id=akt.document_id,
                    case_id=case.case_id,
                    page=1,
                    text="Akt tekst",
                    chunk_index=0,
                    char_start=0,
                    char_end=8,
                )
            ],
        )
        storage_service.save_canonical_list(
            session,
            case.case_id,
            [
                Servitut(
                    easement_id="srv-1",
                    case_id=case.case_id,
                    source_document=attest.document_id,
                    title="Canonical",
                )
            ],
        )
        token = build_access_token(user)

    with patch("app.api.routes.extraction.run_akt_extraction_task.delay") as mock_delay:
        response = client.post(
            f"/cases/{case.case_id}/extract-akt",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["task_type"] == "extraction_akt"
    assert payload["status"] == "pending"
    assert payload["result_data"]["canonical_count"] == 1
    mock_delay.assert_called_once_with(payload["id"], case.case_id)
