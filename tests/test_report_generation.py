from unittest.mock import MagicMock, patch

import pytest

from app.models.chunk import Chunk
from app.models.report import Report, ReportEntry
from app.models.servitut import Evidence, Servitut
from app.services.report_service import generate_report


def make_mock_servitut(i: int) -> Servitut:
    return Servitut(
        servitut_id=f"srv-test{i:04d}",
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
      "nr": 1,
      "date_reference": "01.01.2000",
      "description": "En testservitut om vejret.",
      "beneficiary": "Kommunen",
      "disposition": "Rådighed",
      "legal_type": "Offentligretlig",
      "action": "Ingen handling",
      "relevant_for_project": true,
      "servitut_id": "srv-test0001"
    }
  ],
  "notes": "Alt ser ud til at være i orden.",
  "markdown_table": "| Nr. | Dato | Beskrivelse |\\n|-----|------|-------------|\\n| 1 | 01.01.2000 | En testservitut |"
}"""


def test_report_fallback_on_api_error():
    """When Claude API fails, report falls back to building entries from servitutter directly."""
    servitutter = [make_mock_servitut(1), make_mock_servitut(2)]
    chunks = make_mock_chunks()

    with patch("app.services.report_service._get_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API unavailable")

        report = generate_report(servitutter, chunks, "case-test")

    assert isinstance(report, Report)
    assert report.case_id == "case-test"
    assert len(report.servitutter) == 2
    assert report.servitutter[0].description == "Resumé af servitut 1"


def test_report_with_mock_api_response():
    """When Claude returns valid JSON, report is built from that."""
    servitutter = [make_mock_servitut(1)]
    chunks = make_mock_chunks()

    with patch("app.services.report_service._get_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=MOCK_API_RESPONSE)]
        mock_client.messages.create.return_value = mock_msg

        report = generate_report(servitutter, chunks, "case-test")

    assert isinstance(report, Report)
    assert len(report.servitutter) == 1
    assert report.servitutter[0].description == "En testservitut om vejret."
    assert report.notes == "Alt ser ud til at være i orden."
    assert report.markdown_content is not None


def test_report_entry_model():
    entry = ReportEntry(
        nr=1,
        date_reference="14.09.1903",
        description="Test beskrivelse",
        beneficiary="Kommunen",
        disposition="Rådighed",
        legal_type="Offentligretlig",
        action="Ingen handling",
        relevant_for_project=True,
        servitut_id="srv-test0001",
    )
    assert entry.nr == 1
    assert entry.relevant_for_project is True


def test_report_model_serialization():
    report = Report(
        report_id="rep-test1234",
        case_id="case-test",
        servitutter=[],
        notes="En note",
        markdown_content="# Tabel\n...",
    )
    data = report.model_dump()
    assert data["report_id"] == "rep-test1234"
    assert data["notes"] == "En note"
    report2 = Report(**data)
    assert report2.markdown_content == "# Tabel\n..."
