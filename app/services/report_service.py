from datetime import date
import json
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.report import Report, ReportEntry
from app.models.servitut import Servitut
from app.services.llm_service import generate_text
from app.services.matrikel_service import filter_servitutter_for_target, resolve_matching_target_matrikler
from app.services.rag_service import find_relevant_chunks
from app.utils.ids import generate_report_id

logger = get_logger(__name__)


def _resolve_report_provider() -> str | None:
    if settings.REPORT_LLM_PROVIDER.strip():
        return settings.REPORT_LLM_PROVIDER.strip()
    return None


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


def _resolve_report_model() -> str | None:
    if settings.REPORT_MODEL.strip():
        return settings.REPORT_MODEL.strip()
    provider = (settings.REPORT_LLM_PROVIDER or settings.LLM_PROVIDER).strip().lower()
    if provider == "deepseek":
        return "deepseek-reasoner"
    return None


def _filter_servitutter_by_as_of_date(
    servitutter: List[Servitut],
    as_of_date: Optional[date],
) -> List[Servitut]:
    if as_of_date is None:
        return servitutter
    return [
        srv
        for srv in servitutter
        if srv.registered_at is None or srv.registered_at <= as_of_date
    ]


def _extract_json_object(text: str) -> dict:
    candidates = [text.strip()]
    if "```" in text:
        import re

        fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        candidates.extend(block.strip() for block in fenced_blocks if block.strip())

    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        candidates.append(text[start:end].strip())

    for candidate in dict.fromkeys(candidates):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    raise ValueError("No JSON object could be parsed from report response")


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _build_report_entries(
    entry_payloads: List[dict],
) -> List[ReportEntry]:
    entries: List[ReportEntry] = []
    for i, entry_data in enumerate(entry_payloads, 1):
        scope_val = entry_data.get("scope")
        entries.append(
            ReportEntry(
                nr=i,
                date_reference=entry_data.get("date_reference"),
                description=entry_data.get("description"),
                beneficiary=entry_data.get("beneficiary"),
                disposition=entry_data.get("disposition"),
                legal_type=entry_data.get("legal_type"),
                action=entry_data.get("action"),
                relevant_for_project=_coerce_bool(
                    entry_data.get("relevant_for_project"),
                    default=scope_val == "Ja",
                ),
                scope=scope_val,
                scope_detail=entry_data.get("scope_detail"),
                servitut_id=entry_data.get("servitut_id", ""),
            )
        )
    return entries


def _escape_markdown_cell(value: object) -> str:
    text = str(value or "—")
    text = " ".join(text.splitlines()).strip()
    return text.replace("|", "\\|")


def _build_markdown_table(entries: List[ReportEntry]) -> str:
    header = (
        "| Nr. | Dato/løbenummer | Beskrivelse | Påtaleberettiget | "
        "Rådighed/tilstand | Offentlig/privatretlig | Håndtering/Handling | Vedrører projektområdet |"
    )
    separator = "|-----|-----------------|-------------|------------------|-------------------|------------------------|---------------------|------------------------|"
    rows = [
        "| "
        + " | ".join(
            [
                _escape_markdown_cell(entry.nr),
                _escape_markdown_cell(entry.date_reference),
                _escape_markdown_cell(entry.description),
                _escape_markdown_cell(entry.beneficiary),
                _escape_markdown_cell(entry.disposition),
                _escape_markdown_cell(entry.legal_type),
                _escape_markdown_cell(entry.action),
                _escape_markdown_cell(entry.scope_detail or entry.scope),
            ]
        )
        + " |"
        for entry in entries
    ]
    return "\n".join([header, separator] + rows)


def generate_report(
    servitutter: List[Servitut],
    all_chunks: List[Chunk],
    case_id: str,
    target_matrikler: Optional[List[str]] = None,
    available_matrikler: Optional[List[str]] = None,
    as_of_date: Optional[date] = None,
) -> Report:
    """Generate a structured report from extracted servitutter."""
    report_id = generate_report_id()
    prompt_template = _load_prompt()
    target_matrikler = target_matrikler or []
    available_matrikler = available_matrikler or []
    dated_servitutter = _filter_servitutter_by_as_of_date(servitutter, as_of_date)
    filtered_servitutter = filter_servitutter_for_target(
        dated_servitutter,
        target_matrikler,
        available_matrikler,
    )

    servitutter_json = json.dumps(
        [s.model_dump() for s in filtered_servitutter],
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    evidence_text = _build_evidence_text(filtered_servitutter, all_chunks)

    prompt = prompt_template.replace("{servitutter_json}", servitutter_json)
    prompt = prompt.replace("{evidence_text}", evidence_text)
    prompt = prompt.replace(
        "{target_matrikler_json}",
        json.dumps(target_matrikler, ensure_ascii=False),
    )
    prompt = prompt.replace(
        "{all_matrikler_json}",
        json.dumps(available_matrikler, ensure_ascii=False),
    )
    prompt = prompt.replace(
        "{as_of_date}",
        as_of_date.isoformat() if as_of_date else "ingen datoafgrænsning",
    )

    markdown_content: Optional[str] = None
    entries: List[ReportEntry] = []
    notes: Optional[str] = None

    try:
        response_text = generate_text(
            prompt,
            max_tokens=8192,
            provider=_resolve_report_provider(),
            model=_resolve_report_model(),
        ).strip()
        data = _extract_json_object(response_text)
        notes = data.get("notes")
        entries = _build_report_entries(data.get("entries", []))
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        # Fallback: build basic entries from servitutter
        for i, srv in enumerate(filtered_servitutter, 1):
            scope = (
                "Ja" if srv.applies_to_target_matrikel is True
                else "Nej" if srv.applies_to_target_matrikel is False
                else "Måske"
            )
            matching = resolve_matching_target_matrikler(srv.applies_to_matrikler, target_matrikler)
            scope_detail = f"Vedr. matr.nr. {' og '.join(matching)}" if matching else None
            entries.append(
                ReportEntry(
                    nr=i,
                    date_reference=srv.date_reference,
                    description=srv.summary,
                    beneficiary=srv.beneficiary,
                    disposition=srv.disposition_type,
                    legal_type=srv.legal_type,
                    action=srv.action_note,
                    relevant_for_project=srv.applies_to_target_matrikel is True,
                    scope=scope,
                    scope_detail=scope_detail,
                    servitut_id=srv.servitut_id,
                )
            )

    markdown_content = _build_markdown_table(entries) if entries else None

    report = Report(
        report_id=report_id,
        case_id=case_id,
        as_of_date=as_of_date,
        target_matrikler=target_matrikler,
        available_matrikler=available_matrikler,
        servitutter=entries,
        notes=notes,
        markdown_content=markdown_content,
    )
    return report
