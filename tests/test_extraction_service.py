from unittest.mock import patch
from datetime import date

from app.core.config import settings
from app.models.attest import AttestBlockType, AttestPipelineState, AttestSegment, DeclarationBlock
from app.models.chunk import Chunk
from app.models.document import Document, PageData
from app.models.servitut import Evidence, Servitut
from app.services.extraction import attest_pipeline, llm_extractor
from app.services.extraction import enricher as enricher_module
from app.services.extraction.enricher import enrich_canonical_list, select_candidate_chunks
from app.services.extraction.merger import _enrich_canonical
from app.services import extraction_service
from app.services.chunking_service import chunk_pages


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
            [Servitut(easement_id="srv-a", case_id="case-test", source_document="doc-a")],
            [Servitut(easement_id="srv-b", case_id="case-test", source_document="doc-b")],
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

    monkeypatch.setattr(
        "app.services.extraction_service.storage_service.list_documents",
        lambda session, case_id: [
            Document(
                document_id="doc-z",
                case_id=case_id,
                filename="doc-z.pdf",
                file_path="storage/cases/case-test/documents/doc-z/original.pdf",
                document_type="akt",
            ),
            Document(
                document_id="doc-a",
                case_id=case_id,
                filename="doc-a.pdf",
                file_path="storage/cases/case-test/documents/doc-a/original.pdf",
                document_type="akt",
            ),
        ],
    )
    monkeypatch.setattr(
        extraction_service,
        "_dedup_akt_servitutter",
        lambda servitutter: servitutter,
    )
    with patch(
        "app.services.extraction_service._extract_from_doc_chunks",
        return_value=[
            Servitut(easement_id="srv-1", case_id="case-test", source_document="doc-z"),
            Servitut(easement_id="srv-2", case_id="case-test", source_document="doc-a"),
        ],
    ):
        result = extraction_service.extract_servitutter(
            None,
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


def test_parse_llm_response_accepts_wrapped_json_object():
    response = """
    ```json
    {
      "servitutter": [
        {"date_reference": "01.01.2000-1-1", "title": "Test"}
      ]
    }
    ```
    """

    parsed = llm_extractor._parse_llm_response(response)

    assert parsed == [{"date_reference": "01.01.2000-1-1", "title": "Test"}]


def test_parse_llm_response_accepts_single_servitut_object():
    response = '{"date_reference":"01.01.2000-1-1","archive_number":"40 B 405","title":"Test"}'

    parsed = llm_extractor._parse_llm_response(response)

    assert parsed == [
        {
            "date_reference": "01.01.2000-1-1",
            "archive_number": "40 B 405",
            "title": "Test",
        }
    ]


def test_extract_document_servitutter_handles_wrapped_response():
    chunk = make_chunk("doc-a")

    with patch(
        "app.services.extraction.llm_extractor.generate_text",
        return_value='{"servitutter":[{"title":"Test","date_reference":"01.01.2000-1-1","confidence":0.8}]}',
    ):
        result = extraction_service._extract_document_servitutter(
            "doc-a",
            [chunk],
            "case-test",
            "Prompt {chunks_text}",
            "akt",
        )

    assert len(result) == 1
    assert result[0].title == "Test"
    assert result[0].date_reference == "01.01.2000-1-1"


def test_extract_document_servitutter_uses_larger_token_budget_for_attest():
    chunk = make_chunk("doc-a")

    with patch(
        "app.services.extraction.llm_extractor.generate_text",
        return_value="[]",
    ) as mock_generate:
        extraction_service._extract_document_servitutter(
            "doc-a",
            [chunk],
            "case-test",
            "Prompt {chunks_text}",
            "tinglysningsattest",
        )

    assert mock_generate.call_args.kwargs["max_tokens"] == 8192


def test_extract_document_servitutter_can_use_separate_extraction_provider_and_model(monkeypatch):
    chunk = make_chunk("doc-a")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "MODEL", "deepseek-chat")
    monkeypatch.setattr(settings, "EXTRACTION_LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "EXTRACTION_MODEL", "claude-sonnet-4-6")

    with patch(
        "app.services.extraction.llm_extractor.generate_text",
        return_value="[]",
    ) as mock_generate:
        extraction_service._extract_document_servitutter(
            "doc-a",
            [chunk],
            "case-test",
            "Prompt {chunks_text}",
            "akt",
        )

    assert mock_generate.call_args.kwargs["provider"] == "anthropic"
    assert mock_generate.call_args.kwargs["default_model"] == "claude-sonnet-4-6"


def test_extract_document_servitutter_parses_structured_scope_fields():
    chunk = make_chunk("doc-a")

    with patch(
        "app.services.extraction.llm_extractor.generate_text",
        return_value=(
            '[{'
            '"title":"Test",'
            '"date_reference":"01.01.2000-1-1",'
            '"registered_at":"2000-01-01",'
            '"applies_to_parcel_numbers":["0001o"],'
            '"raw_parcel_references":["1o","1v"],'
            '"raw_scope_text":"Vedr. matr.nr. 1o og 1v",'
            '"scope_source":"akt",'
            '"scope_basis":"Eksplicit nævnt i akten",'
            '"scope_confidence":0.9,'
            '"confidence":0.8'
            '}]'
        ),
    ):
        result = extraction_service._extract_document_servitutter(
            "doc-a",
            [chunk],
            "case-test",
            "Prompt {chunks_text}",
            "akt",
        )

    assert len(result) == 1
    assert result[0].registered_at == date(2000, 1, 1)
    assert result[0].raw_parcel_references == ["1o", "1v"]
    assert result[0].raw_scope_text == "Vedr. matr.nr. 1o og 1v"
    assert result[0].scope_source == "akt"


def test_extract_canonical_from_attest_preloads_documents(monkeypatch):
    chunks = [
        make_chunk("doc-attest", page=1, text="attest side 1"),
        make_chunk("doc-attest", page=2, text="attest side 2"),
        make_chunk("doc-akt", page=1, text="akt side 1"),
    ]
    documents = [
        Document(
            document_id="doc-attest",
            case_id="case-test",
            filename="attest.pdf",
            file_path="storage/cases/case-test/documents/doc-attest/original.pdf",
            document_type="tinglysningsattest",
        ),
        Document(
            document_id="doc-akt",
            case_id="case-test",
            filename="akt.pdf",
            file_path="storage/cases/case-test/documents/doc-akt/original.pdf",
            document_type="akt",
        ),
    ]

    monkeypatch.setattr(
        "app.services.extraction_service.storage_service.load_all_chunks",
        lambda session, case_id: chunks,
    )
    monkeypatch.setattr(
        "app.services.extraction_service.storage_service.list_documents",
        lambda session, case_id: documents,
    )
    monkeypatch.setattr(
        "app.services.extraction_service.storage_service.load_document",
        lambda session, case_id, doc_id: (_ for _ in ()).throw(AssertionError("N+1 load_document call")),
    )

    with patch(
        "app.services.extraction_service.extract_canonical_from_attest_segments",
        return_value=[make_canonical("01.01.2000-1-1")],
    ) as mock_extract:
        result = extraction_service.extract_canonical_from_attest(None, "case-test")

    assert len(result) == 1
    attest_by_doc = mock_extract.call_args.args[1]
    assert list(attest_by_doc) == ["doc-attest"]
    assert len(attest_by_doc["doc-attest"]) == 2


def test_build_attest_segments_splits_large_attest_with_overlap():
    chunks = [
        make_chunk(
            "doc-attest",
            page=page,
            text=f"Tinglysningsattest side {page}\nServitut tekst for side {page}",
        )
        for page in range(1, 7)
    ]

    segments = attest_pipeline.build_attest_segments(
        "case-test",
        "doc-attest",
        chunks,
        max_segment_pages=2,
        overlap_pages=1,
        max_segment_chars=10_000,
    )

    assert [(segment.page_start, segment.page_end) for segment in segments] == [
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 6),
    ]
    covered_pages = {page for segment in segments for page in segment.page_numbers}
    assert covered_pages == {1, 2, 3, 4, 5, 6}


