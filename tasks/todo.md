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

## Middelfart priority rerun plan

- [x] Reset Middelfart extraction/report artifacts without touching OCR/chunks
- [x] Re-run extraction and historical report generation with the current Claude-extraction / DeepSeek-report split
- [x] Inspect `11.03.1974-1904-40` and nearby 1974 rows to see whether the new priority logic resolved the akt match
- [x] Document whether the remaining issue is solved, reduced, or still requires another fix

## Middelfart priority rerun review

- Reset the generated `servitutter/` and `reports/` directories for `case-683ad567` while keeping OCR and chunk artifacts intact
- Re-ran extraction with all case matrikler (`0069f`, `0001o`, `0038b`, `0022a`, `0001v`) as the intended target scope for the historical evaluation
- The decisive akt `doc-d25aaf4c` (`40_F_439_indskannetakt.pdf`) returned `0 match(es)` during enrichment, so the new priority logic did not get a valid dedicated-match candidate for `11.03.1974-1904-40`
- The final extracted 1974 rows still show the wrong enrichment source:
  - `11.03.1974-1904-40` ended as `source_document=doc-79628fe3`, `akt_nr=40_F_439`, `raw_matrikel_references=['1n']`, `scope_source='akt'`
  - `03.07.1974-5375-40` remained tied to `doc-79628fe3` (`Indskannet akt 40 B 649.pdf`) with matrikel `22a`
- This means the priority change alone did **not** solve the 1974 problem; the root cause is upstream of the priority rule because the dedicated akt is not yielding a usable canonical match
- Inspection of `doc-d25aaf4c` chunks shows OCR text dominated by later 1982/2005/2009 material and only weak `40_F_439` anchors, while `doc-79628fe3` contains explicit 1974 kabeldeklaration text for `22a`/`67`, which explains why background enrichment still wins
- The full-case Claude extraction also hit Anthropic rate limits (`429 rate_limit_error`) on several akt calls, so the current Sonnet 4.6 setup is not yet robust for an unrestricted Middelfart full-case rerun without throttling, retries, or lower prompt volume

## LLM payload analysis plan

- [x] Inspect extraction and enrichment prompt assembly to identify exactly which akt content is sent to the LLM
- [x] Measure prompt sizes for the Middelfart akt documents using the current chunk files and prompts
- [x] Estimate why the current payloads exceed the configured Claude input token budget per minute
- [x] Summarize the concrete payload structure and the biggest token drivers

## LLM payload analysis review

- Akt-enrichment sender hele `chunk_list` for hvert akt-dokument til LLM'en via `_build_chunks_text(chunk_list)` i `app/services/extraction/enricher.py`; der sker ingen retrieval eller top-k-filtering før kaldet
- Chunking er side-/afsnitsbaseret med `MAX_CHUNK_SIZE=2000` og `CHUNK_OVERLAP=200`, men enrichment samler derefter alle chunks for dokumentet tilbage i én stor prompt
- Den statiske enrich-prompt uden akttekst er ca. `5603` tegn, inkl. instruktionsblokken, case-matrikler og et repræsentativt canonical JSON på ca. `1294` tegn; den store omkostning er derfor selve aktteksten
- Middelfart-målingen viser følgende omtrentlige inputstørrelser pr. akt (`tegn / ~tokens`):
  - `doc-86bd246c` / `Indskannet akt 40 D 66.pdf`: `121626` tegn / ca. `30406` tokens
  - `doc-d25aaf4c` / `40_F_439_indskannetakt.pdf`: `72473` tegn / ca. `18118` tokens
  - `doc-888aefda` / `Indskannet akt 40 B 405.pdf`: `61701` tegn / ca. `15425` tokens
  - `doc-a1d14fd2` / `40_C_239_indskannetakt.pdf`: `55298` tegn / ca. `13824` tokens
  - `doc-f3b5c988` / `40_P_167_indskannetakt.pdf`: `52857` tegn / ca. `13214` tokens
  - `doc-540a3618` / `Indskannet akt 40.pdf`: `43070` tegn / ca. `10768` tokens
  - `doc-79628fe3` / `Indskannet akt 40 B 649.pdf`: `41633` tegn / ca. `10408` tokens
  - `doc-a021259a` / `Indskannet akt 40 M 201.pdf`: `32853` tegn / ca. `8213` tokens
  - `doc-19f507cc` / `Indskannet akt 40C 164.pdf`: `13799` tegn / ca. `3450` tokens
