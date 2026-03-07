from unittest.mock import patch

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.servitut import Servitut
from app.services.extraction import llm_extractor
from app.services import extraction_service


def make_chunk(doc_id: str, page: int = 1, text: str = "servitut byggelinje vejret") -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-{page:02d}",
        document_id=doc_id,
        case_id="case-test",
        page=page,
        text=text,
        chunk_index=page - 1,
        char_start=0,
        char_end=len(text),
    )


class FakeFuture:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class SpyExecutor:
    def __init__(self, max_workers, thread_name_prefix=None):
        self.max_workers = max_workers
        self.thread_name_prefix = thread_name_prefix
        self.submitted = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        future = FakeFuture(fn(*args, **kwargs))
        self.submitted.append((fn, args, kwargs, future))
        return future


def test_extract_from_doc_chunks_uses_parallel_executor(monkeypatch):
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 4)
    doc_chunks = {
        "doc-a": [make_chunk("doc-a")],
        "doc-b": [make_chunk("doc-b")],
    }

    monkeypatch.setattr(
        llm_extractor,
        "ThreadPoolExecutor",
        lambda max_workers, thread_name_prefix=None: SpyExecutor(max_workers, thread_name_prefix),
    )
    monkeypatch.setattr(
        llm_extractor,
        "wait",
        lambda pending, timeout, return_when: (set(reversed(list(pending))), set()),
    )
    with patch(
        "app.services.extraction.llm_extractor._extract_document_servitutter",
        side_effect=[
            [Servitut(servitut_id="srv-a", case_id="case-test", source_document="doc-a")],
            [Servitut(servitut_id="srv-b", case_id="case-test", source_document="doc-b")],
        ],
    ) as mock_extract:
        result = extraction_service._extract_from_doc_chunks(doc_chunks, "case-test", "akt")

    assert [srv.source_document for srv in result] == ["doc-a", "doc-b"]
    assert mock_extract.call_count == 2


def test_extract_from_doc_chunks_respects_concurrency_limit(monkeypatch):
    captured = {}
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 2)

    def make_executor(max_workers, thread_name_prefix=None):
        captured["max_workers"] = max_workers
        captured["thread_name_prefix"] = thread_name_prefix
        return SpyExecutor(max_workers, thread_name_prefix)

    monkeypatch.setattr(llm_extractor, "ThreadPoolExecutor", make_executor)
    monkeypatch.setattr(
        llm_extractor,
        "wait",
        lambda pending, timeout, return_when: (set(pending), set()),
    )
    with patch(
        "app.services.extraction.llm_extractor._extract_document_servitutter",
        return_value=[],
    ):
        extraction_service._extract_from_doc_chunks(
            {
                "doc-a": [make_chunk("doc-a")],
                "doc-b": [make_chunk("doc-b")],
                "doc-c": [make_chunk("doc-c")],
            },
            "case-test",
            "akt",
        )

    assert captured["max_workers"] == 2
    assert captured["thread_name_prefix"] == "extract-doc"


def test_extract_servitutter_preserves_input_document_order(monkeypatch):
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 4)

    def fake_load_document(case_id: str, doc_id: str):
        class FakeDocument:
            document_type = "akt"

        return FakeDocument()

    monkeypatch.setattr("app.services.extraction_service.storage_service.load_document", fake_load_document)
    monkeypatch.setattr(
        extraction_service,
        "_dedup_akt_servitutter",
        lambda servitutter: servitutter,
    )
    with patch(
        "app.services.extraction_service._extract_from_doc_chunks",
        return_value=[
            Servitut(servitut_id="srv-1", case_id="case-test", source_document="doc-z"),
            Servitut(servitut_id="srv-2", case_id="case-test", source_document="doc-a"),
        ],
    ):
        result = extraction_service.extract_servitutter(
            [
                make_chunk("doc-z"),
                make_chunk("doc-a"),
            ],
            "case-test",
        )

    assert [srv.source_document for srv in result] == ["doc-z", "doc-a"]


def test_extract_document_servitutter_emits_progress_events():
    events = []
    chunk = make_chunk("doc-a")

    with patch(
        "app.services.extraction.llm_extractor.generate_text",
        return_value='[{"title":"Test","confidence":0.8}]',
    ):
        result = extraction_service._extract_document_servitutter(
            "doc-a",
            [chunk],
            "case-test",
            "Prompt {chunks_text}",
            "akt",
            progress_callback=events.append,
        )

    assert len(result) == 1
    assert [event["stage"] for event in events] == [
        "running",
        "requesting",
        "parsing",
        "completed",
    ]
    assert events[-1]["servitut_count"] == 1