def test_merge_attest_servitutter_deduplicates_overlapping_segments():
    left = Servitut(
        easement_id="srv-left",
        case_id="case-test",
        source_document="doc-attest",
        date_reference="01.01.2000-1-1",
        title="Vejret",
        raw_parcel_references=["1a"],
        applies_to_parcel_numbers=["1a"],
        confidence=0.6,
        evidence=[Evidence(chunk_id="c1", document_id="doc-attest", page=1, text_excerpt="side 1")],
    )
    right = Servitut(
        easement_id="srv-right",
        case_id="case-test",
        source_document="doc-attest",
        date_reference="01.01.2000-1-1",
        archive_number="40 B 405",
        title="Vejret og adgang",
        raw_parcel_references=["1b"],
        applies_to_parcel_numbers=["1b"],
        raw_scope_text="Vedr. matr.nr. 1a og 1b",
        confidence=0.9,
        evidence=[Evidence(chunk_id="c2", document_id="doc-attest", page=2, text_excerpt="side 2")],
    )

    merged = attest_pipeline.merge_attest_servitutter([left, right])

    assert len(merged) == 1
    assert merged[0].archive_number == "40 B 405"
    assert merged[0].title == "Vejret og adgang"
    assert merged[0].applies_to_parcel_numbers == ["1a", "1b"]
    assert merged[0].raw_parcel_references == ["1a", "1b"]
    assert len(merged[0].evidence) == 2


