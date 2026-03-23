from unittest.mock import patch
from datetime import date

import pytest

from app.core.config import settings
from app.db.database import create_tables, get_session_ctx, reset_engine_cache
from app.models.chunk import Chunk
from app.models.report import Report, ReportEntry
from app.models.servitut import Evidence, Servitut
from app.services.report_service import generate_report


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


def call_generate_report(servitutter, chunks, case_id="case-test", **kwargs):
    with get_session_ctx() as session:
        return generate_report(session, servitutter, chunks, case_id, **kwargs)


def make_mock_servitut(i: int) -> Servitut:
    return Servitut(
        easement_id=f"srv-test{i:04d}",
        case_id="case-test",
        source_document="doc-test",
        title=f"Servitut {i}",
        summary=f"Resumé af servitut {i}",
        beneficiary="Kommunen",
        disposition_type="rådighed",
        legal_type="offentlig",
        construction_relevance=i % 2 == 0,
        action_note="Ingen handling",
        confidence=0.8,
        evidence=[
            Evidence(
                chunk_id=f"chunk{i:012d}",
                document_id="doc-test",
                page=i,
                text_excerpt=f"Tekst fra side {i}",
            )
        ],
    )


def make_mock_chunks() -> list:
    return [
        Chunk(
            chunk_id=f"chunk{i:012d}",
            document_id="doc-test",
            case_id="case-test",
            page=i,
            text=f"Servitut {i} vedrører vejret og byggelinjer.",
            chunk_index=i,
            char_start=0,
            char_end=50,
        )
        for i in range(1, 4)
    ]


MOCK_API_RESPONSE = """{
  "entries": [
    {
      "sequence_number": 1,
      "date_reference": "01.01.2000",
      "description": "En testservitut om vejret.",
      "beneficiary": "Kommunen",
      "disposition": "Rådighed",
      "legal_type": "Offentligretlig",
      "action": "Ingen handling",
      "relevant_for_project": true,
      "easement_id": "srv-test0001"
    }
  ],
  "notes": "Alt ser ud til at være i orden."
}"""


def test_report_fallback_on_api_error():
    """When Claude API fails, report falls back to building entries from servitutter directly."""
    servitutter = [make_mock_servitut(1), make_mock_servitut(2)]
    chunks = make_mock_chunks()

    with patch("app.services.report_service.generate_text") as mock_generate_text:
        mock_generate_text.side_effect = Exception("API unavailable")
        report = call_generate_report(servitutter, chunks, "case-test")

    assert isinstance(report, Report)
    assert report.case_id == "case-test"
    assert len(report.entries) == 2
    assert report.entries[0].description == "Resumé af servitut 1"
    assert report.target_parcel_numbers == []


def test_report_with_mock_api_response():
    """When Claude returns valid JSON, report is built from that."""
    servitutter = [make_mock_servitut(1)]
    chunks = make_mock_chunks()

    with patch("app.services.report_service.generate_text", return_value=MOCK_API_RESPONSE):
        report = call_generate_report(servitutter, chunks, "case-test")

    assert isinstance(report, Report)
    assert len(report.entries) == 1
    assert report.entries[0].description == "En testservitut om vejret."
    assert report.notes == "Alt ser ud til at være i orden."
    assert report.markdown_content is not None
    assert "| Nr. | Dato/løbenummer |" in report.markdown_content
    assert "En testservitut om vejret." in report.markdown_content


def test_report_uses_deepseek_reasoner_by_default(monkeypatch):
    servitutter = [make_mock_servitut(1)]
    chunks = make_mock_chunks()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "REPORT_LLM_PROVIDER", "")
    monkeypatch.setattr(settings, "REPORT_MODEL", "")

    with patch("app.services.report_service.generate_text", return_value=MOCK_API_RESPONSE) as mock_generate_text:
        call_generate_report(servitutter, chunks, "case-test")

    _, kwargs = mock_generate_text.call_args
    assert kwargs["provider"] is None
    assert kwargs["model"] == "deepseek-reasoner"


