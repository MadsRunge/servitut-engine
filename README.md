# Servitut Engine v1

Et Python-baseret system til automatisk udtræk, strukturering og AI-assisteret redegørelse af servitutter fra PDF-dokumenter. Designet til landinspektører, advokater og bygherrer der arbejder med tinglyste byrder på fast ejendom.

---

## Hvad er en servitut?

En servitut er en tinglyst byrde på en ejendom — fx vejret, byggelinjer, ledningsrettigheder eller fredningsdeklarationer. Servitutredegørelsen er det centrale dokument i en ejendomsanalyse: den opsummerer alle relevante byrder, angiver påtaleberettiget, retslig type og anbefalet handling.

Denne motor automatiserer processen fra rå PDF-akter til struktureret redegørelsestabel.

---

## Pipeline

```
PDF-dokumenter
     │
     ▼
[1] PDF Parsing (pdfplumber)
     │  → PageData (side-for-side tekst + extraction_method + confidence)
     │
     ▼
[2] Chunking (paragraph-split)
     │  → Chunk (stabile hash-IDs, side-reference, char-offsets)
     │
     ▼
[3] Pre-screening (keyword-filter)
     │  → Kun chunks med servitut-relevante ord videre til LLM
     │
     ▼
[4] Ekstraktion (Claude API)
     │  → Struktureret JSON pr. servitut (titel, dato, påtaleberettiget, ...)
     │
     ▼
[5] RAG (keyword-scoring)
     │  → Top-k evidens-chunks pr. servitut
     │
     ▼
[6] Rapport (Claude API)
     └  → Markdown-tabel + JSON-rapport med fuld sporbarhed
```

**Designprincip: Ekstraktion først. Formulering bagefter.**
Den valgte LLM-provider bruges to gange: én gang til at udtrække facts som JSON, én gang til at formulere den endelige redegørelse.

---

## Tech Stack

| Komponent | Teknologi | Begrundelse |
|-----------|-----------|-------------|
| PDF parsing | `pdfplumber` | Python-native, ingen externe tools, god tekstekstraktion fra digitale PDFer |
| LLM | Anthropic Claude eller DeepSeek | Provider styres via `.env`, så model og nøgle kan skiftes uden kodeændringer |
| Storage | PostgreSQL + lokale filer | Strukturerede data i PostgreSQL, binære artefakter som PDF/OCR-filer på disk |
| API | FastAPI + Pydantic v2 | Type-sikker, hurtig, god swagger-dokumentation |
| UI | Streamlit | Hurtig prototype-UI med minimal boilerplate |
| Dependency mgmt | `uv` + `pyproject.toml` | Hurtig, reproducerbar, moderne Python tooling |
| Tests | `pytest` | Standard, god integration med monkeypatching til storage-isolation |

---

## Projektstruktur

```
servitut-engine/
├── app/
│   ├── api/
│   │   ├── main.py                 # FastAPI app, CORS, router-inklusion
│   │   └── routes/
│   │       ├── cases.py            # POST/GET/DELETE /cases
│   │       ├── documents.py        # Upload, parse, chunks
│   │       ├── extraction.py       # Trigger ekstraktion, list servitutter
│   │       └── reports.py          # Generer og hent rapporter
│   ├── core/
│   │   ├── config.py               # Pydantic BaseSettings (.env-drevet)
│   │   └── logging.py              # Struktureret logging
│   ├── models/
│   │   ├── case.py                 # Case-model
│   │   ├── document.py             # Document + PageData
│   │   ├── chunk.py                # Chunk
│   │   ├── servitut.py             # Servitut + Evidence
│   │   └── report.py               # Report + ReportEntry
│   ├── services/
│   │   ├── storage_service.py      # Al fil-I/O (JSON load/save)
│   │   ├── case_service.py         # Case CRUD + pipeline-koordinering
│   │   ├── pdf_service.py          # pdfplumber-parsing, OCR-kandidat-detektion
│   │   ├── chunking_service.py     # Paragraph-split med overlap
│   │   ├── extraction_service.py   # Pre-screening + Claude API → Servitut-liste
│   │   ├── rag_service.py          # Keyword-scoring → top-k evidens-chunks
│   │   └── report_service.py       # Claude API → Report med Markdown-tabel
│   └── utils/
│       ├── ids.py                  # Stabile chunk-IDs (sha256), UUID-helpers
│       ├── text.py                 # Tekstrensning, danske keywords, dato-mønstre
│       └── files.py                # JSON load/save helpers
├── streamlit_app/
│   ├── Home.py                     # Oversigt over cases + pipeline-status
│   └── pages/
│       ├── 1_Create_Case.py        # Opret ny case
│       ├── 2_Upload_Documents.py   # Upload PDF-filer
│       ├── 3_Parse_Documents.py    # Trigger parsing, vis tekst + OCR-badge
│       ├── 4_Inspect_Chunks.py     # Gennemse chunks med filtrering
│       ├── 5_Extract_Servitutter.py # Trigger ekstraktion, vis JSON + confidence
│       ├── 6_Generate_Report.py    # Generer rapport, vis Markdown-tabel
│       └── 7_Review.py             # Sporbarhed: servitut → chunks → kilde-side
├── alembic/
│   ├── env.py                      # Alembic-konfiguration mod appens SQLModel metadata
│   └── versions/                   # Versionsstyrede database-migrations
├── alembic.ini                     # Alembic entrypoint og standard-DB URL
├── docker-compose.yml              # Lokal PostgreSQL til udvikling
├── prompts/
│   ├── extract_servitut.txt        # Dansk prompt til struktureret JSON-udtræk
│   └── generate_report.txt         # Dansk prompt til rapport-formulering
├── storage/
│   └── cases/                      # Runtime-data (gitignored undtagen .gitkeep)
├── tests/
│   ├── test_chunking.py            # Chunk-ID stabilitet, størrelse, page-ref
│   ├── test_extraction_schema.py   # Pydantic-validering, JSON-parsing
│   ├── test_case_service.py        # Case CRUD + storage round-trip
│   └── test_report_generation.py   # Rapport med mock Claude API
├── docs/                           # Eksempel-PDFer (testdata)
├── pyproject.toml
├── uv.lock
└── .env.example
```