def test_extract_canonical_from_attest_segments_reuses_completed_cache(monkeypatch):
    """Pipeline v2: declaration_blocks i state bruges som cache — assembler kaldes ikke igen."""
    chunk = make_chunk("doc-attest", page=1, text="09.02.1957-490-40 vejret")
    block = DeclarationBlock(
        block_id="aabbccddeeff",
        case_id="case-test",
        document_id="doc-attest",
        page_start=1,
        page_end=1,
        source_segment_ids=["doc-attest-segment-0000"],
        status="aktiv",
        fanout_date_refs=["09.02.1957-490-40"],
    )
    state = AttestPipelineState(
        case_id="case-test",
        document_id="doc-attest",
        source_signature=attest_pipeline._source_signature([chunk]),
        segments=[
            AttestSegment(
                segment_id="doc-attest-segment-0000",
                case_id="case-test",
                document_id="doc-attest",
                segment_index=0,
                page_start=1,
                page_end=1,
                page_numbers=[1],
                text="[Side 1]\n09.02.1957-490-40 vejret",
                text_hash="hash",
                block_type=AttestBlockType.DECLARATION_CONTINUATION,
            )
        ],
        declaration_blocks=[block],
    )
    events = []

    monkeypatch.setattr(
        attest_pipeline.storage_service,
        "load_attest_pipeline_state",
        lambda session, case_id, doc_id: state,
    )
    monkeypatch.setattr(
        attest_pipeline.storage_service,
        "save_attest_pipeline_state",
        lambda session, case_id, doc_id, current_state: None,
    )
    # Deterministic pipeline — LLM must not be called
    monkeypatch.setattr(
        attest_pipeline,
        "generate_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    result = attest_pipeline.extract_canonical_from_attest_segments(
        None,
        {"doc-attest": [chunk]},
        "case-test",
        progress_callback=events.append,
    )

    assert len(result) == 1
    # date_reference er normaliseret af fanout.py: DD.MM.YYYY-NNN → YYYYMMDD-NNN
    assert result[0].date_reference == "19570209-490-40"
    stages = [event["stage"] for event in events]
    assert stages == [
        "indexed_attest",
        "classifying_blocks",
        "assembling_blocks",
        "fanout_entries",
        "merging_attest_segments",
        "completed",
    ]


