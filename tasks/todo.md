# Authorization hardening for case-scoped routes

- [x] Add a shared `verify_case_ownership` helper in `app/services/case_service.py` that returns the case or raises `HTTPException(403, "Forbidden")`.
- [x] Update all endpoints in `app/api/routes/documents.py` to require `current_user` and verify case ownership before route logic.
- [x] Update all endpoints in `app/api/routes/ocr.py` to require `current_user` and verify case ownership before route logic.
- [x] Update all endpoints in `app/api/routes/extraction.py` to require `current_user` and verify case ownership before route logic.
- [x] Update all endpoints in `app/api/routes/reports.py` to require `current_user` and verify case ownership before route logic.
- [x] Verify the protected flows with targeted tests or inspection and document the result.

## Review

Findings:
- Added a single ownership gate in `case_service` so all case-scoped routes now fail closed with `403 Forbidden` when the case is missing or owned by another user.
- All endpoints in `documents.py`, `ocr.py`, `extraction.py`, and `reports.py` call the ownership check before document, OCR, extraction, or report logic runs.
- Added service-level tests for owned, foreign, and missing cases plus API coverage for all 11 protected endpoints across the four route modules.

Verification:
- `uv run pytest ...` could not be used directly in this environment because `uv` resolved to a Python 3.10 context without installed dependencies.
- Verified with `.venv/bin/python -m pytest tests/test_case_service.py tests/test_auth_api.py tests/test_documents_api.py -q`
- Result: `33 passed, 1 warning`

# Model key naming investigation

- [x] Inventory Pydantic and SQLModel field names across case, document, servitut, report, user, and TMV job models.
- [x] Trace which field names are exposed through FastAPI routes, Streamlit, and tests.
- [x] Identify non-English, ambiguous, or inconsistent keys and group them by severity.
- [x] Propose a simple English naming convention and a concrete rename map.
- [x] Add a short review section with findings and recommended next steps.

## Review

Findings:
- The API currently exposes internal model keys directly via FastAPI response models, so model field names are already public contract.
- Danish/domain-heavy keys are concentrated in `Matrikel`, `Servitut`, `Report`, and the matching SQL tables, not just in prompts or UI labels.
- The same key names are reused in DB rows, JSONB payloads, LLM prompts, Streamlit pages, and tests, which means renames must be handled as a cross-layer migration.
- The highest-friction keys are mixed-language or abbreviated fields such as `matrikler`, `target_matrikel`, `akt_nr`, `byggeri_markering`, `servitutter`, and `nr`.
- There is no alias layer today; `model_dump()` and `response_model=...` use raw field names, so changing names will immediately change API output and serialized JSON.

Recommended naming direction:
- Use English nouns for all external keys.
- Reserve Danish for free-text values and UI copy, not schema keys.
- Prefer `id`, `Ids`, `At`, `Count`, `Status`, `Source`, `Notes`, `Summary`, `AppliesTo`, `Raw*`, `Is*`, `Has*`, `Primary*`.
- Avoid abbreviations unless they are standard across the product; `akt_nr` and `nr` should be expanded.

Suggested rename map:
- `Matrikel.matrikelnummer` -> `parcel_number`
- `Matrikel.landsejerlav` -> `cadastral_district`
- `Matrikel.areal_m2` -> `area_sqm`
- `Case.matrikler` -> `parcels`
- `Case.target_matrikel` -> `primary_parcel_number`
- `Case.last_extracted_target_matrikel` -> `last_extracted_primary_parcel_number`
- `Servitut.servitut_id` -> `easement_id`
- `Servitut.akt_nr` -> `archive_number`
- `Servitut.byggeri_markering` -> `construction_impact`
- `Servitut.applies_to_matrikler` -> `applies_to_parcel_numbers`
- `Servitut.raw_matrikel_references` -> `raw_parcel_references`
- `Servitut.applies_to_target_matrikel` -> `applies_to_primary_parcel`
- `Servitut.attest_confirmed` -> `confirmed_by_attest`
- `ReportEntry.nr` -> `sequence_number`
- `ReportEntry.byggeri_markering` -> `construction_impact`
- `Report.servitutter` -> `entries`
- `Report.target_matrikler` -> `target_parcel_numbers`
- `Report.available_matrikler` -> `available_parcel_numbers`

Migration note:
- Safest path is two-phase: introduce aliases/compat serialization first, then rename DB columns and JSONB payload keys, then update prompts/tests/UI, and only then remove legacy names.

## Implementation Review

Outcome:
- Applied the agreed English key renames end-to-end across SQLModel models, SQL tables, storage mappings, extraction/report services, prompts, Streamlit pages, scripts, and tests.
- Report schema is now internally consistent with `entries` and `sequence_number` instead of the previous mixed-language `servitutter` and `nr`.
- Danish UI/prose was restored where the mechanical rename had leaked English wording into labels and help text.
- Document classifier heuristics were corrected so attest detection still keys off OCR text like `Landsejerlav:` and `Matrikelnummer:`.

Verification:
- Verified environment dependencies with `./.venv/bin/python` imports for `sqlmodel` and `fitz`.
- Verified targeted schema-sensitive suites with `./.venv/bin/python -m pytest -q tests/test_report_generation.py tests/test_report_editor_service.py tests/test_matrikel_service.py tests/test_extraction_schema.py tests/test_document_classifier.py`
- Verified full repo with `./.venv/bin/python -m pytest -q`
- Result: `142 passed, 6 warnings`
