"""Tests for app/services/attest/segmenter.py"""
from app.models.attest import AttestBlockType
from app.services.attest.segmenter import classify_segment_block_type


def _make_text(*lines: str) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DECLARATION_START
# ---------------------------------------------------------------------------

def test_prioritet_linje_giver_declaration_start():
    text = _make_text(
        "Prioritet 14",
        "Deklaration vedr. hegn og beplantning",
        "Dato/løbenummer: 01.02.2005-112233",
    )
    assert classify_segment_block_type(text) == AttestBlockType.DECLARATION_START


def test_dokument_linje_giver_declaration_start():
    text = _make_text(
        "Dokument 3",
        "Servitut om vejret",
    )
    assert classify_segment_block_type(text) == AttestBlockType.DECLARATION_START


def test_dokumenttype_kolon_giver_declaration_start():
    text = _make_text(
        "Dokumenttype: Deklaration",
        "Prioritet: 7",
        "Noget tekst her",
    )
    assert classify_segment_block_type(text) == AttestBlockType.DECLARATION_START


def test_nummereret_post_i_start_giver_declaration_start():
    text = _make_text(
        "14. Deklaration vedrørende beplantning",
        "Dato/løbenummer: 01.02.2000-445566",
    )
    assert classify_segment_block_type(text) == AttestBlockType.DECLARATION_START


# ---------------------------------------------------------------------------
# AFLYSNING
# ---------------------------------------------------------------------------

def test_aflyst_den_dato_giver_aflysning():
    text = _make_text(
        "Servitut vedr. adgangsvej",
        "Aflyst den 15.06.2018",
    )
    assert classify_segment_block_type(text) == AttestBlockType.AFLYSNING


def test_aflyst_dato_uden_den_giver_aflysning():
    text = "Aflyst 01.01.2010 jf. ny registrering"
    assert classify_segment_block_type(text) == AttestBlockType.AFLYSNING


def test_aflyses_giver_aflysning():
    text = "Denne registrering Aflyses ved ny tinglysning"
    assert classify_segment_block_type(text) == AttestBlockType.AFLYSNING


def test_tinglyst_aflysning_giver_aflysning():
    text = "Tinglyst aflysning 05.03.2020"
    assert classify_segment_block_type(text) == AttestBlockType.AFLYSNING


def test_aflysning_tinglyst_giver_aflysning():
    text = "Aflysning tinglyst den 12.12.2019"
    assert classify_segment_block_type(text) == AttestBlockType.AFLYSNING


def test_tabelcelle_aflyst_giver_aflysning():
    text = _make_text(
        "Status:",
        "Aflyst",
        "Dato: 01.01.2000",
    )
    assert classify_segment_block_type(text) == AttestBlockType.AFLYSNING


def test_fritekst_delvis_aflysning_giver_ikke_aflysning():
    """'delvis aflysning' som fritekst-omtale må IKKE klassificeres som AFLYSNING."""
    text = _make_text(
        "Anmærkninger",
        "Se notat om delvis aflysning af arealdelen.",
        "01.02.2005-112233",
        "01.03.2006-223344",
        "01.04.2007-334455",
    )
    # Har Anmærkninger + 3 date_refs → FANOUT (aflysning-fraserne er ikke eksplicitte)
    result = classify_segment_block_type(text)
    assert result != AttestBlockType.AFLYSNING


# ---------------------------------------------------------------------------
# ANMERKNING_FANOUT
# ---------------------------------------------------------------------------

def test_anmærkninger_med_mange_date_refs_giver_fanout():
    text = _make_text(
        "Anmærkninger",
        "01.02.2005-112233",
        "01.03.2006-223344",
        "01.04.2007-334455",
        "01.05.2008-445566",
    )
    assert classify_segment_block_type(text) == AttestBlockType.ANMERKNING_FANOUT


def test_anmærkninger_med_for_faa_date_refs_giver_text():
    text = _make_text(
        "Anmærkninger",
        "01.02.2005-112233",
        "Yderligere oplysninger om vejretsservitutten",
    )
    assert classify_segment_block_type(text) == AttestBlockType.ANMERKNING_TEXT


def test_anmærkninger_uden_date_refs_giver_text():
    text = _make_text(
        "Anmærkninger:",
        "Vedrørende matr.nr. 38b. Se akt 40 B 405.",
    )
    assert classify_segment_block_type(text) == AttestBlockType.ANMERKNING_TEXT


# ---------------------------------------------------------------------------
# DECLARATION_CONTINUATION
# ---------------------------------------------------------------------------

def test_fritekst_uden_header_giver_continuation():
    text = _make_text(
        "Servitutten gælder for matr.nr. 12a og 12b af Viborg Jorder.",
        "Indehaveren af servitutten er Vejdirektoratet.",
    )
    assert classify_segment_block_type(text) == AttestBlockType.DECLARATION_CONTINUATION


# ---------------------------------------------------------------------------
# UNKNOWN
# ---------------------------------------------------------------------------

def test_tom_tekst_giver_unknown():
    assert classify_segment_block_type("") == AttestBlockType.UNKNOWN
    assert classify_segment_block_type("   \n\n  ") == AttestBlockType.UNKNOWN