def test_extract_canonical_from_attest_segments_persists_segment_results(monkeypatch):
    """Pipeline v2: declaration_blocks persisteres i state efter assembly."""
    chunks = [
        make_chunk("doc-attest", page=1, text="09.02.1957-490-40 vejret"),
        make_chunk("doc-attest", page=2, text="10.02.1957-491-40 ledning"),
    ]
    built_segments = [
        AttestSegment(
            segment_id="doc-attest-segment-0000",
            case_id="case-test",
            document_id="doc-attest",
            segment_index=0,
            page_start=1,
            page_end=1,
            page_numbers=[1],
            text="[Side 1]\n09.02.1957-490-40 vejret",
            text_hash="hash-1",
        ),
        AttestSegment(
            segment_id="doc-attest-segment-0001",
            case_id="case-test",
            document_id="doc-attest",
            segment_index=1,
            page_start=2,
            page_end=2,
            page_numbers=[2],
            text="[Side 2]\n10.02.1957-491-40 ledning",
            text_hash="hash-2",
        ),
    ]
    saved_states = []
    state_store = {"value": None}

    monkeypatch.setattr(
        attest_pipeline.storage_service,
        "load_attest_pipeline_state",
        lambda session, case_id, doc_id: state_store["value"],
    )

    def _save_state(session, case_id, doc_id, state):
        state_store["value"] = state
        saved_states.append(state.model_copy(deep=True))

    monkeypatch.setattr(attest_pipeline.storage_service, "save_attest_pipeline_state", _save_state)
    monkeypatch.setattr(attest_pipeline, "build_attest_segments", lambda *args, **kwargs: built_segments)

    result = attest_pipeline.extract_canonical_from_attest_segments(
        None,
        {"doc-attest": chunks},
        "case-test",
    )

    # Begge date_references er normaliseret
    result_refs = sorted(s.date_reference for s in result)
    assert result_refs == ["19570209-490-40", "19570210-491-40"]

    # declaration_blocks er persisteret i state
    assert state_store["value"].declaration_blocks
    # State er gemt mindst én gang (segmentbygge + block-assembly)
    assert len(saved_states) >= 2


def test_extract_canonical_from_attest_segments_tracks_unresolved_blocks(monkeypatch):
    """Pipeline v2: blokke uden gyldige date_references registreres som uafklarede.

    Den nye pipeline kaster IKKE AttestPipelineIncompleteError — unresolved blocks
    registreres i state.unresolved_block_ids og pipelinen fortsætter.
    """
    chunks = [
        make_chunk("doc-attest", page=1, text="09.02.1957-490-40 vejret"),
        make_chunk("doc-attest", page=2, text="ingen dato her"),
    ]
    built_segments = [
        AttestSegment(
            segment_id="doc-attest-segment-0000",
            case_id="case-test",
            document_id="doc-attest",
            segment_index=0,
            page_start=1,
            page_end=1,
            page_numbers=[1],
            text="[Side 1]\n09.02.1957-490-40 vejret",
            text_hash="hash-1",
        ),
        AttestSegment(
            segment_id="doc-attest-segment-0001",
            case_id="case-test",
            document_id="doc-attest",
            segment_index=1,
            page_start=2,
            page_end=2,
            page_numbers=[2],
            # DECLARATION_START-segment uden date_reference → egen blok, uafklaret
            text="Prioritet 2\nGenerel bestemmelse uden tinglysningsdato",
            text_hash="hash-2",
        ),
    ]
    state_store = {"value": None}
    events = []

    monkeypatch.setattr(
        attest_pipeline.storage_service,
        "load_attest_pipeline_state",
        lambda session, case_id, doc_id: state_store["value"],
    )
    monkeypatch.setattr(
        attest_pipeline.storage_service,
        "save_attest_pipeline_state",
        lambda session, case_id, doc_id, state: state_store.__setitem__("value", state.model_copy(deep=True)),
    )
    monkeypatch.setattr(attest_pipeline, "build_attest_segments", lambda *args, **kwargs: built_segments)

    # Ingen exception — pipelinen fortsætter og returnerer hvad den kan
    result = attest_pipeline.extract_canonical_from_attest_segments(
        None,
        {"doc-attest": chunks},
        "case-test",
        progress_callback=events.append,
    )

    # Kun segment 0 har en gyldig date_reference → 1 servitut
    assert len(result) == 1
    assert result[0].date_reference == "19570209-490-40"

    # Uafklarede blokke er registreret i state
    final_state = state_store["value"]
    assert final_state is not None
    assert len(final_state.unresolved_block_ids) >= 1


