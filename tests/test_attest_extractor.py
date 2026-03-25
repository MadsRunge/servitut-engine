"""Tests for app/services/attest/attest_extractor.py

Dækker de reelle failure modes:
- Hæftelser og Servitutter på samme side (char-niveau split)
- Servitutter header midt i chunk
- Headers fundet men Servitutter mangler → eksplicit fejl
- Fallback når ingen headers
- Candidate block splitting
- LLM-afvisning ekskluderes
- Fan-out blocks producerer multiple entries
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.servitut import Evidence, Servitut
from app.services.attest.attest_extractor import (
    ServitutterSectionNotFoundError,
    _build_full_text,
    _find_section_boundaries,
    merge_candidate_servitutter,
    extract_servitutter_section_text,
    split_into_candidate_blocks,
    _extract_from_candidate_block_llm,
    run_attest_extraction,
)
from app.models.attest import AttestCandidateBlock
from app.services.extraction.prompts import _load_prompt


def _chunk(chunk_id: str, page: int, chunk_index: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-test",
        case_id="case-test",
        page=page,
        chunk_index=chunk_index,
        text=text,
        char_start=0,
        char_end=len(text),
    )


# ---------------------------------------------------------------------------
# _build_full_text
# ---------------------------------------------------------------------------

def test_build_full_text_concatenerer_korrekt():
    chunks = [
        _chunk("c1", 1, 0, "Side 1 tekst"),
        _chunk("c2", 2, 0, "Side 2 tekst"),
    ]
    text, char_map = _build_full_text(chunks)
    assert "Side 1 tekst" in text
    assert "Side 2 tekst" in text
    assert len(char_map) == 2
    # Første chunk starter ved pos 0
    assert char_map[0][0] == 0


def test_build_full_text_sorterer_efter_page_chunk_index():
    chunks = [
        _chunk("c2", 2, 0, "Second"),
        _chunk("c1", 1, 0, "First"),
    ]
    text, _ = _build_full_text(chunks)
    assert text.index("First") < text.index("Second")


# ---------------------------------------------------------------------------
# _find_section_boundaries
# ---------------------------------------------------------------------------

def test_find_section_boundaries_finder_alle_fire():
    text = "Adkomster\nbla\nHæftelser\nbla\nServitutter\nbla\nØvrige oplysninger\nbla"
    boundaries = _find_section_boundaries(text)
    assert set(boundaries.keys()) == {"adkomster", "hæftelser", "servitutter", "øvrige oplysninger"}


def test_find_section_boundaries_tom_ved_ingen_headers():
    text = "Prioritet 1\nDato/løbenummer: 01.01.2000-1234\nDokument:\nbla"
    boundaries = _find_section_boundaries(text)
    assert boundaries == {}


def test_find_section_boundaries_ignorerer_ikke_standalone():
    # "Servitutter" som del af sætning må ikke matches
    text = "Deklaration vedr. servitutter på ejendommen\nPrioritet 1"
    boundaries = _find_section_boundaries(text)
    assert "servitutter" not in boundaries


# ---------------------------------------------------------------------------
# extract_servitutter_section_text — den centrale failure-mode test
# ---------------------------------------------------------------------------

def test_haeftelser_servitutter_paa_samme_side():
    """Kritisk regression: Hæftelser-footer og Servitutter-header på samme side.

    Attesten har side 6 som indeholder:
    '...Afgiftspantebrev...\nServitutter\nDokument:\nDato/løbenummer: 27.06.1934-2094-01'

    Tekst-niveau split skal EKSKLUDERE Afgiftspantebrev-teksten.
    """
    # Simulér side 6 som én chunk med BEGGE sektioner
    haeftelse_tekst = (
        "Afgiftspantebrev:\n"
        "Dato/løbenummer: 07.01.2014-1005068673\n"
        "Prioritet: 17\n"
        "Hovedstol: 1.622.000 DKK\n"
        "Senest påtegnet:\n"
        "Dato: 01.02.2018 12:41:01\n"
    )
    servitut_tekst = (
        "Servitutter\n"
        "Dokument:\n"
        "Dato/løbenummer: 27.06.1934-2094-01\n"
        "Prioritet: 1\n"
        "Dokumenttype: Deklaration\n"
    )
    chunks = [
        _chunk("c1", 1, 0, "Adkomster\nEjer info"),
        _chunk("c2", 3, 0, "Hæftelser\nNoget pantebrev..."),
        # Side 6: kombineret chunk med Hæftelser-indhold + Servitutter-header
        _chunk("c3", 6, 0, haeftelse_tekst + servitut_tekst),
        _chunk("c4", 7, 0, "Mere servitut tekst\nDato/løbenummer: 01.11.1954-316-01"),
        _chunk("c5", 8, 0, "Øvrige oplysninger\nEjendomsvurdering"),
    ]
    section_text, _ = extract_servitutter_section_text(chunks)
    assert "Afgiftspantebrev" not in section_text
    assert "1.622.000 DKK" not in section_text
    assert "27.06.1934-2094-01" in section_text


def test_servitutter_header_midt_i_chunk():
    """Header midt i chunk → char-niveau split inkluderer korrekt."""
    chunk_text = (
        "Andet pantebrev tekst\n"
        "Hæftelser\n"
        "Pantebrev Prioritet 5\n"
        "Servitutter\n"
        "Dokument:\n"
        "Dato/løbenummer: 27.06.1934-2094-01\n"
    )
    chunks = [_chunk("c1", 1, 0, chunk_text)]
    section_text, _ = extract_servitutter_section_text(chunks)
    assert "Pantebrev Prioritet 5" not in section_text
    assert "27.06.1934-2094-01" in section_text


def test_headers_fundet_servitutter_mangler_raises():
    """Headers detekteret men Servitutter-sektion absent → eksplicit fejl."""
    chunks = [
        _chunk("c1", 1, 0, "Adkomster\nEjer info"),
        _chunk("c2", 2, 0, "Hæftelser\nPantebrev..."),
        _chunk("c3", 3, 0, "Øvrige oplysninger\nEjendomsvurdering"),
    ]
    with pytest.raises(ServitutterSectionNotFoundError) as exc_info:
        extract_servitutter_section_text(chunks)
    assert "adkomster" in exc_info.value.detected_sections or "hæftelser" in exc_info.value.detected_sections


def test_ingen_headers_returnerer_alle_chunks():
    """Ingen section-headers → backward compat fallback (returnér alt)."""
    chunks = [
        _chunk("c1", 1, 0, "Prioritet 1\nDato/løbenummer: 01.01.2000-1234"),
        _chunk("c2", 2, 0, "Dokumenttype: Deklaration\nNoget tekst"),
    ]
    section_text, section_map = extract_servitutter_section_text(chunks)
    # Skal indeholde alt
    assert "01.01.2000-1234" in section_text
    assert "Dokumenttype: Deklaration" in section_text


def test_servitutter_som_eneste_section():
    """Kun Servitutter-header, ingen andre sektioner → korrekt section-tekst."""
    chunks = [
        _chunk("c1", 1, 0, "Intro tekst her"),
        _chunk("c2", 2, 0, "Servitutter\nDokument:\nDato/løbenummer: 01.01.2000-1234"),
        _chunk("c3", 3, 0, "Prioritet 2\nDato/løbenummer: 02.02.2001-5678"),
    ]
    section_text, _ = extract_servitutter_section_text(chunks)
    assert "01.01.2000-1234" in section_text
    assert "5678" in section_text
    assert "Intro tekst" not in section_text


# ---------------------------------------------------------------------------
# split_into_candidate_blocks
# ---------------------------------------------------------------------------

def _make_servitutter_section(entries: list[str]) -> str:
    """Byg en Servitutter-sektion tekst fra en liste af entry-tekster."""
    return "Servitutter\n" + "\n".join(entries)


_ENTRY_1 = (
    "Dokument:\n"
    "Dato/løbenummer: 27.06.1934-2094-01\n"
    "Prioritet: 1\n"
    "Dokumenttype: Deklaration\n"
    "Akt nr: 1_E-II_518\n"
    "Titel: Dok om passage\n"
)
_ENTRY_2 = (
    "Dokument:\n"
    "Dato/løbenummer: 01.11.1954-316-01\n"
    "Prioritet: 2\n"
    "Dokumenttype: Servitut\n"
    "Titel: Dok om bebyggelse\n"
)
_ENTRY_3 = (
    "Dokument:\n"
    "Dato/løbenummer: 15.12.1959-7403-01\n"
    "Prioritet: 3\n"
    "Dokumenttype: Servitut\n"
    "Titel: Dok om transformerstation\n"
)


def test_candidate_block_split_tre_entries():
    section_text = _ENTRY_1 + _ENTRY_2 + _ENTRY_3
    char_map: list[tuple[int, int, Chunk]] = [
        (0, len(section_text), _chunk("c1", 6, 0, section_text))
    ]
    blocks = split_into_candidate_blocks(section_text, char_map, "case-x", "doc-x")
    assert len(blocks) == 3


def test_candidate_block_indeholder_korrekt_date_ref():
    section_text = _ENTRY_1 + _ENTRY_2
    char_map = [(0, len(section_text), _chunk("c1", 6, 0, section_text))]
    blocks = split_into_candidate_blocks(section_text, char_map, "case-x", "doc-x")
    date_refs = [ref for b in blocks for ref in b.candidate_date_references]
    assert "27.06.1934-2094-01" in date_refs
    assert "01.11.1954-316-01" in date_refs


def test_candidate_block_header_only_skippes():
    """En blok der kun indeholder 'Servitutter' headeren skal skippes."""
    section_text = "Servitutter\n" + _ENTRY_1
    char_map = [(0, len(section_text), _chunk("c1", 6, 0, section_text))]
    blocks = split_into_candidate_blocks(section_text, char_map, "case-x", "doc-x")
    # Kun ENTRY_1 skal producere en block — "Servitutter\n" er for kort
    assert all("27.06.1934-2094-01" in b.candidate_date_references or b.text.strip() != "Servitutter" for b in blocks)


def test_haeftelser_indhold_ikke_i_candidates():
    """Hæftelser-tekst må ALDRIG optræde i candidate blocks."""
    haeftelse_footer = (
        "Afgiftspantebrev:\n"
        "Dato/løbenummer: 07.01.2014-1005068673\n"
        "Prioritet: 17\n"
        "Hovedstol: 1.622.000 DKK\n"
    )
    chunks = [
        _chunk("c1", 1, 0, "Adkomster\nEjer info"),
        _chunk("c2", 3, 0, "Hæftelser\nPantebrev..."),
        _chunk("c3", 6, 0, haeftelse_footer + "Servitutter\n" + _ENTRY_1),
    ]
    section_text, section_map = extract_servitutter_section_text(chunks)
    blocks = split_into_candidate_blocks(section_text, section_map, "case-x", "doc-x")
    for block in blocks:
        assert "Afgiftspantebrev" not in block.text
        assert "1.622.000 DKK" not in block.text


# ---------------------------------------------------------------------------
# _extract_from_candidate_block_llm
# ---------------------------------------------------------------------------

def _make_candidate_block(text: str) -> AttestCandidateBlock:
    return AttestCandidateBlock(
        block_id="test-block-id",
        case_id="case-test",
        document_id="doc-test",
        text=text,
        page_numbers=[6],
        candidate_date_references=["27.06.1934-2094-01"],
        candidate_archive_numbers=["1_E-II_518"],
    )


def test_llm_kald_per_candidate(monkeypatch):
    """LLM-funktionen kaldes præcis én gang for én candidate block."""
    mock_response = (
        '[{"is_servitut_candidate": true, "date_reference": "27.06.1934-2094-01", '
        '"title": "Dok om passage", "archive_number": "1_E-II_518", '
        '"registered_at": "1934-06-27", "applies_to_parcel_numbers": [], '
        '"raw_parcel_references": [], "raw_scope_text": null, '
        '"scope_source": "attest", "confidence": 1.0}]'
    )
    call_count = []
    def mock_generate_text(prompt, **kwargs):
        call_count.append(1)
        return mock_response

    monkeypatch.setattr(
        "app.services.attest.attest_extractor.generate_text",
        mock_generate_text,
    )

    block = _make_candidate_block(_ENTRY_1)
    result = _extract_from_candidate_block_llm(block, "Prompt med {candidate_text}")
    assert len(call_count) == 1
    assert len(result) == 1
    assert result[0].date_reference == "27.06.1934-2094-01"
    assert result[0].priority == 1
    assert result[0].evidence


def test_llm_afvisning_ekskluderes(monkeypatch):
    """is_servitut_candidate: false → blok ekskluderes fra output."""
    mock_response = (
        '[{"is_servitut_candidate": false, "rejection_reason": "Kun sektionsoverskrift", '
        '"date_reference": null, "title": null}]'
    )
    monkeypatch.setattr(
        "app.services.attest.attest_extractor.generate_text",
        lambda prompt, **kwargs: mock_response,
    )
    block = _make_candidate_block("Servitutter")
    result = _extract_from_candidate_block_llm(block, "Prompt: {candidate_text}")
    assert result == []


def test_fan_out_block_producerer_multiple(monkeypatch):
    """Én block med N date_refs → N Servitut-objekter (fan-out)."""
    mock_response = (
        '[{"is_servitut_candidate": true, "date_reference": "01.01.1990-111-01", '
        '"title": "Servitut A", "archive_number": null, "registered_at": "1990-01-01", '
        '"applies_to_parcel_numbers": [], "raw_parcel_references": [], '
        '"raw_scope_text": null, "scope_source": "attest", "confidence": 1.0},'
        '{"is_servitut_candidate": true, "date_reference": "02.02.1991-222-01", '
        '"title": "Servitut B", "archive_number": null, "registered_at": "1991-02-02", '
        '"applies_to_parcel_numbers": [], "raw_parcel_references": [], '
        '"raw_scope_text": null, "scope_source": "attest", "confidence": 1.0},'
        '{"is_servitut_candidate": true, "date_reference": "03.03.1992-333-01", '
        '"title": "Servitut C", "archive_number": null, "registered_at": "1992-03-03", '
        '"applies_to_parcel_numbers": [], "raw_parcel_references": [], '
        '"raw_scope_text": null, "scope_source": "attest", "confidence": 1.0}]'
    )
    monkeypatch.setattr(
        "app.services.attest.attest_extractor.generate_text",
        lambda prompt, **kwargs: mock_response,
    )
    block = _make_candidate_block(
        "Dokument:\n"
        "Dato/løbenummer: 01.01.1990-111-01\n"
        "Dato/løbenummer: 02.02.1991-222-01\n"
        "Dato/løbenummer: 03.03.1992-333-01\n"
    )
    result = _extract_from_candidate_block_llm(block, "Prompt: {candidate_text}")
    assert len(result) == 3
    date_refs = {s.date_reference for s in result}
    # date_reference er i normaliseret form: YYYYMMDD-NNN
    assert len(date_refs) == 3


def test_attest_candidate_prompt_loader_laeser_den_nye_prompt(tmp_path, monkeypatch):
    prompt_path = tmp_path / "extract_attest_candidate.txt"
    prompt_path.write_text("Prompt: {candidate_text}", encoding="utf-8")
    monkeypatch.setattr(settings, "PROMPTS_DIR", str(tmp_path))
    assert _load_prompt("attest_candidate") == "Prompt: {candidate_text}"


def test_merge_candidate_servitutter_bevarer_attesteret_priority():
    first = Servitut(
        easement_id="srv-1",
        case_id="case-test",
        source_document="doc-a",
        priority=1,
        date_reference="27.06.1934-2094-01",
        title="Dok om passage",
        evidence=[Evidence(chunk_id="c1", document_id="doc-a", page=6, text_excerpt="entry 1")],
    )
    second = Servitut(
        easement_id="srv-2",
        case_id="case-test",
        source_document="doc-a",
        priority=5,
        date_reference="01.11.1954-316-01",
        title="Dok om bebyggelse",
        evidence=[Evidence(chunk_id="c2", document_id="doc-a", page=7, text_excerpt="entry 2")],
    )

    merged = merge_candidate_servitutter([second, first])

    assert [item.priority for item in merged] == [1, 5]


# ---------------------------------------------------------------------------
# run_attest_extraction (integration, mocked LLM)
# ---------------------------------------------------------------------------

def test_run_attest_extraction_koebenhavn_mønster(monkeypatch):
    """Simulér København: Hæftelser pg 3-5, Servitutter fra pg 6.

    Output må IKKE inkludere pantebrev-entries.
    """
    pantebrev_entry = (
        "Afgiftspantebrev:\n"
        "Dato/løbenummer: 07.01.2014-1005068673\n"
        "Prioritet: 17\n"
        "Hovedstol: 1.622.000 DKK\n"
        "Senest påtegnet:\n"
        "Dato: 01.02.2018 12:41:01\n"
    )
    chunks = [
        _chunk("c1", 1, 0, "Adkomster\nEjer info"),
        _chunk("c2", 3, 0, "Hæftelser\nPantebrev prioritet 6..."),
        _chunk("c3", 6, 0, pantebrev_entry + "Servitutter\n" + _ENTRY_1),
        _chunk("c4", 7, 0, _ENTRY_2),
    ]

    servitut_json = (
        '[{"is_servitut_candidate": true, "date_reference": "%s", '
        '"title": "Test", "archive_number": null, "registered_at": null, '
        '"applies_to_parcel_numbers": [], "raw_parcel_references": [], '
        '"raw_scope_text": null, "scope_source": "attest", "confidence": 1.0}]'
    )
    call_texts: list[str] = []

    def mock_llm(prompt, **kwargs):
        call_texts.append(prompt)
        # Returner date_ref baseret på hvad der er i prompt
        if "27.06.1934-2094-01" in prompt:
            return servitut_json % "27.06.1934-2094-01"
        if "01.11.1954-316-01" in prompt:
            return servitut_json % "01.11.1954-316-01"
        return "[]"

    monkeypatch.setattr("app.services.attest.attest_extractor.generate_text", mock_llm)
    monkeypatch.setattr(
        "app.services.attest.attest_extractor._load_prompt",
        lambda name: "Prompt: {candidate_text}",
    )

    result = run_attest_extraction(chunks, "case-test", "doc-test")

    # Ingen af LLM-kaldene måtte se Afgiftspantebrev-teksten
    for prompt in call_texts:
        assert "Afgiftspantebrev" not in prompt
        assert "1.622.000 DKK" not in prompt

    assert len(result) == 2
    date_refs = {s.date_reference for s in result}
    assert any("2094" in dr for dr in date_refs)  # 27.06.1934-2094-01 normaliseret
    assert any("316" in dr for dr in date_refs)   # 01.11.1954-316-01 normaliseret


def test_run_attest_extraction_servitutter_mangler_raises():
    """Hvis headers er fundet men Servitutter mangler → ServitutterSectionNotFoundError."""
    chunks = [
        _chunk("c1", 1, 0, "Adkomster\nEjer info"),
        _chunk("c2", 2, 0, "Hæftelser\nPantebrev..."),
    ]
    with pytest.raises(ServitutterSectionNotFoundError):
        run_attest_extraction(chunks, "case-test", "doc-test")