- Samlet over de 9 Middelfart-akter er enrichment-payloaden ca. `495310` tegn, dvs. omtrent `123828` input tokens, før output tokens
- Det forklarer rate-limit problemet mod Claude Sonnet 4.6: flere enkelte akt-prompts er i sig selv meget store, og hele Middelfart-batchen ligger langt over organisationens `30000` input-tokens-per-minute grænse

## Streamlit width migration plan

- [x] Find alle `use_container_width`-kald i Streamlit-koden
- [x] Udskift dem med det nye `width`-API med samme visuelle semantik
- [x] Verificer at der ikke er flere `use_container_width`-kald tilbage

## Streamlit width migration review

- Opdaterede alle Streamlit-knapper, download-knapper og dataframes, så `use_container_width=True` nu er `width="stretch"` og `use_container_width=False` er `width="content"`
- Rettede kald i `streamlit_app/pages/3_Run_OCR.py`, `streamlit_app/pages/6_Filter_Chunks.py` og `streamlit_app/pages/8_Generate_Report.py`
- Verificerede med en tekstsøgning, at der ikke længere findes `use_container_width` i `streamlit_app`, `app` eller `tests`

## OCR progress sync fix plan

- [x] Gennemgå OCR-sidens batch-progress og find hvorfor UI'et bruger stale dokumentstatus
- [x] Opdatér OCR-siden til at genlæse status fra `storage` efter hver afsluttet fil og vise total fremdrift for hele sagen
- [x] Verificér ændringen med en fokuseret syntaks-/integritetskontrol

## OCR progress sync review

- OCR-siden i `streamlit_app/pages/3_Run_OCR.py` viser nu summary-metrics via placeholders, så `Dokumenter i alt`, `OCR færdige` og `Klar til kørsel` kan opdateres under batch-kørslen
- Batch-progress bruger nu frisk status fra `storage_service.list_documents(case_id)` efter hver fil i stedet for den oprindelige `docs`-liste fra side-load
- Snapshot-listen viser nu hele sagens dokumenter med status afledt fra faktisk `parse_status`, så allerede færdige dokumenter tæller med i fremdriften
- Progressbaren viser total OCR-fremdrift for sagen (`ocr_done` / alle dokumenter) i stedet for kun antal gennemløbte batch-elementer
- Verificerede ændringen med `uv run python -m py_compile streamlit_app/pages/3_Run_OCR.py`

## Aalborg OCR reset plan

- [x] Identificér Aalborg-sagen og kortlæg hvilke artefakter der er genereret fra OCR
- [x] Nulstil OCR- og chunk-artefakter for Aalborg uden at slette originale PDF-filer eller sagsmetadata
- [x] Verificér at dokumentmetadata er sat tilbage til pre-OCR status og dokumentér resultatet

## PDF split feature plan

- [x] Kortlæg upload-flowet og design en minimal split-løsning til store PDF'er
- [x] Tilføj en PDF-split-service med validering af sideintervaller og generering af PDF-dele
- [x] Integrér split-flowet i Streamlit-upload-siden, så brugeren kan opdele og uploade del-PDF'er
- [x] Verificér med fokuserede tests og dokumentér resultatet

## PDF split feature review

