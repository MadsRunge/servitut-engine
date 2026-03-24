"""Tests for app/services/attest/assembler.py"""
from app.models.attest import AttestBlockType, AttestSegment
from app.services.attest.assembler import assemble_declaration_blocks


def _seg(
    idx: int,
    block_type: str,
    text: str = "",
    page_start: int = 1,
    page_end: int = 1,
) -> AttestSegment:
    return AttestSegment(
        segment_id=f"doc-segment-{idx:04d}",
        case_id="case-test",
        document_id="doc-test",
        segment_index=idx,
        page_start=page_start,
        page_end=page_end,
        text=text,
        text_hash=f"hash-{idx}",
        block_type=block_type,
    )


CASE_ID = "case-test"
DOC_ID  = "doc-test"


# ---------------------------------------------------------------------------
# Simpel case (1:1)
# ---------------------------------------------------------------------------

def test_simpel_case_giver_en_blok():
    segments = [
        _seg(0, "declaration_start", "Prioritet 1\nDeklaration vedr. hegn\n01.02.2005-112233"),
        _seg(1, "declaration_continuation", "Vedrørende matr.nr. 12a"),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert len(blocks) == 1
    assert blocks[0].page_start == 1
    assert len(blocks[0].source_segment_ids) == 2


def test_to_start_segmenter_giver_to_blokke():
    segments = [
        _seg(0, "declaration_start", "Prioritet 1", page_start=1, page_end=1),
        _seg(1, "declaration_start", "Prioritet 2", page_start=2, page_end=2),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert len(blocks) == 2


# ---------------------------------------------------------------------------
# Fan-out (Aalborg-mønster)
# ---------------------------------------------------------------------------

def test_fanout_block_samler_date_refs():
    fanout_text = (
        "Anmærkninger\n"
        "01.02.2005-112233\n"
        "01.03.2006-223344\n"
        "01.04.2007-334455\n"
        "01.05.2008-445566\n"
    )
    segments = [
        _seg(0, "declaration_start", "Prioritet 1\nDeklaration vedr. hegn"),
        _seg(1, "anmerkning_fanout", fanout_text),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert len(blocks) == 1
    assert len(blocks[0].fanout_date_refs) == 4


def test_fanout_fra_to_sektioner_akkumuleres():
    """Aalborg-mønster: fan-out refs fra to FANOUT-segmenter samles."""
    fanout_a = "Anmærkninger\n01.02.2005-112233\n01.03.2006-223344\n01.04.2007-334455\n"
    fanout_b = "Anmærkninger\n01.05.2008-445566\n01.06.2009-556677\n01.07.2010-667788\n"
    segments = [
        _seg(0, "declaration_start", "Prioritet 232\nDeklaration vedr. hegn"),
        _seg(1, "anmerkning_fanout", fanout_a),
        _seg(2, "anmerkning_fanout", fanout_b),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert len(blocks) == 1
    assert len(blocks[0].fanout_date_refs) == 6


# ---------------------------------------------------------------------------
# Aflyst
# ---------------------------------------------------------------------------

def test_aflysning_segment_sætter_has_aflysning():
    segments = [
        _seg(0, "declaration_start", "Prioritet 5\nVejret"),
        _seg(1, "aflysning", "Aflyst den 01.01.2015"),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert len(blocks) == 1
    assert blocks[0].has_aflysning is True
    assert blocks[0].status == "aflyst"


def test_blok_uden_aflysning_faar_status_aktiv():
    segments = [
        _seg(0, "declaration_start", "Prioritet 3\nByggelinje"),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert blocks[0].status == "aktiv"


# ---------------------------------------------------------------------------
# Orphan (continuation uden start)
# ---------------------------------------------------------------------------

def test_continuation_uden_start_giver_orphan_blok():
    segments = [
        _seg(0, "declaration_continuation", "Servitutten gælder for matr.nr. 12a"),
    ]
    blocks = assemble_declaration_blocks(segments, CASE_ID, DOC_ID)
    assert len(blocks) == 1


# ---------------------------------------------------------------------------
# Tom liste
# ---------------------------------------------------------------------------

def test_tom_segment_liste_giver_tom_blok_liste():
    assert assemble_declaration_blocks([], CASE_ID, DOC_ID) == []


# ---------------------------------------------------------------------------
# LLM-fallback
# ---------------------------------------------------------------------------

def test_unknown_segment_reklassificeres_via_llm_callback():
    """UNKNOWN-segmenter sendes til llm_classify og genbehandles."""
    segments = [
        _seg(0, "declaration_start", "Prioritet 1"),
        _seg(1, "unknown", "Noget tekst der ikke ligner noget"),
    ]
    # LLM-fallback returnerer CONTINUATION → merges ind i blokken
    blocks = assemble_declaration_blocks(
        segments,
        CASE_ID,
        DOC_ID,
        llm_classify=lambda text: AttestBlockType.DECLARATION_CONTINUATION,
    )
    assert len(blocks) == 1
    assert len(blocks[0].source_segment_ids) == 2


def test_unknown_segment_der_forbliver_unknown_merges_ind():
    """Segmenter der forbliver UNKNOWN efter LLM merges ind i aktuel blok."""
    segments = [
        _seg(0, "declaration_start", "Prioritet 1"),
        _seg(1, "unknown", "???"),
    ]
    blocks = assemble_declaration_blocks(
        segments,
        CASE_ID,
        DOC_ID,
        llm_classify=lambda text: AttestBlockType.UNKNOWN,
    )
    assert len(blocks) == 1
