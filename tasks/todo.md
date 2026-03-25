## Local test stack doc

## Clean attest extraction completion plan

- [x] Kortlaeg de konkrete huller i den nye attest-path: prompt, prioritet, evidence og legacy debug/state
- [x] Implementer prompt-wiring, bevar attesteret prioritet og fix evidence/provenance i den nye extractor
- [x] Fjern eller afkobl resterende legacy-attestkode fra aktiv extraction-path hvor det er nødvendigt
- [x] Koer maalrettede tests og backend-suiten, og noter review/resultat

## Clean attest extraction completion review

- Den nye attest-path bruger nu sin egen prompt via `_load_prompt("attest_candidate")` og falder ikke tilbage til `extract_servitut.txt`.
- Candidate-block extraction injicerer nu deterministiske defaults for `priority`, `date_reference` og `archive_number`, så LLM-output ikke taber attestens egne nøglefelter.
- Den aktive attest-path bruger nu `merge_candidate_servitutter()` i stedet for den gamle merge-logik, og `priority` renummereres ikke længere til intern rækkefølge.
- Evidence patcher nu faktisk tilbage på de genererede `Servitut`-objekter i den nye extractor.
- Pipeline-wrapperen gemmer nu en ærlig minimal state med `segment_strategy = attest_candidate_v1`, så den aktive extraction-path ikke efterlader gammel page-window-state som sandhed.
- Den overflødige `section_parser`-gren blev fjernet fra worktree for at undgå to konkurrerende sektion-logikker.