- Tilføjede `app/services/pdf_service.py` med sideoptælling, forslag til split-intervaller, validering af brugerens sideintervaller og generering af del-PDF'er via PyMuPDF
- Tilføjede en delt dokument-oprettelseshelper i `app/services/document_service.py`, så API og Streamlit-sider bruger samme logik til at gemme PDF'er som sagsdokumenter
- Split-flowet ligger nu på en separat Streamlit-side før upload, hvor brugeren kan uploade én PDF, se samlet sidetal, generere standardintervaller og gemme de valgte dele direkte som individuelle `akt`-dokumenter
- Upload-siden er ryddet tilbage til almindelig upload af tinglysningsattest og akter, med et link videre til split-siden for store filer
- Verificeret med `uv run pytest tests/test_pdf_service.py tests/test_documents_api.py -q` (`7 passed`) og `uv run python -m py_compile streamlit_app/pages/2a_Split_PDF.py streamlit_app/pages/2_Upload_Documents.py streamlit_app/Home.py streamlit_app/ui.py app/services/pdf_service.py app/services/document_service.py app/api/routes/documents.py`

## Report editor plan

- [x] Afklar rapportflowet og placér manuel redigering som et særskilt trin efter rapportgenerering
- [x] Udtræk delt rapport-rendering og tilføj helperlogik til at gemme redigerede rapportrækker tilbage på modellen
- [x] Tilføj en separat Streamlit-side med stort redigeringsvindue til rapporttabellen og eksport af den redigerede version
- [x] Opdatér navigation og workflow, så review ligger efter rapportredigering
- [x] Verificér med fokuserede tests og syntakskontrol

## Report editor review

- Tilføjede delt rapport-rendering i `app/services/report_render_service.py`, så genererede og manuelt redigerede rapporter bruger samme markdown- og HTML-eksport
- Tilføjede `app/services/report_editor_service.py`, som konverterer rapportposter til editor-rækker, sorterer efter prioritet (`nr`), renummererer og gemmer den opdaterede tabel tilbage på rapporten
- Udvidede `Report`-modellen med `edited_at` og `manually_edited`, så manuelle rettelser kan spores
- Tilføjede en ny side `streamlit_app/pages/9_Edit_Report.py`, hvor brugeren kan redigere hele rapporttabellen i et stort `data_editor`-vindue, gemme rettelser og eksportere den redigerede rapport
- Flyttede review-siden til `streamlit_app/pages/10_Review.py` og opdaterede pipeline-navigationen, så redigering nu er trin 9 og review trin 10
- Opdaterede rapportsiden og forsiden, så workflowet peger videre til redigering efter rapportgenerering
- Verificeret med `uv run pytest tests/test_report_generation.py tests/test_report_editor_service.py -q` (`12 passed`) og `uv run python -m py_compile streamlit_app/pages/8_Generate_Report.py streamlit_app/pages/9_Edit_Report.py streamlit_app/pages/10_Review.py streamlit_app/Home.py streamlit_app/ui.py app/services/report_service.py app/services/report_render_service.py app/services/report_editor_service.py app/models/report.py`

## OCR performance optimization plan

- [x] Gennemgå OCR-flowet og fastlæg hvor genkørsel og sekventielt arbejde koster unødigt meget tid
- [x] Implementér artifact-reuse så uændrede PDF'er kan genbruge eksisterende `ocr.pdf`, OCR-sider og chunks
- [x] Saml OCR-pipeline-logikken i én service, så Streamlit og API bruger samme optimerede vej
- [x] Tilføj tests for cache-hit/cache-miss-adfærd og kør fokuseret verifikation

## OCR performance optimization review

