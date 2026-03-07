import pytest

from app.models.document import PageData
from app.services.chunking_service import chunk_pages
from app.utils.ids import generate_chunk_id


def make_pages(texts):
    return [PageData(page_number=i + 1, text=t) for i, t in enumerate(texts)]


def test_chunk_id_stability():
    id1 = generate_chunk_id("doc-abc", 1, 0)
    id2 = generate_chunk_id("doc-abc", 1, 0)
    assert id1 == id2
    assert len(id1) == 12


def test_chunk_id_uniqueness():
    id1 = generate_chunk_id("doc-abc", 1, 0)
    id2 = generate_chunk_id("doc-abc", 1, 1)
    id3 = generate_chunk_id("doc-abc", 2, 0)
    assert id1 != id2
    assert id1 != id3


def test_basic_chunking():
    pages = make_pages(["Dette er en paragraf.\n\nOg endnu en paragraf."])
    chunks = chunk_pages(pages, "doc-test", "case-test")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.page == 1
        assert chunk.document_id == "doc-test"
        assert chunk.case_id == "case-test"
        assert chunk.text


def test_chunk_page_reference():
    pages = make_pages([
        "Side 1 indhold.",
        "Side 2 indhold.\n\nEndnu mere på side 2.",
    ])
    chunks = chunk_pages(pages, "doc-ref", "case-ref")
    page_numbers = {c.page for c in chunks}
    assert 1 in page_numbers
    assert 2 in page_numbers


def test_chunk_size_limit():
    long_text = "A" * 500 + "\n\n" + "B" * 500 + "\n\n" + "C" * 500 + "\n\n" + "D" * 500
    pages = make_pages([long_text])
    chunks = chunk_pages(pages, "doc-big", "case-big")
    for chunk in chunks:
        assert len(chunk.text) <= 2200  # Some tolerance for overlap


def test_empty_page_skipped():
    pages = make_pages(["", "Noget indhold her."])
    chunks = chunk_pages(pages, "doc-empty", "case-empty")
    assert len(chunks) >= 1
    assert all(c.text for c in chunks)


def test_chunk_index_sequential():
    pages = make_pages(["Para 1.\n\nPara 2.\n\nPara 3.\n\nPara 4.\n\nPara 5."])
    chunks = chunk_pages(pages, "doc-seq", "case-seq")
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))