Verificering:
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_attest_extractor.py tests/test_extraction_service.py`
  - `58 passed`
- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
  - `289 passed, 6 warnings`

## Reset all cases extraction plan

- [x] Identificer alle cases i DB og deres nuværende extraction-state
- [x] Nulstil extraction-output for alle cases uden at slette OCR-data
- [x] Verificer status, servitutter og attest-state pr. case efter reset

## Reset all cases extraction review

- Nulstillede extraction-output for begge lokale cases via backendens `reset_case_extraction_outputs(..., clear_attest_pipeline=True)`.
- OCR-data blev bevaret i begge cases; kun canonical/extraction-state blev ryddet.
- Normaliserede bagefter JSON `null` til rigtig SQL `NULL` for `cases.canonical_list`, `cases.scoring_results` og `documents.attest_pipeline_state`, så state ikke stod halvryddet.

Efter reset:
- `case-4aa8d93e`
  - status: `ocr_done`
  - docs: `3/3 ocr_done`
  - chunks: `171`
  - servitutter: `0`
  - reports: `0`
  - declarations: `0`
  - attest pipeline state: `0` dokumenter
  - canonical_list: `NULL`
- `case-7f345dcc`
  - status: `ocr_done`
  - docs: `123/123 ocr_done`
  - chunks: `8287`
  - servitutter: `0`
  - reports: `0`
  - declarations: `0`
  - attest pipeline state: `0` dokumenter
  - canonical_list: `NULL`

- [x] Skriv en kort docs-fil med den lokale startup-rækkefølge for backend, Redis, worker og frontend

## Local test stack review

- Oprettede en kort lokal test-guide, så den fulde stack kan startes ens hver gang før frontend-test af OCR/extraction-flow.

## Aalborg frontend test readiness plan

- [x] Tilføj et eksplicit rerun-flow for extraction i frontend, så sagen kan køres igen selv når der allerede findes servitutter
- [x] Aftal og implementér den nødvendige backend-kontrakt til frontend-debugning af den nye attest-pipeline
- [x] Tilpas review-UI til de nye canonical felter fra attest-pipeline v2
- [x] Tilføj en lille QA-checkliste for Aalborg-casen, så vi kan verificere flowet end-to-end i frontend

## Aalborg frontend test readiness review

- Implementerede et eksplicit rerun-flow i frontend, som kalder `POST /cases/{case_id}/extract` med `force_rebuild=true` og `clear_attest_pipeline=true`, så sagen kan genkøres fra en ren attest-pipeline uden manuel DB-oprydning.
- Tilføjede backend-reset af servitutter, canonical cache, redegørelser, erklæringer og attest-pipeline-state samt en lille debug-endpoint for attest-dokumenter.
- Tilføjede attest-debugvisning i dokumentlisten og udvidede review-panelet med de vigtigste pipeline-v2-felter: status, fan-out-markering, `date_reference`, `scope_type`, `declaration_block_id` og flags.
- Tilføjede QA-checkliste i `servitut-frontend/docs/aalborg_frontend_qa.md` for Aalborg-flowet.
- Verificeret med backend-tests `26 passed`, extraction-service-tests `32 passed`, frontend `pnpm lint`, frontend `pnpm typecheck`, samt Alembic SQL-render for den nye migration.

## Frontend readiness assessment

- [x] Gennemgå frontend-flow for caseworkspace, upload, OCR/extraction-job og servitutvisning
- [x] Sammenhold UI-flow med backend-pipeline og identificér manglende koblinger eller åbenlyse gaps
- [x] Skriv en kort vurdering af om frontend er klar til realistisk test eller stadig for ufærdig

## Frontend readiness review

- Frontenden er teknisk testbar i sin nuværende form: upload, OCR-kø, extraction-job polling, review-liste, redegørelse og erklæring er alle koblet op i `src/features/cases/components/case-workspace.tsx`.
- Baseline-checks bestod i `servitut-frontend`: `pnpm lint` og `pnpm typecheck`.
- Den største funktionelle UI-gap er, at extraction-flowet antager at første fundne servitutter betyder "klar til review". `getAnalysisState()` sætter kun `canExtract` når `servitutter.length === 0`, så UI'et giver ikke en naturlig vej til at genkøre extraction efter et delvist eller forkert resultat.
- Pipeline-gapet er større end UI-gapet: frontend er bygget mod den nuværende backend-kontrakt, men backendens attest-pipeline er stadig den gamle LLM-drevne enumeration. Derfor er UI'et egnet til workflow-test og manuel review, men ikke et stærkt bevis på korrekthed for Aalborg-lignende cases.

## Claude review prompt plan

- [x] Saml den nødvendige kontekst om Aalborg vs. København/Middelfart og den nye attest-model
- [x] Skriv en præcis prompt, der beder Claude Code læse planen og lave sin egen uafhængige analyse
- [x] Gem prompten som en genbrugelig markdown-fil under `docs/`

## Claude review prompt review

- Oprettede `docs/claude_attest_solution_review_prompt.md` som en klar prompt til Claude Code.
- Prompten peger Claude til den nye planfil, beskriver Aalborg-problemet kontra tidligere cases og beder om en uafhængig evaluering af løsningsretningen.
- Prompten beder eksplicit om vurdering af datamodel, pipeline, risici, alternativ design og næste implementeringstrin, så outputtet bliver brugbart som arkitektur-review og ikke bare en opsummering.

## Attest registration model plan

- [x] Afklar de domænemæssige forskelle mellem Aalborg og de tidligere København/Middelfart-cases
- [x] Beskriv en generel attest-model, der ikke er afhængig af case-specifik prompt-tuning
- [x] Dokumentér hvornår scope kobles fra canonical entries til ejendommens matrikler
- [x] Beskriv hvordan modellen understøtter både erklæring og redegørelse som slutprodukter
- [x] Gem planen som en kort, præcis markdown-fil under `docs/`

## Attest registration model review

- Oprettede en ny plan i `docs/attest_registration_model_plan.md` for en generel attest-parser, der kan håndtere både klassiske cases (København/Middelfart) og Aalborgs fan-out-mønster med mange `date_reference` under samme synlige deklarationsblok.
- Planen fastlægger, at `date_reference` er den atomare canonical enhed, mens en `Prioritet`-/deklarationsblok er en metadata-kilde som kan fanes ud til mange registreringer.
- Scope-mappingen er placeret efter canonical fan-out og før akt-berigelse, så både erklæring og redegørelse bygger på samme strukturerede scope-grundlag.
- Dokumentet anbefaler en deterministisk attest-parser som primær motor og begrænser LLM-brug til metadata-berigelse og fallback, så løsningen ikke bliver prompt-tung eller case-specifik.

# Alembic and local PostgreSQL setup

- [x] Add Alembic configuration and a first migration that captures the current PostgreSQL schema.
- [ ] Adjust app startup so PostgreSQL schema changes are not silently handled by `create_all()`.
- [ ] Add local PostgreSQL bootstrap via Docker Compose.
- [ ] Document `DATABASE_URL`, local Postgres startup, and Alembic migration commands in `.env.example` and `README.md`.
- [ ] Verify the migration setup with targeted commands and record the outcome.

## Review

Progress:
- The initial Alembic baseline now matches the current ORM schema, including the new `jobs` table used by Celery-backed OCR and extraction polling.
- Verified the migration renders valid PostgreSQL DDL with `./.venv/bin/python -m alembic upgrade head --sql`.

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

# Celery worker architecture

- [x] Inspect current OCR/extraction API flow, DB session patterns, and existing job-style models before implementation.
- [x] Add `celery` and `redis` dependencies plus `REDIS_URL` configuration.
- [x] Introduce a background job model and DB table with storage helpers for create/read/update.
- [x] Implement Celery app and worker tasks for OCR and extraction with status/result updates in PostgreSQL.
- [x] Refactor OCR and extraction routes to enqueue jobs and return `202 Accepted` payloads instead of blocking.
- [x] Add a polling endpoint for job status under the case scope.
- [x] Run targeted verification and document outcomes here.

## Review

Outcome:
- Added a generic `Job` DTO plus a `jobs` SQLModel table so OCR and extraction can be tracked in PostgreSQL with `pending`, `processing`, `completed`, and `failed` states.
- Added `app/worker/celery_app.py` and `app/worker/tasks.py`; worker tasks now open their own DB sessions, call the existing OCR/extraction services, and persist status/result updates back to the job table.
- Refactored `POST /cases/{case_id}/documents/{doc_id}/ocr` and `POST /cases/{case_id}/extract` so they enqueue Celery work and immediately return `202 Accepted` with the new job payload.
- Added `GET /cases/{case_id}/jobs/{job_id}` for frontend polling, still protected by the existing case ownership guard.
- Updated `.env.example`, dependency metadata, and API tests so the new Redis/Celery layer is part of the documented runtime contract.

Verification:
- Synced dependencies with `uv sync --extra dev` to install `celery` and `redis`.
- Verified the async route flow with `./.venv/bin/python -m pytest -q tests/test_documents_api.py tests/test_jobs_api.py tests/test_auth_api.py`
- Verified the full repository with `./.venv/bin/python -m pytest -q`
- Result: `148 passed, 6 warnings`

# Local database reset for Aalborg clean slate

- [x] Inspect the PostgreSQL schema and confirm which tables can be cleared while preserving `users`
- [x] Record the exact reset command and verify local DB connectivity
- [x] Clear non-user application tables in local PostgreSQL
- [x] Verify that `users` still contains data and all other application tables are empty

## Review

- Local DB connectivity verified against `postgresql://postgres:postgres@127.0.0.1:5432/servitut` as user `postgres`.
- Reset command prepared:
  `TRUNCATE TABLE cases, chunks, documents, jobs, reports, servituterklaringer, servitutter, tmv_jobs RESTART IDENTITY CASCADE;`
