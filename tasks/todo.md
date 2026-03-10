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
