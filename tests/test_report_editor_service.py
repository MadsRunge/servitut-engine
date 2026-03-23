from app.models.report import Report, ReportEntry
from app.services.report_editor_service import report_to_editor_rows, update_report_from_editor


def _make_report() -> Report:
    return Report(
        report_id="rep-test1234",
        case_id="case-test",
        target_parcel_numbers=["0001o"],
        available_parcel_numbers=["0001o", "0001v"],
        entries=[
            ReportEntry(
                sequence_number=1,
                date_reference="11.03.1974-1904-40",
                raw_text="Original tekst",
                description="Første servitut",
                beneficiary="Kommunen",
                disposition="Rådighed",
                legal_type="Offentligretlig",
                action="Ingen handling",
                relevant_for_project=True,
                scope="Ja",
                scope_detail="Vedr. matr.nr. 0001o",
                easement_id="srv-1",
            ),
            ReportEntry(
                sequence_number=2,
                date_reference="04.11.1966-5973-40",
                description="Anden servitut",
                beneficiary="Amtet",
                disposition="Tilstand",
                legal_type="Privatretlig",
                action="Kræver vurdering",
                relevant_for_project=False,
                scope="Måske",
                easement_id="srv-2",
            ),
        ],
        notes="Original note",
    )


def test_report_to_editor_rows_includes_editable_fields():
    report = _make_report()

    rows = report_to_editor_rows(report)

    assert rows[0]["description"] == "Første servitut"
    assert rows[0]["raw_text"] == "Original tekst"
    assert rows[1]["scope"] == "Måske"
    assert rows[1]["easement_id"] == "srv-2"


def test_amt_warning_survives_editor_roundtrip():
    """beneficiary_amt_warning=True should be preserved through report_to_editor_rows → update_report_from_editor."""
    report = _make_report()
    report.entries[0].beneficiary_amt_warning = True

    rows = report_to_editor_rows(report)
    assert rows[0]["beneficiary_amt_warning"] is True

    updated = update_report_from_editor(report.model_copy(deep=True), rows)
    assert updated.entries[0].beneficiary_amt_warning is True


def test_update_report_from_editor_sorts_and_rebuilds_markdown():
    report = _make_report()
    edited_rows = [
        {
            "sequence_number": 20,
            "date_reference": "04.11.1966-5973-40",
            "raw_text": "",
            "description": "Flyttet ned",
            "beneficiary": "Regionen",
            "disposition": "Tilstand",
            "legal_type": "Privatretlig",
            "action": "Ukendt indhold",
            "scope": "Nej",
            "scope_detail": "",
            "relevant_for_project": False,
            "easement_id": "srv-2",
        },
        {
            "sequence_number": 1,
            "date_reference": "11.03.1974-1904-40",
            "raw_text": "Ny tekst",
            "description": "Flyttet op",
            "beneficiary": "Kommunen",
            "disposition": "Rådighed",
            "legal_type": "Offentligretlig",
            "action": "Akt ikke gennemgået.",
            "scope": "Ja",
            "scope_detail": "Vedr. matr.nr. 0001o og 0001v",
            "relevant_for_project": True,
            "easement_id": "srv-1",
        },
    ]

    updated = update_report_from_editor(report, edited_rows, notes="Redigeret note")

    assert updated.manually_edited is True
    assert updated.edited_at is not None
    assert updated.notes == "Redigeret note"
    assert updated.entries[0].sequence_number == 1
    assert updated.entries[0].description == "Flyttet op"
    assert updated.entries[1].sequence_number == 2
    assert updated.entries[1].description == "Flyttet ned"
    assert updated.entries[1].raw_text is None
    assert updated.markdown_content is not None
    assert "Flyttet op" in updated.markdown_content
    assert "Flyttet ned" in updated.markdown_content
