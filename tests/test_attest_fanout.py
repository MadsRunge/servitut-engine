"""Tests for app/services/attest/fanout.py"""
import pytest
from app.models.attest import DeclarationBlock
from app.services.attest.fanout import fan_out_registration_entries, validate_date_reference


def _block(
    fanout_date_refs=None,
    raw_scope_text="",
    raw_parcel_references=None,
    status="aktiv",
    archive_number=None,
    title="Test deklaration",
) -> DeclarationBlock:
    return DeclarationBlock(
        block_id="testblock01",
        case_id="case-test",
        document_id="doc-test",
        page_start=1,
        page_end=3,
        source_segment_ids=["seg-0000"],
        title=title,
        archive_number=archive_number,
        raw_scope_text=raw_scope_text,
        raw_parcel_references=raw_parcel_references or [],
        has_aflysning=status == "aflyst",
        status=status,
        fanout_date_refs=fanout_date_refs or [],
    )


CASE_ID = "case-test"


# ---------------------------------------------------------------------------
# validate_date_reference
# ---------------------------------------------------------------------------

def test_validering_accepterer_standard_format():
    assert validate_date_reference("01.02.2005-112233") == "20050201-112233"


def test_validering_accepterer_format_med_mellemrum():
    assert validate_date_reference("01.02.2005 - 112233") == "20050201-112233"


def test_validering_accepterer_bindestreg_skråstreg():
    assert validate_date_reference("01-02-2005/112233") == "20050201-112233"


def test_validering_afviser_ingen_løbenummer():
    assert validate_date_reference("01.02.2005-") is None


def test_validering_afviser_ugyldig_dato():
    assert validate_date_reference("32.13.2005-112233") is None


def test_validering_afviser_tom_streng():
    assert validate_date_reference("") is None


def test_validering_afviser_tilfældig_tekst():
    assert validate_date_reference("ingen dato her") is None


# ---------------------------------------------------------------------------
# Fan-out: 0 gyldige date_refs → ([], False)
# ---------------------------------------------------------------------------

def test_ingen_date_refs_giver_resolved_false():
    block = _block(fanout_date_refs=[], raw_scope_text="Ingen dato her")
    entries, resolved = fan_out_registration_entries(block, CASE_ID)
    assert resolved is False
    assert entries == []


def test_kun_ugyldige_date_refs_giver_resolved_false():
    block = _block(fanout_date_refs=["ikke-en-dato", "heller-ikke"])
    entries, resolved = fan_out_registration_entries(block, CASE_ID)
    assert resolved is False
    assert entries == []


# ---------------------------------------------------------------------------
# Fan-out: 1 gyldig date_ref → ([entry], True), is_fanout_entry=False
# ---------------------------------------------------------------------------

def test_en_date_ref_giver_en_entry_ikke_fanout():
    block = _block(fanout_date_refs=["01.02.2005-112233"])
    entries, resolved = fan_out_registration_entries(block, CASE_ID)
    assert resolved is True
    assert len(entries) == 1
    assert entries[0].is_fanout_entry is False
    assert entries[0].date_reference == "20050201-112233"


def test_en_date_ref_arver_titel_fra_blok():
    block = _block(fanout_date_refs=["01.02.2005-112233"], title="Deklaration vedr. hegn")
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    assert entries[0].title == "Deklaration vedr. hegn"


def test_en_date_ref_arver_arkivnummer_fra_blok():
    block = _block(fanout_date_refs=["01.02.2005-112233"], archive_number="40 B 405")
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    assert entries[0].archive_number == "40 B 405"


# ---------------------------------------------------------------------------
# Fan-out: N date_refs → N entries, is_fanout_entry=True
# ---------------------------------------------------------------------------

def test_tre_date_refs_giver_tre_entries():
    block = _block(fanout_date_refs=[
        "01.02.2005-112233",
        "01.03.2006-223344",
        "01.04.2007-334455",
    ])
    entries, resolved = fan_out_registration_entries(block, CASE_ID)
    assert resolved is True
    assert len(entries) == 3
    assert all(e.is_fanout_entry for e in entries)


def test_fanout_entries_har_unikke_date_references():
    block = _block(fanout_date_refs=[
        "01.02.2005-112233",
        "01.03.2006-223344",
        "01.04.2007-334455",
    ])
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    refs = [e.date_reference for e in entries]
    assert len(refs) == len(set(refs))


def test_fanout_entries_har_unikke_entry_ids():
    block = _block(fanout_date_refs=[
        "01.02.2005-112233",
        "01.03.2006-223344",
        "01.04.2007-334455",
    ])
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    ids = [e.easement_id for e in entries]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Arvet scope (ingen egne parcel-refs) → scope_confidence = 0.35
# ---------------------------------------------------------------------------

def test_arvet_scope_giver_lav_confidence():
    block = _block(
        fanout_date_refs=["01.02.2005-112233", "01.03.2006-223344", "01.04.2007-334455"],
        raw_scope_text="Servitutten gælder generelt for hele ejendommen",
    )
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    for entry in entries:
        assert entry.scope_confidence == pytest.approx(0.35)


# ---------------------------------------------------------------------------
# Eget scope (egne parcel-refs ved siden af date_ref) → scope_confidence = 0.75
# ---------------------------------------------------------------------------

def test_eget_scope_giver_høj_confidence():
    scope_text = (
        "01.02.2005-112233 Vedr. matr. 12a\n"
        "01.03.2006-223344 Vedr. matr. 12b\n"
        "01.04.2007-334455 Vedr. matr. 12c\n"
    )
    block = _block(
        fanout_date_refs=["01.02.2005-112233", "01.03.2006-223344", "01.04.2007-334455"],
        raw_scope_text=scope_text,
    )
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    # Entries med egne parcel-refs har 0.75
    assert any(e.scope_confidence == pytest.approx(0.75) for e in entries)


# ---------------------------------------------------------------------------
# Aflyst blok → alle entries status=aflyst
# ---------------------------------------------------------------------------

def test_aflyst_blok_giver_aflyst_status():
    block = _block(
        fanout_date_refs=["01.02.2005-112233", "01.03.2006-223344", "01.04.2007-334455"],
        status="aflyst",
    )
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    assert all(e.status == "aflyst" for e in entries)


def test_aktiv_blok_giver_aktiv_status():
    block = _block(
        fanout_date_refs=["01.02.2005-112233"],
        status="aktiv",
    )
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    assert entries[0].status == "aktiv"


# ---------------------------------------------------------------------------
# Blanding af gyldige og ugyldige refs → kun gyldige entries
# ---------------------------------------------------------------------------

def test_blanding_gyldige_og_ugyldige_refs():
    block = _block(fanout_date_refs=[
        "01.02.2005-112233",   # gyldig
        "ikke-en-dato",         # ugyldig
        "01.04.2007-334455",   # gyldig
    ])
    entries, resolved = fan_out_registration_entries(block, CASE_ID)
    assert resolved is True
    assert len(entries) == 2


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_entries_har_declaration_block_id():
    block = _block(fanout_date_refs=["01.02.2005-112233", "01.03.2006-223344", "01.04.2007-334455"])
    entries, _ = fan_out_registration_entries(block, CASE_ID)
    for entry in entries:
        assert entry.declaration_block_id == "testblock01"
