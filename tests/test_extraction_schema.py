import json
import pytest
from datetime import date, datetime

from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut


MOCK_LLM_RESPONSE = """
[
  {
    "date_reference": "14.09.1903-913066-40",
    "title": "Vejret for naboejendommen",
    "summary": "Ejer af ejendommen har pligt til at holde vejen åben for naboejendommens beboere.",
    "beneficiary": "Ejer af matr. nr. 5a",
    "disposition_type": "rådighed",
    "legal_type": "privatretlig",
    "construction_relevance": true,
    "action_note": "Kontrollér vejens beliggenhed ift. byggeønsker.",
    "confidence": 0.9
  },
  {
    "date_reference": null,
    "title": "Byggelinje",
    "summary": "Byggelinje 5 meter fra vejmidte.",
    "beneficiary": null,
    "disposition_type": "rådighed",
    "legal_type": "offentlig",
    "construction_relevance": true,
    "action_note": "Overhold byggelinjen ved nybyggeri.",
    "confidence": 0.85
  }
]
"""


def test_parse_mock_llm_response():
    data = json.loads(MOCK_LLM_RESPONSE)
    assert len(data) == 2
    assert data[0]["title"] == "Vejret for naboejendommen"
    assert data[1]["beneficiary"] is None


def test_servitut_model_validates_correctly():
    srv = Servitut(
        servitut_id="srv-abc12345",
        case_id="case-xyz",
        source_document="doc-abc",
        date_reference="14.09.1903",
        registered_at=date(1903, 9, 14),
        title="Test servitut",
        summary="En test servitut",
        beneficiary="Kommunen",
        disposition_type="rådighed",
        legal_type="offentlig",
        construction_relevance=True,
        action_note="Ingen handling",
        raw_matrikel_references=["1o", "1v"],
        raw_scope_text="Vedr. matr.nr. 1o og 1v",
        scope_source="attest",
        confidence=0.9,
        evidence=[],
        flags=[],
    )
    assert srv.servitut_id == "srv-abc12345"
    assert srv.construction_relevance is True
    assert srv.confidence == 0.9
    assert srv.registered_at == date(1903, 9, 14)
    assert srv.scope_source == "attest"


def test_servitut_model_defaults():
    srv = Servitut(
        servitut_id="srv-min",
        case_id="case-min",
        source_document="doc-min",
    )
    assert srv.confidence == 0.0
    assert srv.construction_relevance is False
    assert srv.evidence == []
    assert srv.flags == []
    assert srv.raw_matrikel_references == []
    assert srv.registered_at is None


def test_evidence_model():
    ev = Evidence(
        chunk_id="abc123456789",
        document_id="doc-abc",
        page=3,
        text_excerpt="Servitutten vedrører vejret.",
    )
    assert ev.page == 3
    assert "vejret" in ev.text_excerpt


def test_chunk_model():
    chunk = Chunk(
        chunk_id="abc123456789",
        document_id="doc-test",
        case_id="case-test",
        page=1,
        text="Test tekst",
        chunk_index=0,
        char_start=0,
        char_end=10,
    )
    assert chunk.chunk_id == "abc123456789"
    assert len(chunk.chunk_id) == 12


def test_servitut_serialization():
    srv = Servitut(
        servitut_id="srv-test",
        case_id="case-test",
        source_document="doc-test",
        title="Test",
        registered_at=date(2022, 12, 20),
        raw_scope_text="Vedr. matr.nr. 1o",
        confidence=0.75,
    )
    data = srv.model_dump()
    assert data["servitut_id"] == "srv-test"
    assert data["confidence"] == 0.75
    assert data["registered_at"] == date(2022, 12, 20)
    # Round-trip
    srv2 = Servitut(**data)
    assert srv2.title == "Test"
    assert srv2.raw_scope_text == "Vedr. matr.nr. 1o"
