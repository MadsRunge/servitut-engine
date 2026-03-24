"""Tests for app/services/attest/scope_resolver.py"""
import pytest
from app.models.servitut import Servitut
from app.services.attest.scope_resolver import REVIEW_THRESHOLD, resolve_scope


def _entry(
    raw_scope_text="",
    raw_parcel_references=None,
    is_fanout_entry=False,
    scope_confidence=0.0,
    date_reference="01.02.2005-112233",
    **kwargs,
) -> Servitut:
    return Servitut(
        easement_id="entry-test",
        case_id="case-test",
        source_document="doc-test",
        date_reference=date_reference,
        raw_scope_text=raw_scope_text,
        raw_parcel_references=raw_parcel_references or [],
        is_fanout_entry=is_fanout_entry,
        scope_confidence=scope_confidence,
        **kwargs,
    )


CASE_MATRIKLER = ["12a", "12b", "38b"]
PRIMARY = "12a"


# ---------------------------------------------------------------------------
# EXPLICIT_PARCEL_LIST — alle matcher
# ---------------------------------------------------------------------------

def test_explicit_alle_matchet_giver_095():
    entry = _entry(raw_scope_text="Vedr. matr.nr. 12a og 12b")
    resolved = resolve_scope([entry], CASE_MATRIKLER, primary_parcel=PRIMARY)
    assert resolved[0].scope_confidence == pytest.approx(0.95)
    assert resolved[0].scope_type == "explicit_parcel_list"


def test_explicit_alle_matchet_sætter_applies_to_parcel_numbers():
    entry = _entry(raw_scope_text="Vedr. matr.nr. 12a")
    resolved = resolve_scope([entry], CASE_MATRIKLER, primary_parcel=PRIMARY)
    assert "12a" in resolved[0].applies_to_parcel_numbers


# ---------------------------------------------------------------------------
# EXPLICIT_PARCEL_LIST — delvist match
# ---------------------------------------------------------------------------

def test_explicit_delvist_match_giver_075():
    # 12a matcher, 99z matcher ikke
    entry = _entry(raw_scope_text="Vedr. matr.nr. 12a og 99z")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_confidence == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# WHOLE_PROPERTY
# ---------------------------------------------------------------------------

def test_hele_ejendommen_giver_080():
    entry = _entry(raw_scope_text="Gælder hele ejendommen")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_confidence == pytest.approx(0.80)
    assert resolved[0].scope_type == "whole_property"


def test_samtlige_parceller_giver_whole_property():
    entry = _entry(raw_scope_text="Vedr. samtlige parceller")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_type == "whole_property"


def test_al_grund_giver_whole_property():
    entry = _entry(raw_scope_text="al grund under matr.nr.")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_type == "whole_property"


# ---------------------------------------------------------------------------
# AREA_DESCRIPTION
# ---------------------------------------------------------------------------

def test_geografisk_fritekst_med_signal_giver_060():
    entry = _entry(raw_scope_text="Langs den eksisterende sti mod skov")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_confidence == pytest.approx(0.60)
    assert resolved[0].scope_type == "area_description"


def test_fritekst_uden_signal_giver_040():
    entry = _entry(raw_scope_text="Noget generisk fritekst uden matrikel eller geografi")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_confidence == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# UNKNOWN
# ---------------------------------------------------------------------------

def test_tom_scope_giver_unknown_og_lav_confidence():
    entry = _entry(raw_scope_text="", raw_parcel_references=[])
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert resolved[0].scope_type == "unknown"
    assert resolved[0].scope_confidence <= 0.10


# ---------------------------------------------------------------------------
# Review-flag
# ---------------------------------------------------------------------------

def test_lav_confidence_tilføjer_review_required_flag():
    entry = _entry(raw_scope_text="")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert "review_required" in resolved[0].flags


def test_høj_confidence_tilføjer_ikke_review_flag():
    entry = _entry(raw_scope_text="Vedr. matr.nr. 12a")
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    assert "review_required" not in resolved[0].flags


def test_review_threshold_er_0_50():
    assert REVIEW_THRESHOLD == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# applies_to_primary_parcel
# ---------------------------------------------------------------------------

def test_primary_parcel_i_matches_giver_true():
    entry = _entry(raw_scope_text="Vedr. matr.nr. 12a og 12b")
    resolved = resolve_scope([entry], CASE_MATRIKLER, primary_parcel="12a")
    assert resolved[0].applies_to_primary_parcel is True


def test_primary_parcel_ikke_i_matches_giver_false():
    entry = _entry(raw_scope_text="Vedr. matr.nr. 38b")
    resolved = resolve_scope([entry], CASE_MATRIKLER, primary_parcel="12a")
    assert resolved[0].applies_to_primary_parcel is False


# ---------------------------------------------------------------------------
# Fanout-arv bevarender confidence fra fanout.py
# ---------------------------------------------------------------------------

def test_fanout_entry_med_arvet_scope_har_lav_confidence():
    entry = _entry(
        is_fanout_entry=True,
        raw_scope_text="Servitutten gælder generelt",
        scope_confidence=0.35,
    )
    resolved = resolve_scope([entry], CASE_MATRIKLER)
    # scope_resolver må ikke løfte confidence for fanout entries uden egne refs
    assert resolved[0].scope_confidence < REVIEW_THRESHOLD
    assert "review_required" in resolved[0].flags


# ---------------------------------------------------------------------------
# Tom liste
# ---------------------------------------------------------------------------

def test_tom_entries_liste_giver_tom_resultat():
    assert resolve_scope([], CASE_MATRIKLER) == []