def test_report_uses_explicit_report_model_override(monkeypatch):
    servitutter = [make_mock_servitut(1)]
    chunks = make_mock_chunks()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "REPORT_LLM_PROVIDER", "")
    monkeypatch.setattr(settings, "REPORT_MODEL", "deepseek-chat")

    with patch("app.services.report_service.generate_text", return_value=MOCK_API_RESPONSE) as mock_generate_text:
        call_generate_report(servitutter, chunks, "case-test")

    _, kwargs = mock_generate_text.call_args
    assert kwargs["provider"] is None
    assert kwargs["model"] == "deepseek-chat"


def test_report_can_use_separate_provider_and_model(monkeypatch):
    servitutter = [make_mock_servitut(1)]
    chunks = make_mock_chunks()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "REPORT_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "REPORT_MODEL", "deepseek-reasoner")

    with patch("app.services.report_service.generate_text", return_value=MOCK_API_RESPONSE) as mock_generate_text:
        call_generate_report(servitutter, chunks, "case-test")

    _, kwargs = mock_generate_text.call_args
    assert kwargs["provider"] == "deepseek"
    assert kwargs["model"] == "deepseek-reasoner"


def test_report_accepts_json_wrapped_in_code_fence():
    servitutter = [make_mock_servitut(1)]
    chunks = make_mock_chunks()
    wrapped_response = f"```json\n{MOCK_API_RESPONSE}\n```"

    with patch("app.services.report_service.generate_text", return_value=wrapped_response):
        report = call_generate_report(servitutter, chunks, "case-test")

    assert len(report.entries) == 1
    assert report.notes == "Alt ser ud til at være i orden."


def test_report_includes_all_servitutter_with_scope_annotation():
    """All servitutter appear in the report prompt — Ja/Nej/Måske set by LLM, not filtered."""
    included = make_mock_servitut(1)
    included.title = "Servitut for 0005ay"
    included.applies_to_parcel_numbers = ["0005ay"]
    other = make_mock_servitut(2)
    other.title = "Servitut for anden matrikel"
    other.applies_to_parcel_numbers = ["0518p"]

    with patch("app.services.report_service.generate_text", return_value=MOCK_API_RESPONSE) as mock_generate_text:
        call_generate_report(
            [included, other],
            make_mock_chunks(),
            "case-test",
            target_parcel_numbers=["0005ay"],
            available_parcel_numbers=["0005ay", "0518p"],
        )

    prompt = mock_generate_text.call_args[0][0]
    assert "Servitut for 0005ay" in prompt
    # Both are sent to the LLM so it can assign Ja/Nej/Måske
    assert "Servitut for anden matrikel" in prompt


def test_report_filters_future_servitutter_when_as_of_date_is_set():
    historical = make_mock_servitut(1)
    historical.title = "Historisk servitut"
    historical.registered_at = date(2022, 12, 20)
    future = make_mock_servitut(2)
    future.title = "Ny servitut"
    future.registered_at = date(2024, 1, 16)

    with patch("app.services.report_service.generate_text", return_value=MOCK_API_RESPONSE) as mock_generate_text:
        report = call_generate_report(
            [historical, future],
            make_mock_chunks(),
            "case-test",
            as_of_date=date(2022, 12, 20),
        )

    prompt = mock_generate_text.call_args[0][0]
    assert "Historisk servitut" in prompt
    assert "Ny servitut" not in prompt
    assert report.as_of_date == date(2022, 12, 20)


def test_report_entry_model():
    entry = ReportEntry(
        sequence_number=1,
        date_reference="14.09.1903",
        description="Test beskrivelse",
        beneficiary="Kommunen",
        disposition="Rådighed",
        legal_type="Offentligretlig",
        action="Ingen handling",
        relevant_for_project=True,
        easement_id="srv-test0001",
    )
    assert entry.sequence_number == 1
    assert entry.relevant_for_project is True


