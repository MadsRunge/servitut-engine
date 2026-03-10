# PDF cleanup plan

- [x] Review tracked PDF files and classify which should remain in Git
- [x] Update `.gitignore` so only servitutredegørelser and tinglysningsattester can be tracked as PDFs
- [x] Remove other tracked PDFs from the Git index without deleting local files
- [x] Verify the staged diff and document the result

## Review

- `.gitignore` now ignores all `*.pdf` files except filenames containing `Servitutredegørelse` or `Tinglysningsattest`
- 30 tracked PDF files were removed from the Git index with `git rm --cached`, leaving the local files in place
- Remaining step outside this workspace change is to commit and push the staged deletions so the files disappear from the remote repository

## Project overview plan

- [x] Inspect repository structure and entrypoints
- [x] Map the core pipeline across API, services, models, and Streamlit pages
- [x] Review tests and configuration to understand runtime assumptions
- [x] Summarize architecture, current workflow, and notable technical risks

## Project overview review

- Confirmed actual runtime architecture is FastAPI plus Streamlit over file-based JSON storage under `storage/cases`
- Confirmed the implemented pipeline is OCR-first, not generic PDF parsing first
- Confirmed extraction is two-pass: tinglysningsattest builds the canonical list, akt documents enrich it
- Confirmed test coverage exists for storage, chunking, OCR, extraction concurrency, matrikel parsing, LLM provider routing, and report fallback logic
- Noted that README and older descriptions still reference an earlier parse-centric pipeline and are partly out of sync with the current OCR-first implementation

## Bugfix plan

- [x] Ensure API document uploads classify documents with a valid `document_type`
- [x] Fix review scope filtering to pass target matrikler in the expected list format
- [x] Add regression tests for both fixes
- [x] Run focused verification for the changed areas

## Bugfix review

- API uploads now accept an optional `document_type` form field and otherwise infer `tinglysningsattest` from the filename, defaulting to `akt`
- Review page now passes the selected target matrikel as a list, matching the service contract
- Matrikel filtering was hardened to normalize either a single string or a list of strings
- Verified with `uv run pytest tests/test_documents_api.py tests/test_matrikel_service.py -q` (`8 passed`)

## Improvement plan

- [x] Add automatic document classification based on upload metadata and OCR/page text
- [x] Refactor report generation so the LLM returns JSON only and markdown is built deterministically in Python
- [x] Add regression tests for classification and report generation behavior
- [x] Run focused verification for the changed flows

## Improvement review

- Added a shared document classification service that uses explicit type overrides first, OCR/page text second, filename heuristics third, and defaults to `akt`
- API uploads now use the shared classifier, and OCR completion reclassifies legacy `unknown` documents from extracted text
- Report prompting now asks for JSON only; markdown tables are generated deterministically in Python from parsed `ReportEntry` objects
- Report parsing is robust to plain JSON and fenced JSON responses, while fallback report generation still works
- Verified with `uv run pytest tests/test_document_classifier.py tests/test_documents_api.py tests/test_report_generation.py tests/test_matrikel_service.py -q` (`21 passed`)

## Middelfart end-to-end plan

- [x] Identify the Middelfart case and define the exact reset scope for generated artifacts
- [x] Reset OCR, chunk, extraction, and report artifacts for the Middelfart case while keeping source PDFs and metadata
- [x] Re-run OCR, extraction, and report generation for the Middelfart case
- [x] Compare the generated extraction/report output against `docs/22267_Servitutredegørelse.pdf`
- [x] Document the evaluation outcome and any product gaps

## Middelfart end-to-end review

- Reset `storage/cases/case-683ad567` by removing generated OCR/chunk/servitut/report artifacts, keeping `original.pdf` files and document metadata identities intact
- Re-ran OCR successfully for all 10 Middelfart documents and repopulated case matrikler from the tinglysningsattest
- Re-ran extraction end-to-end against the configured LLM provider; extraction produced 11 servitutter and saved fresh servitut JSON files
- The report LLM step did not return parseable JSON, so `generate_report` fell back to deterministic Python report assembly; saved reports include `rep-524fff84` for target `0069f` and `rep-66e24d00` for evaluation target `0001o` + `0001v`
- Compared against `docs/22267_Servitutredegørelse.pdf` and found that the overall historical count is close, but the product currently misses servitut `02.07.1956-2192-40` and instead includes a newer `16.01.2024-1015412544` servitut that post-dates the 20.12.2022 reference redegørelse
- Found content/date drift in multiple extracted servitutter: `11.03.1974-1904-40` is described as an elkabel-deklaration instead of the afløbsledning in the reference, and `04.11.1966-5973-40` is described as a jordkabel/transformer-servitut instead of the landvæsenskommisionskendelse in the reference
- Found a scope-normalization gap in reporting: extracted matrikel numbers such as `38b`, `69f`, and `22a` are not normalized to the case format `0038b`, `0069f`, `0022a`, which causes several rows that should be `Nej` to be rendered as `Måske` in the report

## Scope normalization fix plan

- [x] Add canonical matrikel normalization so scope comparisons tolerate zero-padded and non-zero-padded representations
- [x] Add regression tests for mixed matrikel formats in scope resolution and report filtering
- [x] Run focused verification for matrikel and report services
- [x] Regenerate the Middelfart evaluation report for matr.nr. `0001o` and `0001v`

## Scope normalization fix review