---

## Storage-layout (runtime)

```
storage/cases/{case_id}/
  documents/{doc_id}/
    original.pdf                    # Uploadet PDF
    ocr.pdf                         # OCR-behandlet PDF
  ocr/
    {doc_id}_pages.json             # OCR-sider på disk til friskhedstjek
```

Strukturerede objekter som cases, dokumentmetadata, chunks, servitutter, rapporter
og jobs gemmes i PostgreSQL. Disklayoutet ovenfor bruges kun til binære artefakter
og enkelte OCR-sidefiler.

---

## Opsætning

### Forudsætninger

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installeret
- Docker Desktop eller en lokal PostgreSQL 16+ instans
- En Anthropic API-nøgle

### 1. Installer afhængigheder

```bash
uv sync --extra dev
```

Dette opretter `.venv` automatisk og installerer alle dependencies inkl. test-afhængigheder.

### 2. Konfigurer miljøvariable

```bash
cp .env.example .env
```

Åbn `.env` og vælg provider samt den relevante API-nøgle:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
MODEL=claude-sonnet-4-6
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
LLM_TIMEOUT_SECONDS=120
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/servitut
REDIS_URL=redis://127.0.0.1:6379/0
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
CORS_ALLOW_CREDENTIALS=true
STORAGE_DIR=storage
PROMPTS_DIR=prompts
MAX_CHUNK_SIZE=2000
CHUNK_OVERLAP=200
```

For DeepSeek, sæt fx:

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
MODEL=deepseek-chat
```

### 3. Start PostgreSQL lokalt

Anbefalet lokalt setup er Docker Compose:

```bash
docker compose up -d postgres
```

Det starter PostgreSQL på `127.0.0.1:5432` og opretter databasen `servitut`
automatisk.

### 4. Kør database-migrations

```bash
uv run alembic upgrade head
```

Alembic opretter også tabellen `alembic_version`, så I får et audit trail over
hvilke migrations der er kørt.

### 5. Start API-serveren

```bash
uv run uvicorn app.api.main:app --reload
```

API kører på `http://localhost:8000`. Swagger-dokumentation: `http://localhost:8000/docs`.

### 6. Start Streamlit UI

```bash
uv run streamlit run streamlit_app/Home.py
```

UI kører på `http://localhost:8501`.

### 7. Kør tests

```bash
uv run pytest tests/ -v
```

## Migrationer

Opret en ny migration:

```bash
uv run alembic revision --autogenerate -m "beskriv ændringen"
```

Anvend seneste migration:

```bash
uv run alembic upgrade head
```

Se nuværende migrationsniveau:

```bash
uv run alembic current
```

---

## Brug via UI (Streamlit)

Følg pipeline-trinene i rækkefølge via sidemenuen:

1. **Create Case** — Opret en sag med navn, adresse og evt. ekstern reference
2. **Upload Documents** — Upload én eller flere PDF-filer til sagen
3. **Parse Documents** — Kør pdfplumber-parsing; sider med lav tekstmængde markeres som OCR-kandidater
4. **Inspect Chunks** — Gennemse de opdelte chunks; filtrer på dokument og side
5. **Extract Servitutter** — Kald den valgte LLM-provider; se struktureret JSON pr. servitut med confidence-score
6. **Generate Report** — Generer den endelige redegørelse som Markdown-tabel
7. **Review** — Fuld sporbarhed: vælg en servitut og se de chunks og kilde-sider der lå til grund

---

## Brug via API

### Opret en case

```bash
curl -X POST http://localhost:8000/cases \
  -H "Content-Type: application/json" \
  -d '{"name": "Matr. 5a Lyngby", "address": "Lyngby Hovedgade 1"}'
```

### Upload et dokument

```bash
curl -X POST http://localhost:8000/cases/{case_id}/documents \
  -F "file=@docs/Servitutredegørelse fra Magnus Thernøe.pdf"
```

### Parse dokumentet (ekstrakt tekst + opret chunks)

```bash
curl -X POST http://localhost:8000/cases/{case_id}/documents/{doc_id}/parse
```

### Udtræk servitutter

```bash
curl -X POST http://localhost:8000/cases/{case_id}/extract
```

### Generer rapport

```bash
curl -X POST http://localhost:8000/cases/{case_id}/reports
```

---

## Konfiguration

Alle indstillinger styres via `.env` og eksponeres som Pydantic `BaseSettings`:

| Variabel | Standard | Beskrivelse |
|----------|----------|-------------|
| `LLM_PROVIDER` | `anthropic` | Aktiv provider: `anthropic` eller `deepseek` |
| `ANTHROPIC_API_KEY` | tom | Anthropic API-nøgle ved `LLM_PROVIDER=anthropic` |
| `DEEPSEEK_API_KEY` | tom | DeepSeek API-nøgle ved `LLM_PROVIDER=deepseek` |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | Base URL for DeepSeek OpenAI-kompatibelt endpoint |
| `MODEL` | `claude-sonnet-4-6` | Model-ID for den valgte provider |
| `LLM_TIMEOUT_SECONDS` | `120` | Timeout for LLM-kald |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/servitut` | Primær applikationsdatabase |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis til Celery broker/backend og health checks |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Komma-separeret liste eller JSON-array med tilladte frontend-origins |
| `CORS_ALLOW_CREDENTIALS` | `true` | Aktiver credentials/cookies på CORS-responses |
| `STORAGE_DIR` | `storage` | Rod-mappe for al data |
| `PROMPTS_DIR` | `prompts` | Mappe med prompt-filer |
| `MAX_CHUNK_SIZE` | `2000` | Maks tegn pr. chunk |
| `CHUNK_OVERLAP` | `200` | Overlap mellem chunks (tegn) |

---

## Tekniske detaljer

### Chunk-ID stabilitet

Chunk-IDs genereres deterministisk som `sha256(doc_id:page:chunk_index)[:12]`. Det betyder at samme dokument altid giver samme IDs — uanset hvornår det parses — hvilket giver stabil sporbarhed i evidens-referencer.

### Pre-screening

Før LLM kaldes, filtreres chunks på et sæt danske servitut-nøgleord (`servitut`, `deklaration`, `tinglyst`, `påtaleberettiget`, `byggelinje`, `vejret`, osv.). Dette reducerer API-forbrug og øger signal/støj-ratio i prompten.

### OCR-kandidat-detektion

Sider med færre end 50 tegn efter tekstekstraktion markeres som `ocr_candidate` med confidence `0.3`. Disse sider er sandsynligvis indskannede billeder og kan i en fremtidig version sendes til OCR-behandling.

### RAG (keyword-scoring)

Evidens-chunks til rapport-generering vælges via keyword-overlap: nøgleord udtrækkes fra servituttens titel og resumé, og alle chunks scores på antallet af matches. De top-k chunks vedlægges som evidens til rapport-prompten.

---

## Testdata

`/docs/`-mappen indeholder eksempel-PDFer fra et rigtigt sagssæt:

- **Servitutredegørelse fra Magnus Thernøe.pdf** — Ground truth-redegørelse med korrekt tabelformat
- **Indskannet akt fra Magnus Thernøe (1-3).pdf** — Worst-case input: indskannede håndskrevne akter
- **Ejendomssammendrag fra Magnus Thernøe.pdf** — Struktureret ejendomsoversigt
- **BBR Meddelelse fra Magnus Thernøe.pdf** — BBR-udtræk

Brug ground truth-redegørelsen til at evaluere systemets output.
