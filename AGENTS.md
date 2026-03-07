# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `app/`: `api/` contains FastAPI routes, `services/` holds the pipeline logic, `models/` defines Pydantic schemas, `core/` contains settings and logging, and `utils/` contains small shared helpers. The Streamlit workflow lives in `streamlit_app/`, with numbered pages matching the processing flow (`3_Run_OCR.py`, `6_Extract_Servitutter.py`, `8_Review.py`). Prompts for LLM-backed steps are stored in `prompts/`. Tests live in `tests/`. Example PDFs are in `docs/sample_cases/`. Runtime case data is written under `storage/cases/`; treat that directory as generated state, not source.

## Build, Test, and Development Commands
Use `uv` for all local work:

- `uv sync --extra dev` installs the app and test dependencies into `.venv`.
- `uv run uvicorn app.api.main:app --reload` starts the API on `http://localhost:8000`.
- `uv run streamlit run streamlit_app/Home.py` starts the UI on `http://localhost:8501`.
- `uv run pytest -v` runs the full suite.
- `uv run pytest tests/test_report_generation.py -q` is useful for a focused service-level check.

Create `.env` from `.env.example` before running API or UI; key settings are `ANTHROPIC_API_KEY`, `MODEL`, `STORAGE_DIR`, and chunking limits.

## Coding Style & Naming Conventions
Target Python 3.11+ and follow PEP 8 with 4-space indentation. Use `snake_case` for modules, functions, and test names; use `PascalCase` for Pydantic models such as `ReportEntry`. Keep route handlers thin and place business logic in `app/services/`. Prefer typed function signatures and Pydantic serialization via `model_dump()` rather than legacy `.dict()`. Reuse `app.core.config.settings` for configuration and `app.core.logging.get_logger(__name__)` for logging.

## Testing Guidelines
Pytest is the only configured test runner; the repository currently collects 26 tests. Add tests in `tests/test_<feature>.py` and name cases `test_<behavior>()`. Isolate filesystem effects with `tmp_path` and `monkeypatch`, especially when overriding `settings.STORAGE_DIR`. Cover both happy paths and fallback/error paths for LLM-backed services.

## Commit & Pull Request Guidelines
Recent history favors short, imperative subjects with Conventional Commit prefixes when possible: `feat:`, `fix:`, `docs:`, `chore:`. Keep commits scoped to one change area. PRs should explain which pipeline stage is affected, list verification steps run (`uv run pytest -v`, manual API/UI checks), and include screenshots when Streamlit pages change. Link related issues or sample-case evidence when behavior changes are user-visible.


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