def test_extract_servitutter_does_not_save_partial_canonical_cache(monkeypatch):
    attest_chunk = make_chunk("doc-attest", page=1, text="attest side 1")
    akt_chunk = make_chunk("doc-akt", page=1, text="akt side 1")

    monkeypatch.setattr(
        "app.services.extraction_service.storage_service.list_documents",
        lambda session, case_id: [
            Document(
                document_id="doc-attest",
                case_id=case_id,
                filename="attest.pdf",
                file_path="storage/cases/case-test/documents/doc-attest/original.pdf",
                document_type="tinglysningsattest",
            ),
            Document(
                document_id="doc-akt",
                case_id=case_id,
                filename="akt.pdf",
                file_path="storage/cases/case-test/documents/doc-akt/original.pdf",
                document_type="akt",
            ),
        ],
    )

    with patch(
        "app.services.extraction_service.extract_canonical_from_attest_segments",
        side_effect=attest_pipeline.AttestPipelineIncompleteError(
            "case-test",
            [{"document_id": "doc-attest", "failed_segments": 1, "total_segments": 2}],
        ),
    ), patch(
        "app.services.extraction_service.storage_service.save_canonical_list",
        side_effect=AssertionError("partial canonical result must not be cached"),
    ):
        try:
            extraction_service.extract_servitutter(
                None,
                [attest_chunk, akt_chunk],
                "case-test",
            )
            assert False, "Expected extraction to fail on partial canonical extraction"
        except attest_pipeline.AttestPipelineIncompleteError:
            pass


def test_extract_servitutter_uses_segmented_attest_pipeline(monkeypatch):
    attest_chunk = make_chunk("doc-attest", page=1, text="attest side 1")
    akt_chunk = make_chunk("doc-akt", page=1, text="akt side 1")
    canonical = [make_canonical("01.01.2000-1-1", title="Vejret")]

    monkeypatch.setattr(
        "app.services.extraction_service.storage_service.list_documents",
        lambda session, case_id: [
            Document(
                document_id="doc-attest",
                case_id=case_id,
                filename="attest.pdf",
                file_path="storage/cases/case-test/documents/doc-attest/original.pdf",
                document_type="tinglysningsattest",
            ),
            Document(
                document_id="doc-akt",
                case_id=case_id,
                filename="akt.pdf",
                file_path="storage/cases/case-test/documents/doc-akt/original.pdf",
                document_type="akt",
            ),
        ],
    )
    monkeypatch.setattr(
        extraction_service.matrikel_service,
        "sync_case_matrikler",
        lambda session, case_id, doc_ids: None,
    )
    monkeypatch.setattr(
        extraction_service,
        "enrich_canonical_list",
        lambda canonical_list, akt_by_doc, case_id, **kwargs: canonical_list,
    )

    with patch(
        "app.services.extraction_service.extract_canonical_from_attest_segments",
        return_value=canonical,
    ) as mock_extract:
        result = extraction_service.extract_servitutter(
            None,
            [attest_chunk, akt_chunk],
            "case-test",
        )

    assert [servitut.date_reference for servitut in result] == ["01.01.2000-1-1"]
    attest_by_doc = mock_extract.call_args.args[1]
    assert list(attest_by_doc) == ["doc-attest"]


def make_canonical(date_reference: str, archive_number: str = None, title: str = "Test") -> Servitut:
    return Servitut(
        easement_id="srv-canonical",
        case_id="case-test",
        source_document="doc-attest",
        date_reference=date_reference,
        archive_number=archive_number,
        title=title,
    )


def test_select_candidate_chunks_scores_akt_nr():
    """Chunk med archive_number-match inkluderes."""
    canonical = make_canonical("01.01.2000-1-1", archive_number="40 F 439")
    chunk_hit = make_chunk("doc-a", page=1, text="Se akt 40F439 vedr. byggelinje")
    chunk_miss = make_chunk("doc-a", page=2, text="Ingen relevante oplysninger her overhovedet")

    result = select_candidate_chunks([chunk_hit, chunk_miss], [canonical])

    assert chunk_hit in result
    # chunk_miss kan inkluderes som kontekstvindue (nabo), men chunk_hit skal altid med
    chunk_ids = [c.chunk_id for c in result]
    assert chunk_hit.chunk_id in chunk_ids


def test_select_candidate_chunks_no_signal():
    """Ingen match → tom liste returneres."""
    canonical = make_canonical("11.03.1974-1904-40", archive_number="40 F 439")
    chunks = [
        make_chunk("doc-a", page=i, text="Helt irrelevant tekst om noget andet")
        for i in range(1, 4)
    ]

    result = select_candidate_chunks(chunks, [canonical])

    assert result == []