- Added a shared matrikel normalization helper in `app/services/matrikel_service.py` that removes formatting-only differences such as zero-padding and whitespace before scope comparisons
- Updated target resolution, available matrikel comparison, and matching-target lookup to use the same normalized representation while preserving the original target format in report-facing output
- Hardened case target updates so `1o` correctly resolves to stored case matrikel `0001o`
- Verified with `.venv/bin/pytest tests/test_matrikel_service.py tests/test_report_generation.py -q` (`17 passed`)
- Regenerated the Middelfart evaluation report for `0001o` + `0001v` as `rep-b9a3578b`; several rows that were previously false `Måske` are now `Nej` (`1903`, `1932`, `03.06.1957`, `03.07.1974`, `04.09.2007`, `05.08.1975`)
- Remaining `Måske` rows now reflect extraction uncertainty rather than formatting mismatch, especially `04.11.1966-5973-40`, `12.07.1955-2403-40`, and `09.02.1957-490-40`

## Structured scope and as-of-date plan

- [x] Extend the servitut data model with structured scope evidence and a parsed registration date
- [x] Update extraction prompts and parsers so both attest and akt flows return raw scope evidence instead of only conclusions
- [x] Tighten merge rules so attest scope remains authoritative and akt only fills missing scope metadata
- [x] Add `as_of_date` filtering to report generation and expose it in API/UI entry points
- [x] Add regression tests for structured scope extraction, merge precedence, and as-of-date filtering
- [x] Re-run the Middelfart case with the updated pipeline and compare the new output against the reference redegørelse

## Structured scope and as-of-date review

- Added structured scope fields and parsed registration dates to `Servitut`, plus shared extraction normalization helpers for strings, matrikel lists, and date parsing
- Updated `extract_tinglysningsattest`, `extract_servitut`, and `enrich_servitut` prompts so the LLM now returns `registered_at`, `raw_matrikel_references`, `raw_scope_text`, and `scope_source`
- Updated both attestation and akt parsing so these new fields are populated deterministically in the stored servitut JSON
- Tightened merge logic so attestation scope remains authoritative when present; akt scope is now only used to fill missing scope metadata
- Added `as_of_date` to the `Report` model and `generate_report`, exposed it in the API route and Streamlit report page, and filtered out future servitutter before report generation
- Verified with `.venv/bin/pytest tests/test_extraction_schema.py tests/test_extraction_service.py tests/test_matrikel_service.py tests/test_report_generation.py tests/test_documents_api.py -q` (`36 passed`)
- Re-ran Middelfart extraction and a historical report for matr.nr. `0001o` + `0001v` as of `2022-12-20`; extraction produced 11 servitutter with populated `registered_at` and raw scope evidence, and the historical report `rep-076dc6b5` correctly excluded the 2024 servitut
- The updated pipeline now makes the remaining issues easier to diagnose: missing reference row `02.07.1956-2192-40` is still an extraction miss, while `11.03.1974-1904-40` still carries akt-derived scope for matr.nr. `22a`, which is an enrichment/matching problem rather than a reporting problem

## Middelfart re-evaluation plan

- [x] Re-run Middelfart extraction and historical report generation after the latest matching and prompt changes
- [x] Check whether `02.07.1956-2192-40` is now present in the canonical list
- [x] Check whether `11.03.1974-1904-40` still mismatches to the wrong akt/context
- [x] Compare the regenerated historical report with `docs/22267_Servitutredegørelse.pdf` and document the quality delta

## Middelfart re-evaluation review

- Re-ran Middelfart extraction and generated historical report `rep-8790ca60` for matr.nr. `0001o` + `0001v` as of `2022-12-20`
- The 2024 servitut is still extracted in the live dataset, but is correctly filtered out of the historical report via `as_of_date`
- `02.07.1956-2192-40` is still missing from the extracted canonical list, so the attestation completeness problem is not fully resolved by the prompt change alone
- `11.03.1974-1904-40` still mismatches to the wrong akt/context (`22a`/`67` kabeldeklaration), so fuzzy matching did not fix the core enrichment problem for that row
- The report is nevertheless closer to the reference on several rows: `04.11.1966-5973-40` is now interpreted as an afløbsledningsservitut affecting `1o` and `1v`, and `03.06.1957-2228-40` remains correctly outside the project scope
- Remaining high-impact gaps are now narrower and clearer:
  - attestation extraction still misses non-standard or weakly formatted rows such as `02.07.1956-2192-40`
  - akt enrichment can still overwrite the semantic understanding of the wrong canonical row when two neighboring 1974 entries are confused
  - report generation can still infer historically plausible mappings (`1a` → `1o/1v`) that are useful, but should be treated as assumptions rather than hard facts

## LLM split config plan

- [x] Add separate extraction/report provider and model settings with backward-compatible fallbacks
- [x] Update LLM and report services to route by explicit provider overrides instead of global provider only
- [x] Add regression tests that prove extraction and report can resolve different providers/models from `.env`
- [x] Verify the new config behavior with focused tests and a runtime config check

## LLM split config review

- Added `EXTRACTION_LLM_PROVIDER`, `EXTRACTION_MODEL`, and `REPORT_LLM_PROVIDER` to the settings model, while keeping `LLM_PROVIDER` and `MODEL` as global fallbacks for backward compatibility
- Updated `generate_text` so callers can override both `provider` and a route-specific default model without changing the existing global call pattern
- Updated extraction calls to honor `EXTRACTION_*` settings and report generation to honor `REPORT_*` settings, so extraction and report can now use different providers in the same run
- Updated `.env.example` to document the new split configuration and set the local `.env` explicitly to `anthropic`/`claude-sonnet-4-6` for extraction and `deepseek`/`deepseek-reasoner` for report generation
- Verified with `.venv/bin/pytest tests/test_llm_service.py tests/test_extraction_service.py tests/test_report_generation.py -q` (`31 passed`) and a runtime config check showing `EXTRACTION_PROVIDER=anthropic`, `EXTRACTION_MODEL=claude-sonnet-4-6`, `REPORT_PROVIDER=deepseek`, `REPORT_MODEL=deepseek-reasoner`
