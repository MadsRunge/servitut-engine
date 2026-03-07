# CLAUDE.md — Servitut Engine

Dette dokument er den styrende kontekst for Claude Code-sessioner på dette projekt.
Læs det før du gør noget som helst.

---

## Hvad er dette projekt?

En Python-baseret motor til automatisk udtræk og AI-assisteret redegørelse af tinglyste servitutter fra PDF-dokumenter. Målgruppen er landinspektører, advokater og bygherrer.

**Kerneopgave:** Modtag PDF-akter → udtræk servitutter som struktureret JSON → formuler en professionel redegørelsestabel.

---

## Kritisk designprincip

**Ekstraktion først. Formulering bagefter.**

Claude bruges to gange i pipeline:
1. Til at udtrække facts som struktureret JSON (ingen formulering)
2. Til at formulere den endelige redegørelse baseret på det strukturerede JSON

Bland aldrig disse to trin. Ekstraktion skal altid kunne inspiceres uafhængigt af formuleringen.

---

## Pipeline (v1)

```
PDF → PageData (pdfplumber) → Chunks (paragraph-split) → Servitut JSON (Claude) → Rapport (Claude)
```

Trin:
1. **PDF parsing** — `app/services/pdf_service.py` — pdfplumber, side-for-side, OCR-kandidat-detektion
2. **Chunking** — `app/services/chunking_service.py` — paragraph-split med overlap, stabile hash-IDs
3. **Pre-screening** — `app/services/extraction_service.py` — keyword-filter før LLM-kald
4. **Ekstraktion** — `app/services/extraction_service.py` — Claude → `List[Servitut]` som JSON
5. **RAG** — `app/services/rag_service.py` — keyword-scoring, top-k evidens-chunks
6. **Rapport** — `app/services/report_service.py` — Claude → Markdown-tabel + JSON-rapport

---

## Hvad er allerede bygget (v1 baseline)

Alle filer under `app/`, `streamlit_app/`, `prompts/` og `tests/` er implementeret og fungerende.
26 tests passer (`uv run pytest tests/ -v`).

Fungerende:
- Case CRUD med JSON-persistens (`storage/cases/{case_id}/`)
- PDF parsing med pdfplumber + OCR-kandidat-detektion
- Paragraph-baseret chunking med stabile chunk-IDs
- Pre-screening med danske servitut-keywords
- Ekstraktion via Claude API → `List[Servitut]`
- RAG keyword-scoring → evidens-chunks
- Rapport-generering via Claude API → Markdown-tabel
- FastAPI med fuld CRUD + pipeline-endpoints
- Streamlit UI med 7 pipeline-trin (sider 1–7)

---

## Hvad der IKKE skal bygges i v1

Hold scope stramt. Disse ting hører til v2 eller senere:

- Ingen BBR/Datafordeler-integration
- Ingen autentificering eller brugeradministration
- Ingen database (PostgreSQL, SQLite etc.) — brug JSON-filer
- Ingen vektor-database eller embedding-baseret RAG
- Ingen OCR-implementering (marker kandidater, implementer ikke)
- Ingen asynkron task-queue (Celery, Redis etc.)
- Ingen deployment-infrastruktur (Docker, CI/CD etc.)

---

## Testdata

Realistiske eksempel-PDFer ligger i `docs/sample_cases/magnus/`:

| Fil | Type | Formål |
|-----|------|--------|
| `Servitutredegørelse fra Magnus Thernøe.pdf` | Ground truth | Facit — korrekt output-format |
| `Servitutredegørelse 22258.pdf` | Ground truth | Andet eksempel på korrekt format |
| `Indskannet akt fra Magnus Thernøe.pdf` | Indskannet akt | Worst-case input (håndskrevet/skannet) |
| `Indskannet akt fra Magnus Thernøe (1-3).pdf` | Indskannede akter | Flere worst-case eksempler |
| `Ejendomssammendrag fra Magnus Thernøe.pdf` | Struktureret dokument | Typisk input |
| `BBR Meddelelse fra Magnus Thernøe.pdf` | BBR-udtræk | Supplement til servitutanalyse |
| `Metodeforslag AI servitutredegørelse.pdf` | Metodedokument | Baggrundsviden om domænet |

Brug ground truth-filerne til at evaluere systemets output kvalitativt.

---

## Redegørelsestabelformat (ground truth)

Kolonner i den korrekte output-tabel:

| Nr. | Dato/løbenummer | Beskrivelse af indhold | Påtaleberettiget | Rådighed/tilstand | Offentlig/privatretlig | Håndtering/Handling | Vedrører projektområdet |

Dette format er defineret i `prompts/generate_report.txt` og i `app/models/report.py` (`ReportEntry`).

---

## Storage-struktur

```
storage/cases/{case_id}/
  case.json
  documents/{doc_id}/
    original.pdf
    metadata.json        # dokument-metadata uden pages
    pages.json           # side-for-side tekst
    chunks.json          # alle chunks
  servitutter/
    {servitut_id}.json
  reports/
    {report_id}.json
```

Al data er plain JSON. Læs frit med `cat` eller en editor for at debugge.

---

## Nøglefiler

```
app/core/config.py              Pydantic Settings — alle env-variabler
app/services/pdf_service.py     PDF parsing
app/services/chunking_service.py Chunking
app/services/extraction_service.py Pre-screening + Claude ekstraktion
app/services/rag_service.py     Keyword-scoring RAG
app/services/report_service.py  Rapport-generering
app/services/storage_service.py Al fil-I/O
prompts/extract_servitut.txt    Ekstraktions-prompt ({chunks_text})
prompts/generate_report.txt     Rapport-prompt ({servitutter_json}, {evidence_text})
```

---

## Kørsel

```bash
uv sync --extra dev                                    # installer dependencies
cp .env.example .env                                   # tilføj ANTHROPIC_API_KEY
uv run uvicorn app.api.main:app --reload               # API på :8000
uv run streamlit run streamlit_app/Home.py             # UI på :8501
uv run pytest tests/ -v                                # kør tests
```

---

## Kodekonventioner

- **Pydantic v2** — brug `model_dump()`, ikke `.dict()`
- **Ingen globale side-effekter** — services må ikke importere hinanden cirkulært
- **Logging** — brug `get_logger(__name__)` fra `app.core.logging`
- **Fejlhåndtering** — API-lag kaster `HTTPException`, services logger og re-raiser
- **Test-isolation** — brug `monkeypatch` på `settings.STORAGE_DIR` til at pege på `tmp_path`
- **Ingen requirements.txt** — brug kun `pyproject.toml` + `uv`
