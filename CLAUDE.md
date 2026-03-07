# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --extra dev          # install app + test dependencies
uv run uvicorn app.api.main:app --reload   # API on http://localhost:8000
uv run streamlit run streamlit_app/Home.py # UI on http://localhost:8501
uv run pytest -v             # full test suite (26 tests)
uv run pytest tests/test_report_generation.py -q  # focused service-level check
uv run pytest tests/test_chunking.py::test_name -v  # single test
```

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` before running the API or UI.

## Architecture

The pipeline processes Danish property deed PDFs (servitutter) through these stages:

```
PDF → OCR (Claude Vision) → PageData → Chunks → Servitut JSON → Report (Markdown)
```

**Stage 1 — OCR** (`app/services/ocr_service.py`): pymupdf renders each PDF page to PNG; Claude Vision reads the image and returns raw text as `PageData`. Images stored in `storage/cases/{case_id}/page_images/{doc_id}/`.

**Stage 2 — Chunking** (`app/services/chunking_service.py`): Paragraph-based splitting with configurable `MAX_CHUNK_SIZE` / `CHUNK_OVERLAP`. Chunk IDs = sha256(doc_id:page:chunk_index)[:12].

**Stage 3 — Extraction** (`app/services/extraction_service.py`): Keyword pre-screening (`app/utils/text.py:has_servitut_keywords`) filters chunks before sending to Claude. Processes per document. Returns `List[Servitut]`.

**Stage 4 — Reporting** (`app/services/report_service.py`): RAG service (`app/services/rag_service.py`) retrieves evidence chunks; Claude generates a Markdown table report.

## Storage Layout

All runtime data lives under `storage/` (treat as generated, not source):

```
storage/cases/{case_id}/
  case.json
  documents/{doc_id}/metadata.json   # Document model without pages
  ocr/{doc_id}_pages.json            # PageData list (pages stored separately)
  page_images/{doc_id}/page_N.png
  chunks/{doc_id}_chunks.json
  servitutter/{servitut_id}.json
  reports/{report_id}.json
```

All persistence goes through `app/services/storage_service.py` — never write storage paths inline in routes or other services.

## Key Conventions

- Route handlers in `app/api/routes/` stay thin; business logic belongs in `app/services/`.
- Use `app.core.config.settings` for all config; `app.core.logging.get_logger(__name__)` for logging.
- Pydantic v2 throughout: use `model_dump()` not `.dict()`.
- Prompts are plain text files in `prompts/` with `{placeholder}` variables replaced via `.replace()`. Three prompts exist: `ocr_page.txt`, `extract_servitut.txt` (uses `{chunks_text}`), `generate_report.txt` (uses `{servitutter_json}` and `{evidence_text}`).
- Tests use `tmp_path` and `monkeypatch` to override `settings.STORAGE_DIR`; cover happy paths and LLM error/fallback paths.
- Conventional Commit prefixes: `feat:`, `fix:`, `docs:`, `chore:`.




# Workflow Orchestration

## #1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don’t keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

## #2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

## #3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

## #4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: “Would a staff engineer approve this?”
- Run tests, check logs, demonstrate correctness

## #5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask “is there a more elegant way?”
- If a fix feels hacky: “Knowing everything I know now, implement the elegant solution”
- Skip this for simple, obvious fixes — don’t over-engineer
- Challenge your own work before presenting it

## #6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don’t ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

# Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items  
2. **Verify Plan**: Check plan in before starting implementation  
3. **Track Progress**: Mark items complete as you go  
4. **Explain Changes**: High-level summary at each step  
5. **Document Results**: Add review section to `tasks/todo.md`  
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections  

---

# Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what’s necessary. Avoid introducing bugs.
