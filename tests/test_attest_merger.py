"""Tests for den opdaterede merge-logik i attest_pipeline.py.

Fokus: fan-out entries må ikke merges på fælles archive_number eller titel.
"""
from app.models.servitut import Evidence, Servitut
from app.services.extraction.attest_pipeline import merge_attest_servitutter


def _entry(
    date_reference=None,
    archive_number=None,
    title="Deklaration vedr. hegn",
    is_fanout_entry=False,
    declaration_block_id=None,
    page=1,
    doc_id="doc-test",
) -> Servitut:
    evidence = [Evidence(chunk_id="c1", document_id=doc_id, page=page, text_excerpt="tekst")]
    return Servitut(
        easement_id=f"entry-{date_reference or archive_number or title}-{page}",
        case_id="case-test",
        source_document=doc_id,
        date_reference=date_reference,
        archive_number=archive_number,
        title=title,
        evidence=evidence,
        is_fanout_entry=is_fanout_entry,
        declaration_block_id=declaration_block_id,
    )


# ---------------------------------------------------------------------------
# Fan-out entries: må KUN merges på exact date_reference
# ---------------------------------------------------------------------------

def test_fanout_entries_merges_ikke_på_fælles_archive_number():
    """Tre fan-out entries med samme archive_number skal forblive tre separate."""
    entries = [
        _entry(
            date_reference=f"01.0{i}.2005-11223{i}",
            archive_number="40 B 405",
            is_fanout_entry=True,
            declaration_block_id="block-01",
            page=i,
        )
        for i in range(1, 4)
    ]
    merged = merge_attest_servitutter(entries)
    assert len(merged) == 3, f"Forventede 3 entries, fik {len(merged)}"


def test_fanout_entries_merges_ikke_på_titel_og_page_proximity():
    """Fan-out entries med identisk titel og nærliggende sider skal ikke merges."""
    entries = [
        _entry(
            date_reference=f"01.0{i}.2005-11223{i}",
            title="Deklaration vedr. hegn",
            is_fanout_entry=True,
            declaration_block_id="block-01",
            page=i,
        )
        for i in range(1, 4)
    ]
    merged = merge_attest_servitutter(entries)
    assert len(merged) == 3


def test_fanout_entries_med_samme_date_reference_merges():
    """Cross-segment duplikat: fan-out entries med identisk date_reference merges til én."""
    entries = [
        _entry(
            date_reference="01.02.2005-112233",
            is_fanout_entry=True,
            declaration_block_id="block-01",
            page=1,
        ),
        _entry(
            date_reference="01.02.2005-112233",  # duplikat fra overlap-segment
            is_fanout_entry=True,
            declaration_block_id="block-01",
            page=2,
        ),
    ]
    merged = merge_attest_servitutter(entries)
    assert len(merged) == 1


# ---------------------------------------------------------------------------
# Ikke-fanout entries: bevarer eksisterende merge-logik
# ---------------------------------------------------------------------------

def test_ikke_fanout_entries_merges_på_archive_number():
    """Ikke-fanout entries med identisk archive_number merges (gammel adfærd bevaret)."""
    entries = [
        _entry(
            date_reference="01.02.2005-112233",
            archive_number="40 B 405",
            is_fanout_entry=False,
            page=1,
        ),
        _entry(
            date_reference=None,
            archive_number="40 B 405",
            is_fanout_entry=False,
            page=2,
        ),
    ]
    merged = merge_attest_servitutter(entries)
    assert len(merged) == 1


def test_ikke_fanout_entries_merges_på_titel_og_page():
    """Ikke-fanout entries med identisk titel og nærliggende sider merges."""
    entries = [
        _entry(
            date_reference=None,
            archive_number=None,
            title="Vejret til naboejendommen",
            is_fanout_entry=False,
            page=3,
            doc_id="doc-same",
        ),
        _entry(
            date_reference=None,
            archive_number=None,
            title="Vejret til naboejendommen",
            is_fanout_entry=False,
            page=4,
            doc_id="doc-same",
        ),
    ]
    merged = merge_attest_servitutter(entries)
    assert len(merged) == 1


# ---------------------------------------------------------------------------
# Blanding: fanout og ikke-fanout i samme liste
# ---------------------------------------------------------------------------

def test_blanding_fanout_og_ikke_fanout():
    """Fan-out entries og ikke-fanout entries behandles korrekt i blanding."""
    entries = [
        # 3 fanout entries — må IKKE merges på archive_number
        _entry("01.02.2005-111111", archive_number="40 B 1", is_fanout_entry=True,
               declaration_block_id="block-A", page=1),
        _entry("01.03.2006-222222", archive_number="40 B 1", is_fanout_entry=True,
               declaration_block_id="block-A", page=2),
        _entry("01.04.2007-333333", archive_number="40 B 1", is_fanout_entry=True,
               declaration_block_id="block-A", page=3),
        # 1 ikke-fanout entry med andet arkivnr
        _entry("01.05.2008-444444", archive_number="50 C 2", is_fanout_entry=False, page=4),
    ]
    merged = merge_attest_servitutter(entries)
    assert len(merged) == 4