- Reset executed successfully with `TRUNCATE TABLE`.
- Post-reset verification:
  `users=1`, `cases=0`, `documents=0`, `chunks=0`, `servitutter=0`, `jobs=0`, `reports=0`, `servituterklaringer=0`, `tmv_jobs=0`.
- Note: this reset only touched PostgreSQL. Files in `storage/` were intentionally left as-is.

# Split frontend upload by document type

- [x] Inspect the current Next.js upload flow, the Streamlit upload split, and the generated client support for `document_type`
- [x] Update the Next.js case upload UI to separate `tinglysningsattest` and `akt` uploads
- [x] Send explicit `document_type` values from frontend upload requests instead of relying on backend filename heuristics
- [x] Verify the frontend with `pnpm lint` and `pnpm typecheck`

## Review

- The Next.js case workspace now mirrors the Streamlit intent: one dedicated upload action for `tinglysningsattest` and one separate upload path for `akt`.
- Akt drag-and-drop is now explicitly bound to `akt`, while attest upload uses its own file input, so the backend no longer has to infer Aalborg document types from filenames.
- Frontend upload requests now send `document_type` in multipart form data through the generated client.
- Verification passed in `servitut-frontend`:
  `pnpm lint`
  `pnpm typecheck`

# Frontend upload size limit for Aalborg PDFs

- [x] Confirm whether the 50 MB rejection is only a frontend guard and inspect the oversized Aalborg files
- [x] Raise the Next.js upload size limit to cover the current oversized Aalborg akter
- [x] Verify the frontend and record the result

## Review

- Confirmed that the 50 MB cap lived only in `servitut-frontend/src/features/cases/components/case-workspace.tsx`; no matching backend upload cap was found in the FastAPI route.
- The blocked Aalborg akter were only slightly over the old limit: `51 MB`, `52 MB`, `56 MB`, and `60 MB`.
- Raised the frontend guard to `100 MB`, which covers the current Aalborg set without removing the guard entirely.
- Verification passed in `servitut-frontend`:
  `pnpm lint`
  `pnpm typecheck`
- For files materially above `100 MB`, the Streamlit split-PDF workflow remains the safer fallback than allowing arbitrarily large browser uploads.

# Remove uploaded documents before OCR

- [x] Inspect backend and frontend support for document deletion
- [x] Add a case-scoped `DELETE /cases/{case_id}/documents/{doc_id}` route and verify it
- [x] Regenerate the frontend API client for the new document-delete route
- [x] Add a delete action in the Next.js upload UI, limited to the pre-OCR state
- [x] Verify frontend checks and record the result

## Review

- Added `DELETE /cases/{case_id}/documents/{doc_id}` in FastAPI and wired it to the existing document removal service.
- Deletion is intentionally limited to documents with `parse_status="pending"` so users can clean up uploads before OCR without racing active processing.
- Regenerated the frontend client from a locally dumped OpenAPI spec (`/tmp/servitut-openapi.json`) because the running dev server's `/openapi.json` was not a stable source during this change.
- The Next.js upload list now shows a `Fjern` action per document; it is disabled once OCR has started.
- Verification passed:
  `./.venv/bin/python -m pytest -q tests/test_documents_api.py`
  `pnpm lint`
  `pnpm typecheck`