def test_select_candidate_chunks_context_window():
    """Naboer til en hit-chunk inkluderes i kontekstvinduet."""
    canonical = make_canonical("01.01.2000-1-1", archive_number="40 F 439")
    chunks = [
        make_chunk("doc-a", page=1, text="Intet interessant her"),         # index 0 — nabo
        make_chunk("doc-a", page=2, text="Akt 40F439 omhandler vejret"),   # index 1 — hit
        make_chunk("doc-a", page=3, text="Fortsat tekst om sagen"),        # index 2 — nabo
        make_chunk("doc-a", page=4, text="Fuldstændigt irrelevant xyz"),   # index 3 — ude af vindue
    ]

    result = select_candidate_chunks(chunks, [canonical], context_window=1)

    result_ids = [c.chunk_id for c in result]
    assert chunks[0].chunk_id in result_ids  # nabo før
    assert chunks[1].chunk_id in result_ids  # hit
    assert chunks[2].chunk_id in result_ids  # nabo efter


def test_select_candidate_chunks_char_cap():
    """Tegnloftet på 16000 tegn respekteres."""
    canonical = make_canonical("01.01.2000-1-1", archive_number="40 F 439")
    # Lav én hit-chunk efterfulgt af mange store chunks der tilsammen overstiger loftet
    big_text = "A" * 5000
    hit_chunk = make_chunk("doc-a", page=1, text="40F439 kort hit")
    big_chunks = [make_chunk("doc-a", page=i, text=big_text) for i in range(2, 8)]

    # Sæt hit_chunk som nabo til de store chunks (context_window=1 → page2 inkluderes)
    all_chunks = [hit_chunk] + big_chunks

    result = select_candidate_chunks(all_chunks, [canonical], context_window=1)

    total_chars = sum(len(c.text) for c in result)
    assert total_chars <= 16_000


def test_enrich_canonical_preserves_attest_scope_over_akt_scope():
    canonical = Servitut(
        easement_id="srv-canonical",
        case_id="case-test",
        source_document="doc-attest",
        date_reference="01.01.2000-1-1",
        applies_to_parcel_numbers=["0001o", "0001v"],
        raw_parcel_references=["1o", "1v"],
        raw_scope_text="Vedr. matr.nr. 1o og 1v",
        scope_source="attest",
        registered_at=date(2000, 1, 1),
        confidence=0.6,
    )
    akt = Servitut(
        easement_id="srv-akt",
        case_id="case-test",
        source_document="doc-akt",
        date_reference="01.01.2000-1-1",
        applies_to_parcel_numbers=["0022a"],
        raw_parcel_references=["22a"],
        raw_scope_text="Vedr. matr.nr. 22a",
        scope_source="akt",
        summary="Detaljer fra akt",
        confidence=0.9,
    )

    merged = _enrich_canonical(canonical, akt)

    assert merged.summary == "Detaljer fra akt"
    assert merged.applies_to_parcel_numbers == ["0001o", "0001v"]
    assert merged.raw_parcel_references == ["1o", "1v"]
    assert merged.raw_scope_text == "Vedr. matr.nr. 1o og 1v"
    assert merged.scope_source == "attest"


def test_describe_chunk_scoring_inputs_exposes_attest_fields_and_signals():
    canonical = Servitut(
        easement_id="srv-canonical",
        case_id="case-test",
        source_document="doc-attest",
        date_reference="11.03.1974-1904-40",
        archive_number="40 F 439",
        title="Afløbsledning ved byggelinje",
        applies_to_parcel_numbers=["38b"],
        raw_parcel_references=["38b", "1a"],
        raw_scope_text="Vedr. matr.nr. 38b",
    )

    described = extraction_service.describe_chunk_scoring_inputs([canonical])

    row = described["canonical_rows"][0]
    assert row["raw_scope_text"] == "Vedr. matr.nr. 38b"
    assert row["applies_to_parcel_numbers"] == ["38b"]
    signal_types = {signal["signal_type"] for signal in row["derived_signals"]}
    assert {"archive_number", "date_ref", "lob_suffix", "matrikel", "title_word"} <= signal_types