- OCR-kørslen havde to konkrete flaskehalse: `ocrmypdf` blev tvunget til `jobs=1`, og både UI og API kørte hele OCR-kæden igen selv når `ocr.pdf`, OCR-sider og chunks allerede fandtes og var friske
- Tilføjede en fælles `run_document_pipeline()` i `app/services/ocr_service.py`, som genbruger eksisterende artefakter når `original.pdf` ikke er nyere end de afledte filer
- Streamlit- og API-laget bruger nu samme pipeline, så optimeringen gælder både batchkørsel og enkeltkørsel
- OCR-workerantal er nu konfigurerbart via `OCR_JOBS`; standarden er auto (`0` => op til 4 CPU-kerner) i stedet for hårdkodet single-threaded kørsel
- Verificeret med `uv run pytest tests/test_ocr_pipeline.py tests/test_documents_api.py -q` (`15 passed`)

## Aalborg OCR reset review

- Identificerede Aalborg-sagen som `case-947bbd23`
- Fjernede alle genererede OCR-page JSON-filer i `storage/cases/case-947bbd23/ocr`, alle chunk JSON-filer i `storage/cases/case-947bbd23/chunks` samt alle eksisterende `ocr.pdf`-artefakter under dokumentmapperne
- Nulstillede alle 12 dokumenters OCR-metadata tilbage til pre-OCR state: `parse_status='pending'`, `page_count=0`, `chunk_count=0`, `ocr_blank_pages=0`, `ocr_low_conf_pages=0`
- Verificerede, at der ikke længere findes filer i `ocr/` eller `chunks/`, og at alle `original.pdf` stadig ligger intakt under dokumentmapperne
- Ved efterkontrol viste UI'et `1` OCR-færdig; det skyldtes ikke en tællebug men at `doc-9b92f3d5` var blevet skrevet færdig igen kl. `2026-03-10 16:06:13`
- Kørte derfor resetten igen og verificerede bagefter `OCR_DONE_COUNT=0` samt `0` filer i både `ocr/` og `chunks/`

## OCR live progress refactor plan

- [x] Reproducer hvorfor den aktuelle OCR-side ikke føles live under batch-kørsel
- [x] Refaktorer batch-OCR til en rerun-baseret model, så siden genrender mellem dokumenter med frisk state fra storage
- [x] Verificér den nye flowlogik og dokumentér resultatet

## OCR live progress refactor review

- Root cause var Streamlit execution-model: den tidligere batch-kode forsøgte at holde hele OCR-kørslen i ét langt run med placeholders, hvilket ikke gav en robust live-UI for lange OCR-job
- Batch-OCR i `streamlit_app/pages/3_Run_OCR.py` kører nu ét dokument per rerun via `st.session_state`, så siden genindlæser mellem dokumenter og læser frisk status fra disk hver gang
- Tilføjede batch-state pr. sag, progressvisning baseret på faktisk `ocr_done`-status, samt en `Stop batch-OCR`-knap
- Deaktiverede enkelt-dokument-knapper og retry-knappen mens batch kører, så der ikke opstår konkurrerende OCR-skrivninger
- Verificerede syntaksen med `uv run python -m py_compile streamlit_app/pages/3_Run_OCR.py`

## Report download button fix plan

## Hosting evaluation plan

- [x] Kortlæg projektets runtime-arkitektur og aktuelle storage-model
- [x] Sammenhold Streamlit, FastAPI, OCR og filstorage med relevante hostingplatformes begrænsninger
- [x] Anbefal en konkret hostingstrategi for nuværende kodebase samt en multi-user storage-retning

## Hosting evaluation review

- Bekræftede, at Streamlit-siderne kalder services direkte i Python og læser/skriver runtime-data via `storage/cases`, så appen er stateful og ikke designet som stateless frontend mod et separat API-lag
- Bekræftede, at OCR-pipelinen bruger `ocrmypdf`, hvilket kræver systempakker ud over Python dependencies og gør platformvalg mere restriktivt
- Vurderede Render som bedste kortsigtede hostingmatch for nuværende kodebase, fordi en enkelt Docker-service med persistent disk matcher både Streamlit, OCR og lokal artefakt-cache
- Vurderede, at rigtig per-user isolation ikke bør bygges som “én fysisk disk pr. bruger”, men som applikationsstyret separation via bruger-id, sagsejerskab og på sigt database + objektstorage

