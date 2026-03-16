import fitz
import pytest

from app.services.pdf_service import (
    PdfPageRange,
    build_split_suggestion,
    get_pdf_page_count,
    parse_page_ranges,
    split_pdf_bytes,
)


def _build_pdf_bytes(page_count: int) -> bytes:
    pdf = fitz.open()
    try:
        for page_number in range(1, page_count + 1):
            page = pdf.new_page()
            page.insert_text((72, 72), f"Page {page_number}")
        return pdf.tobytes()
    finally:
        pdf.close()


def test_build_split_suggestion_covers_all_pages():
    suggestion = build_split_suggestion(total_pages=230, pages_per_part=100)

    assert suggestion == "1-100 | Del 1\n101-200 | Del 2\n201-230 | Del 3"


def test_parse_page_ranges_rejects_overlap():
    with pytest.raises(ValueError, match="må ikke overlappe"):
        parse_page_ranges("1-10\n10-20", total_pages=50)


def test_parse_page_ranges_supports_labels_and_single_pages():
    ranges = parse_page_ranges("1-3 | Attest\n4\n5-6 | Akt 2", total_pages=6)

    assert ranges == [
        PdfPageRange(start_page=1, end_page=3, label="Attest"),
        PdfPageRange(start_page=4, end_page=4, label=None),
        PdfPageRange(start_page=5, end_page=6, label="Akt 2"),
    ]


def test_split_pdf_bytes_returns_expected_files():
    pdf_bytes = _build_pdf_bytes(page_count=5)
    ranges = [
        PdfPageRange(start_page=1, end_page=2, label="Del 1"),
        PdfPageRange(start_page=3, end_page=5, label=None),
    ]

    outputs = split_pdf_bytes(pdf_bytes, ranges, original_filename="stor fil.pdf")

    assert [name for name, _ in outputs] == [
        "stor fil_Del_1.pdf",
        "stor fil_del-02_p3-5.pdf",
    ]
    assert [get_pdf_page_count(part_bytes) for _, part_bytes in outputs] == [2, 3]