def test_score_akt_chunks_for_case_includes_scoreless_context_chunks(monkeypatch):
    canonical = make_canonical("01.01.2000-1-1", archive_number="40 F 439", title="Byggelinje")
    document = Document(
        document_id="doc-a",
        case_id="case-test",
        filename="akt.pdf",
        file_path="storage/cases/case-test/documents/doc-a/original.pdf",
        document_type="akt",
    )
    chunks = [
        make_chunk("doc-a", page=1, text="Forord uden signal"),
        make_chunk("doc-a", page=2, text="Her står akt 40F439 tydeligt"),
        make_chunk("doc-a", page=3, text="Efterfølgende kontekst uden egne signaler"),
        make_chunk("doc-a", page=4, text="Helt irrelevant afslutning"),
    ]

    monkeypatch.setattr(
        extraction_service.storage_service,
        "list_documents",
        lambda session, case_id: [document],
    )
    monkeypatch.setattr(
        extraction_service.storage_service,
        "load_chunks",
        lambda session, case_id, doc_id: chunks,
    )

    results = extraction_service.score_akt_chunks_for_case(None, "case-test", [canonical])

    assert len(results) == 1
    result = results[0]
    assert result["candidate_count"] == 3
    assert result["selection_summary"]["selected_hit_chunks"] == 1
    assert result["selection_summary"]["selected_context_chunks"] == 2

    states_by_page = {detail["page"]: detail["selection_state"] for detail in result["chunk_details"]}
    assert states_by_page[1] == "selected_context"
    assert states_by_page[2] == "selected_hit"
    assert states_by_page[3] == "selected_context"


# ---------------------------------------------------------------------------
# Parallel enrichment (enrich_canonical_list Fase 2)
# ---------------------------------------------------------------------------

def test_enrich_canonical_list_uses_parallel_executor(monkeypatch):
    """Fase 2 bruger ThreadPoolExecutor når EXTRACTION_MAX_CONCURRENCY > 1."""
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 4)

    canonical = [make_canonical("01.01.2000-1-1", archive_number="40 F 439")]
    chunk_a = make_chunk("doc-a", page=1, text="Akt 40F439 vedr. vejret")
    chunk_b = make_chunk("doc-b", page=1, text="Akt 40F439 vedr. ledning")

    captured = {}

    class SpyEnrichExecutor:
        def __init__(self, max_workers, thread_name_prefix=None):
            captured["max_workers"] = max_workers
            captured["prefix"] = thread_name_prefix
            self.max_workers = max_workers

        def __enter__(self): return self
        def __exit__(self, *a): return False

        def submit(self, fn, *args, **kwargs):
            class F:
                def result(self_): return []
            return F()

    monkeypatch.setattr(enricher_module, "ThreadPoolExecutor", SpyEnrichExecutor)
    monkeypatch.setattr(enricher_module, "wait", lambda pending, timeout, return_when: (set(pending), set()))

    enrich_canonical_list(
        canonical,
        {"doc-a": [chunk_a], "doc-b": [chunk_b]},
        case_id="case-test",
    )

    assert "max_workers" in captured
    assert captured["prefix"] == "enrich-doc"
    assert captured["max_workers"] <= 4


def test_enrich_canonical_list_preserves_correct_doc_chunk_binding(monkeypatch):
    """
    Evidens-chunks skal komme fra det dokument LLM-resultatet faktisk stammer fra,
    ikke fra et vilkårligt andet dokument (regression for chunk_list scope-fejl).
    """
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 4)

    canonical_a = make_canonical("01.01.2000-1001", archive_number="40 A 1", title="Vejret")
    canonical_b = make_canonical("01.02.2000-2002", archive_number="40 B 2", title="Ledning")

    chunk_a = make_chunk("doc-a", page=1, text="Akt 40A1 vedr. vejret")
    chunk_b = make_chunk("doc-b", page=1, text="Akt 40B2 vedr. ledning")

    def fake_enrich(doc_id, chunk_list, canonical_list, *args, **kwargs):
        if doc_id == "doc-a":
            return [{"archive_number": "40 A 1", "date_reference": "01.01.2000-1001", "confidence": 0.9}]
        if doc_id == "doc-b":
            return [{"archive_number": "40 B 2", "date_reference": "01.02.2000-2002", "confidence": 0.9}]
        return []

    monkeypatch.setattr(enricher_module, "_enrich_from_doc", fake_enrich)

    result = enrich_canonical_list(
        [canonical_a, canonical_b],
        {"doc-a": [chunk_a], "doc-b": [chunk_b]},
        case_id="case-test",
    )

    result_by_date = {s.date_reference: s for s in result}
    assert result_by_date["01.01.2000-1001"].source_document == "doc-a"
    assert result_by_date["01.02.2000-2002"].source_document == "doc-b"
    # Evidens skal pege på det rigtige dokument
    for srv in result:
        for ev in srv.evidence:
            assert ev.document_id == srv.source_document, (
                f"Evidens-chunk {ev.chunk_id} tilhører {ev.document_id!r} "
                f"men servitutten angiver {srv.source_document!r}"
            )