## Hosting documentation plan

- [x] Definér hvilke dele af Render-deployet der skal dokumenteres for den nuværende kodebase
- [x] Beskriv en kortsigtet multi-user model oven på eksisterende filstorage
- [x] Beskriv en langsigtet arkitektur med database og objektstorage og gem dokumentet i `docs/`

## Hosting documentation review

- Oprettede en samlet drifts- og arkitekturguide i `docs/render-hosting-og-multi-user-arkitektur.md`
- Dokumentationen beskriver både den anbefalede v1-deploy på Render med én Docker-service og persistent disk samt de konkrete begrænsninger ved at køre OCR og storage stateful i én instans
- Dokumentationen beskriver en minimal multi-user model for den nuværende app med `owner_user_id` og bruger-separerede stier under `storage/`
- Dokumentationen beskriver også den anbefalede fremtidige SaaS-retning med auth, Postgres, objektstorage og asynkron jobafvikling

- [x] Find årsagen til `StreamlitDuplicateElementId` på rapport-siden
- [x] Tilføj stabile unikke keys til rapportens download-knapper
- [x] Verificér at siden stadig parser syntaktisk

## Report download button fix review

- Fejlen skyldtes tre `download_button`-widgets uden eksplicit `key`, gengivet i en loop over rapporter
- Tilføjede unikke keys baseret på `report.report_id` til markdown-, html- og json-downloadknapperne i `streamlit_app/pages/8_Generate_Report.py`
- Verificerede syntaksen med `uv run python -m py_compile streamlit_app/pages/8_Generate_Report.py`

## Report fallback root-cause analysis plan

- [x] Gennemgå rapport-pipelinen og identificér hvilke fejl der sender `generate_report()` i fallback
- [x] Mål de faktiske inputstørrelser for rapport-prompts på Aalborg og Middelfart
- [x] Vurder om fallback mest sandsynligt skyldes inputstørrelse, outputtrunkering eller JSON-parse-fejl

## Report fallback root-cause analysis review

- `generate_report()` falder tilbage ved enhver exception i LLM-kaldet eller JSON-parsingen; den præcise fejl gemmes kun i runtime-loggen og ikke i rapport-JSON
- Aalborg-rapporten bruger en ekstremt stor prompt: ca. `178527` tegn, dvs. omtrent `44631` input tokens (`servitutter_json` alene ca. `31518` tokens og `evidence_text` yderligere ca. `12519` tokens)
- Middelfart-rapporten er markant mindre, men stadig stor: ca. `59911` tegn, dvs. omtrent `14977` input tokens
- Rapport-inputtet er redundant: hele `Servitut.model_dump()` sendes til modellen, inklusive nested `evidence` og øvrige felter, og derefter sendes et separat `evidence_text` oveni med top-chunks for samme servitutter
- Estimeret outputstørrelse ser ikke ud til at være den primære flaskehals (`~5833` tokens for Aalborg-lignende JSON og `~2207` tokens for Middelfart-lignende JSON, begge under `max_tokens=8192`)
- Den mest sandsynlige root cause er derfor ikke outputtrunkering men at rapport-prompten er for tung og redundant, hvilket gør DeepSeek-reportkaldet skrøbeligt og øger sandsynligheden for et ikke-parsebart JSON-svar; på Aalborg er inputstørrelsen i sig selv sandsynligvis stor nok til at være hovedårsagen

## OCR/extraction follow-up fix plan

- [x] Gør OCR batch-flowet eksplicit None-sikkert, så afslutningsgrenen ikke kan falde videre til spinner-kaldet
- [x] Fjern N+1-dokumentload i canonical-attest-udtræk ved at preloade dokumentmetadata pr. dokument-id
- [x] Erstat cross-module imports af private scoring-funktioner med et offentligt API og opdatér brugere/tests
- [x] Kør fokuseret verifikation for OCR- og extraction-flowet og dokumentér resultatet