def test_sort_oldest_first():
    """Entries should be sorted by date_reference oldest-first."""
    srv1 = make_mock_servitut(1)
    srv1.date_reference = "15.06.1985-200-40"
    srv1.summary = "Nyeste servitut"
    srv2 = make_mock_servitut(2)
    srv2.date_reference = "03.02.1957-490-40"
    srv2.summary = "Ældste servitut"
    srv3 = make_mock_servitut(3)
    srv3.date_reference = "22.11.1970-100-40"
    srv3.summary = "Midterste servitut"

    with patch("app.services.report_service.generate_text") as mock_generate:
        mock_generate.side_effect = Exception("Force fallback")
        report = call_generate_report([srv1, srv2, srv3], make_mock_chunks(), "case-test")

    assert report.entries[0].date_reference.startswith("03.02.1957")
    assert report.entries[1].date_reference.startswith("22.11.1970")
    assert report.entries[2].date_reference.startswith("15.06.1985")


def test_dedup_removes_duplicate_date_reference():
    """Two servitutter with the same date_reference → only one entry."""
    srv1 = make_mock_servitut(1)
    srv1.date_reference = "01.01.2000-123-40"
    srv2 = make_mock_servitut(2)
    srv2.date_reference = "01.01.2000-123-40"

    with patch("app.services.report_service.generate_text") as mock_generate:
        mock_generate.side_effect = Exception("Force fallback")
        report = call_generate_report([srv1, srv2], make_mock_chunks(), "case-test")

    assert len(report.entries) == 1


def test_empty_description_no_raw_text():
    """When description and raw_text are both empty, fallback text is 'Akt ikke gennemgået.'"""
    srv = make_mock_servitut(1)
    srv.summary = None
    srv.evidence = []  # no raw_text

    with patch("app.services.report_service.generate_text") as mock_generate:
        mock_generate.side_effect = Exception("Force fallback")
        report = call_generate_report([srv], make_mock_chunks(), "case-test")

    assert report.entries[0].description == "Akt ikke gennemgået."


def test_empty_action_fallback():
    """When action_note is None, fallback is 'Kræver opslag i tingbogsakt'."""
    srv = make_mock_servitut(1)
    srv.action_note = None

    with patch("app.services.report_service.generate_text") as mock_generate:
        mock_generate.side_effect = Exception("Force fallback")
        report = call_generate_report([srv], make_mock_chunks(), "case-test")

    assert report.entries[0].action == "Kræver opslag i tingbogsakt"


def test_amt_warning_set():
    """Beneficiary containing 'amt' (case-insensitive) sets beneficiary_amt_warning=True."""
    srv = make_mock_servitut(1)
    srv.beneficiary = "Vejle Amt"

    with patch("app.services.report_service.generate_text") as mock_generate:
        mock_generate.side_effect = Exception("Force fallback")
        report = call_generate_report([srv], make_mock_chunks(), "case-test")

    assert report.entries[0].beneficiary_amt_warning is True


def test_amt_warning_not_set():
    """Beneficiary without 'amt' leaves beneficiary_amt_warning=False."""
    srv = make_mock_servitut(1)
    srv.beneficiary = "Kommunen"

    with patch("app.services.report_service.generate_text") as mock_generate:
        mock_generate.side_effect = Exception("Force fallback")
        report = call_generate_report([srv], make_mock_chunks(), "case-test")

    assert report.entries[0].beneficiary_amt_warning is False


def test_report_model_serialization():
    report = Report(
        report_id="rep-test1234",
        case_id="case-test",
        as_of_date=date(2022, 12, 20),
        target_parcel_numbers=["1o", "1v"],
        entries=[],
        notes="En note",
        markdown_content="# Tabel\n...",
    )
    data = report.model_dump()
    assert data["report_id"] == "rep-test1234"
    assert data["notes"] == "En note"
    assert data["as_of_date"] == date(2022, 12, 20)
    assert data["target_parcel_numbers"] == ["1o", "1v"]
    report2 = Report(**data)
    assert report2.markdown_content == "# Tabel\n..."
    assert report2.as_of_date == date(2022, 12, 20)
    assert report2.target_parcel_numbers == ["1o", "1v"]