def test_enrich_canonical_list_sequential_when_concurrency_one(monkeypatch):
    """EXTRACTION_MAX_CONCURRENCY=1 → ingen ThreadPoolExecutor bruges."""
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 1)

    canonical = [make_canonical("01.01.2000-1-1", archive_number="40 F 439")]
    chunk_a = make_chunk("doc-a", page=1, text="Akt 40F439 vejret")
    llm_calls = []

    def fake_enrich(doc_id, *args, **kwargs):
        llm_calls.append(doc_id)
        return []

    monkeypatch.setattr(enricher_module, "_enrich_from_doc", fake_enrich)

    with patch.object(enricher_module, "ThreadPoolExecutor", side_effect=AssertionError("must not use executor")):
        enrich_canonical_list(canonical, {"doc-a": [chunk_a]}, case_id="case-test")

    assert llm_calls == ["doc-a"]


def test_enrich_canonical_list_writes_observability_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EXTRACTION_MAX_CONCURRENCY", 1)

    canonical = [make_canonical("01.01.2000-1-1", archive_number="40 F 439", title="Vejret")]
    chunk = make_chunk("doc-a", page=1, text="Akt 40F439 vejret")
    captured = {}

    def fake_enrich(doc_id, *args, **kwargs):
        return [{"archive_number": "40 F 439", "date_reference": "01.01.2000-1-1", "confidence": 0.9}]

    def fake_write(case_id, payload, run_id=None):
        captured["case_id"] = case_id
        captured["payload"] = payload
        captured["run_id"] = run_id
        return tmp_path / "extraction-summary.json"

    monkeypatch.setattr(enricher_module, "_enrich_from_doc", fake_enrich)
    monkeypatch.setattr(enricher_module.pipeline_observability, "write_extraction_run_summary", fake_write)

    result = enrich_canonical_list(canonical, {"doc-a": [chunk]}, case_id="case-test")

    assert len(result) == 1
    assert captured["case_id"] == "case-test"
    assert captured["payload"]["candidate_documents"] == 1
    assert captured["payload"]["candidate_chunks_total"] >= 1
    assert captured["payload"]["documents"][0]["doc_id"] == "doc-a"
    assert captured["payload"]["documents"][0]["llm_items"] == 1


# ---------------------------------------------------------------------------
# DSS administrative page filter
# ---------------------------------------------------------------------------

def test_chunk_pages_skips_dss_header_pages():
    """Sider med DSS-metadata-header skal ikke chunkes."""
    dss_page = PageData(
        page_number=1,
        text="DSS 88303021 76_AR-A 31 Bulk Sort / Hvid 271876 I I",
        confidence=0.9,
    )
    content_page = PageData(
        page_number=2,
        text="Deklaration om vejret til naboejendommen matr. nr. 5a tinglyst 15.06.2000.",
        confidence=0.9,
    )

    chunks = chunk_pages([dss_page, content_page], doc_id="doc-test", case_id="case-test")

    chunk_pages_used = {c.page for c in chunks}
    assert 1 not in chunk_pages_used, "DSS-header-side må ikke chunkes"
    assert 2 in chunk_pages_used, "Indholdsside skal chunkes"


def test_chunk_pages_skips_dss_header_case_insensitive():
    """DSS-filteret er case-insensitivt."""
    dss_page = PageData(
        page_number=1,
        text="dss 12345678 76_B-A 204 bulk hvid 99999",
        confidence=0.9,
    )
    chunks = chunk_pages([dss_page], doc_id="doc-test", case_id="case-test")
    assert chunks == []


def test_chunk_pages_keeps_non_dss_short_pages():
    """Korte ikke-DSS-sider filtreres ikke af det administrative filter."""
    short_page = PageData(
        page_number=1,
        text="Vejret til matr.nr. 5a.",
        confidence=0.9,
    )
    chunks = chunk_pages([short_page], doc_id="doc-test", case_id="case-test")
    assert len(chunks) >= 1