## OCR/extraction follow-up fix review

- OCR-batchen i `streamlit_app/pages/3_Run_OCR.py` har nu en eksplicit `else`-gren omkring spinner/run-kaldet, så `next_doc is None` ikke kan falde videre til OCR-eksekvering selv hvis `st.rerun()`-semantikken ændrer sig
- `extract_canonical_from_attest()` og den øvrige dokumenttype-opslag i `app/services/extraction_service.py` preloader nu dokumentmetadata én gang via `storage_service.list_documents(case_id)` i stedet for per chunk / per dokument-opslag
- Scoring-funktionerne i `app/services/extraction/enricher.py` er gjort offentlige som `build_scoring_signals`, `score_chunks` og `select_candidate_chunks`, og imports/tests er opdateret til at bruge dem
- Beholdt midlertidige aliases til de gamle private navne i enricheren for bagudkompatibilitet inde i modulet, men cross-module brug er flyttet til det offentlige API
- Verificeret med `uv run pytest tests/test_ocr_pipeline.py tests/test_documents_api.py tests/test_extraction_service.py -q` (`31 passed`) samt `python -m py_compile` på de ændrede OCR-/extraction-filer

## Sidebar step UI fix plan

- [x] Gennemgå sidebar-stepvisualiseringen og identificér hvorfor hover/click giver ustabil UI-opførsel
- [x] Refaktorer komponenten i `streamlit_app/ui.py`, så den er visuelt isoleret og ikke interaktiv
- [x] Kør fokuseret syntaks-/integritetskontrol og dokumentér resultatet

## Sidebar step UI fix review

- Sidebar-stepvisualiseringen i `streamlit_app/ui.py` var en dekorativ custom HTML-render uden eget CSS-scope; fixet isolerer den nu i egne `sidebar-steps`/`sidebar-step`-klasser i stedet for at genbruge de almindelige pipeline-pills
- Komponenten er nu eksplicit ikke-interaktiv med `pointer-events: none`, `user-select: none` og `cursor: default`, så hover/click ikke kan trigge selection/focus-opførsel i sidebarens widget-lag
- Aktivt trin bevares visuelt via dedikeret `sidebar-step.active`-styling, men uden transitions eller interaktionsadfærd
- Verificeret med `python -m py_compile` på `streamlit_app/ui.py` samt alle Streamlit-sider

## Streamlit UI hardening plan

- [x] Gennemgå fælles UI-helpers og sider med `unsafe_allow_html=True` for DOM-fragile mønstre
- [x] Sanitizér dynamiske værdier i `streamlit_app/ui.py` og fjern usikker rå HTML, hvor native widgets er nok
- [x] Omskriv progress-/statusvisninger i extract/filter-sider til sikker Markdown uden HTML-injektion
- [x] Kør fokuseret verifikation af Streamlit-modulerne og dokumentér resultatet

## Streamlit UI hardening review

- `streamlit_app/ui.py` escaper nu dynamiske værdier i hero, sektioner, empty states, stat cards, case-banner og rapportkort, så rå HTML ikke kan brydes af case-/LLM-data
- Fjernede den ubrugte `render_panel_start`/`render_panel_end`-helper, som byggede åbne/lukkede `<div>`-tags over flere Streamlit-calls og derfor var et latent DOM-risiko-mønster
- Progress-visningerne i `streamlit_app/pages/6_Filter_Chunks.py` og `streamlit_app/pages/7_Extract_Servitutter.py` bruger nu almindelig Markdown i stedet for `unsafe_allow_html=True`
- Extract-sidens servitut-footer bruger nu ren tekst i `st.caption(...)` i stedet for HTML-entiteter og `unsafe_allow_html`
- Verificeret med `python -m py_compile` på `streamlit_app/ui.py`, `streamlit_app/Home.py` og alle Streamlit-sider
