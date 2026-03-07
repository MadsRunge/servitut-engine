import json
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.report import Report, ReportEntry
from app.models.servitut import Servitut
from app.services.llm_service import generate_text
from app.services.rag_service import find_relevant_chunks
from app.utils.ids import generate_report_id

logger = get_logger(__name__)


def _load_prompt() -> str:
    prompt_path = settings.prompts_path / "generate_report.txt"
    return prompt_path.read_text(encoding="utf-8")


def _build_evidence_text(servitutter: List[Servitut], all_chunks: List[Chunk]) -> str:
    parts = []
    for srv in servitutter:
        top_chunks = find_relevant_chunks(srv, all_chunks, top_k=3)
        if top_chunks:
            chunk_texts = "\n".join(f"  [Side {c.page}]: {c.text[:400]}" for c in top_chunks)
            parts.append(f"Servitut '{srv.title}':\n{chunk_texts}")
    return "\n\n".join(parts)


def generate_report(
    servitutter: List[Servitut],
    all_chunks: List[Chunk],
    case_id: str,
) -> Report:
    """Generate a structured report from extracted servitutter."""
    report_id = generate_report_id()
    prompt_template = _load_prompt()

    servitutter_json = json.dumps(
        [s.model_dump() for s in servitutter],
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    evidence_text = _build_evidence_text(servitutter, all_chunks)

    prompt = prompt_template.replace("{servitutter_json}", servitutter_json)
    prompt = prompt.replace("{evidence_text}", evidence_text)

    markdown_content: Optional[str] = None
    entries: List[ReportEntry] = []
    notes: Optional[str] = None

    try:
        response_text = generate_text(prompt, max_tokens=8192).strip()

        # Parse JSON response
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(response_text[start:end])
            markdown_content = data.get("markdown_table")
            notes = data.get("notes")
            for i, entry_data in enumerate(data.get("entries", []), 1):
                entries.append(
                    ReportEntry(
                        nr=i,
                        date_reference=entry_data.get("date_reference"),
                        description=entry_data.get("description"),
                        beneficiary=entry_data.get("beneficiary"),
                        disposition=entry_data.get("disposition"),
                        legal_type=entry_data.get("legal_type"),
                        action=entry_data.get("action"),
                        relevant_for_project=entry_data.get("relevant_for_project", False),
                        servitut_id=entry_data.get("servitut_id", ""),
                    )
                )
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        # Fallback: build basic entries from servitutter
        for i, srv in enumerate(servitutter, 1):
            entries.append(
                ReportEntry(
                    nr=i,
                    date_reference=srv.date_reference,
                    description=srv.summary,
                    beneficiary=srv.beneficiary,
                    disposition=srv.disposition_type,
                    legal_type=srv.legal_type,
                    action=srv.action_note,
                    relevant_for_project=srv.construction_relevance,
                    servitut_id=srv.servitut_id,
                )
            )

    report = Report(
        report_id=report_id,
        case_id=case_id,
        servitutter=entries,
        notes=notes,
        markdown_content=markdown_content,
    )
    return report
