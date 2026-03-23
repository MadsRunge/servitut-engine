import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.document import Document
from app.models.report import Report
from app.services import storage_service
from app.services.auth_service import build_access_token, create_user
from app.services.case_service import create_case

client = TestClient(app)


def _create_owned_case(email: str, name: str):
    with get_session_ctx() as session:
        user = create_user(session, email=email, password="secret123")
        case = create_case(session, name, user_id=user.id)
        token = build_access_token(user)
    return case, {"Authorization": f"Bearer {token}"}

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


def test_register_login_and_me():
    register_response = client.post(
        "/auth/register",
        json={"email": "auth@example.com", "password": "secret123", "role": "user"},
    )
    assert register_response.status_code == 201
    assert register_response.json()["email"] == "auth@example.com"
    assert "hashed_password" not in register_response.json()

    login_response = client.post(
        "/auth/login",
        data={"username": "auth@example.com", "password": "secret123"},
    )
    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]

    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "auth@example.com"


def test_cases_require_bearer_token():
    response = client.get("/cases")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["message"] == "Not authenticated"


def test_list_cases_only_returns_owned_cases():
    owned_case, headers = _create_owned_case("owner@example.com", "Min sag")
    _create_owned_case("other@example.com", "Anden sag")

    response = client.get("/cases", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert [case["case_id"] for case in payload] == [owned_case.case_id]


def test_get_case_returns_404_for_foreign_case():
    foreign_case, _ = _create_owned_case("foreign@example.com", "Fremmed sag")
    _, headers = _create_owned_case("viewer@example.com", "Egen sag")

    response = client.get(f"/cases/{foreign_case.case_id}", headers=headers)

    assert response.status_code == 404


def test_get_document_returns_404_for_foreign_case_document():
    with get_session_ctx() as session:
        owner = create_user(session, email="doc-owner@example.com", password="secret123")
        viewer = create_user(session, email="doc-viewer@example.com", password="secret123")
        case = create_case(session, "Dokumentsag", user_id=owner.id)
        pdf_path = storage_service.get_document_pdf_path(case.case_id, "doc-foreign")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        storage_service.save_document(
            session,
            Document(
                document_id="doc-foreign",
                case_id=case.case_id,
                filename="akt.pdf",
                file_path=str(pdf_path),
                document_type="akt",
            ),
        )
        viewer_headers = {"Authorization": f"Bearer {build_access_token(viewer)}"}

    response = client.get(
        f"/cases/{case.case_id}/documents/doc-foreign",
        headers=viewer_headers,
    )

    assert response.status_code == 403


def test_get_report_returns_404_for_foreign_case_report():
    with get_session_ctx() as session:
        owner = create_user(session, email="report-owner@example.com", password="secret123")
        viewer = create_user(session, email="report-viewer@example.com", password="secret123")
        case = create_case(session, "Rapportsag", user_id=owner.id)
        storage_service.save_report(
            session,
            Report(report_id="rep-foreign", case_id=case.case_id),
        )
        viewer_headers = {"Authorization": f"Bearer {build_access_token(viewer)}"}

    response = client.get(
        f"/cases/{case.case_id}/reports/rep-foreign",
        headers=viewer_headers,
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path_template", "request_kwargs"),
    [
        (
            "POST",
            "/cases/{case_id}/documents",
            {
                "files": {
                    "file": ("attest.pdf", b"%PDF-1.4 fake", "application/pdf"),
                },
            },
        ),
        ("GET", "/cases/{case_id}/documents", {}),
        ("GET", "/cases/{case_id}/documents/doc-foreign", {}),
        ("POST", "/cases/{case_id}/documents/doc-foreign/ocr", {}),
        ("GET", "/cases/{case_id}/documents/doc-foreign/pages", {}),
        ("GET", "/cases/{case_id}/documents/doc-foreign/chunks", {}),
        ("POST", "/cases/{case_id}/extract", {}),
        ("GET", "/cases/{case_id}/jobs/job-foreign", {}),
        ("GET", "/cases/{case_id}/servitutter", {}),
        ("POST", "/cases/{case_id}/reports", {}),
        ("GET", "/cases/{case_id}/reports", {}),
        ("GET", "/cases/{case_id}/reports/rep-foreign", {}),
    ],
)
def test_case_scoped_routes_return_403_for_foreign_case(method, path_template, request_kwargs):
    with get_session_ctx() as session:
        owner = create_user(session, email="route-owner@example.com", password="secret123")
        viewer = create_user(session, email="route-viewer@example.com", password="secret123")
        case = create_case(session, "Fremmed sag", user_id=owner.id)
        viewer_headers = {"Authorization": f"Bearer {build_access_token(viewer)}"}

    response = client.request(
        method,
        path_template.format(case_id=case.case_id),
        headers=viewer_headers,
        **request_kwargs,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert response.json()["error"]["message"] == "Forbidden"
