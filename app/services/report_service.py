from datetime import date, datetime
import json
import re
from typing import List, Optional

from sqlmodel import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.chunk import Chunk
from app.models.report import Report, ReportEntry
from app.models.servitut import Servitut
from app.services.llm_service import generate_text
from app.services.report_render_service import build_markdown_table
from app.services.matrikel_service import filter_servitutter_for_target, resolve_matching_target_matrikler
from app.services import storage_service
from app.utils.ids import generate_report_id

logger = get_logger(__name__)


def _resolve_report_provider() -> str | None:
    if settings.REPORT_LLM_PROVIDER.strip():
        return settings.REPORT_LLM_PROVIDER.strip()
    return None


def _load_prompt() -> str:
    prompt_path = settings.prompts_path / "generate_report.txt"
    return prompt_path.read_text(encoding="utf-8")



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
                title=entry_data.get("title"),
                byggeri_markering=entry_data.get("byggeri_markering"),
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


_AMT_REGEX = re.compile(r'\bamt\b', re.IGNORECASE)


def _parse_date_reference(date_ref: Optional[str]) -> date:
    """Returnerer date.max for None/ugyldige datoer → sorteres sidst."""
    if not date_ref:
        return date.max
    try:
        return datetime.strptime(date_ref[:10], "%d.%m.%Y").date()
    except ValueError:
        return date.max


def _dedup_servitutter(servitutter: List[Servitut]) -> List[Servitut]:
    """Fjern dubletter på date_reference (beholder første). None-keys deduplikeres aldrig."""
    seen: dict[str, str] = {}
    unique: List[Servitut] = []
    for srv in servitutter:
        if srv.date_reference is None:
            unique.append(srv)
            continue
        if srv.date_reference not in seen:
            seen[srv.date_reference] = srv.servitut_id
            unique.append(srv)
        else:
            logger.warning(
                f"Dedup: fjerner dublet {srv.servitut_id!r} "
                f"(date_reference={srv.date_reference!r}, beholder={seen[srv.date_reference]!r})"
            )
    return unique


def _apply_empty_field_fallbacks(entry: ReportEntry) -> ReportEntry:
    updates: dict = {}
    desc = (entry.description or "").strip()
    if not desc:
        updates["description"] = (
            "Ukendt indhold"
            if (entry.raw_text or "").strip()
            else "Akt ikke gennemgået."
        )
    if not (entry.action or "").strip():
        updates["action"] = "Kræver opslag i tingbogsakt"
    if _AMT_REGEX.search(entry.beneficiary or ""):
        updates["beneficiary_amt_warning"] = True
    return entry.model_copy(update=updates) if updates else entry


def generate_report(
    session: Session,
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
    filtered_servitutter = _dedup_servitutter(filtered_servitutter)
    filtered_servitutter = sorted(filtered_servitutter, key=lambda s: _parse_date_reference(s.date_reference))

    _REPORT_FIELDS = {
        "servitut_id", "date_reference", "title", "summary", "beneficiary",
        "disposition_type", "legal_type", "action_note", "byggeri_markering",
        "applies_to_target_matrikel", "applies_to_matrikler", "registered_at",
    }
    servitutter_json = json.dumps(
        [
            {k: v for k, v in s.model_dump(mode="json").items() if k in _REPORT_FIELDS}
            for s in filtered_servitutter
        ],
        ensure_ascii=False,
        indent=2,
    )

    prompt = prompt_template.replace("{servitutter_json}", servitutter_json)
    prompt = prompt.replace("{evidence_text}", "")
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

    attest_doc_ids = {
        d.document_id
        for d in storage_service.list_documents(session, case_id)
        if d.document_type == "tinglysningsattest"
    }

    # Build lookup dicts for enrichment (used in both LLM and fallback paths)
    srv_by_id = {s.servitut_id: s for s in filtered_servitutter}
    srv_by_date = {s.date_reference: s for s in filtered_servitutter}

    def _lookup_srv(servitut_id: str, date_reference: Optional[str]) -> Optional[Servitut]:
        return srv_by_id.get(servitut_id) or srv_by_date.get(date_reference)

    def _akt_raw_text(srv: Servitut) -> Optional[str]:
        akt_ev = [ev for ev in (srv.evidence or []) if ev.document_id not in attest_doc_ids]
        return akt_ev[0].text_excerpt[:500] if akt_ev else None

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
        raw_entries = _build_report_entries(data.get("entries", []))
        entries = []
        for entry in raw_entries:
            srv = _lookup_srv(entry.servitut_id, entry.date_reference)
            updates = {}
            if srv:
                if not entry.description or entry.description.strip() in ("—", "-", ""):
                    if srv.title:
                        updates["description"] = f"Ingen aktindhold tilgængeligt — {srv.title}"
                raw_text = _akt_raw_text(srv)
                if raw_text:
                    updates["raw_text"] = raw_text
            enriched = entry.model_copy(update=updates) if updates else entry
            entries.append(_apply_empty_field_fallbacks(enriched))
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
            entries.append(_apply_empty_field_fallbacks(
                ReportEntry(
                    nr=i,
                    date_reference=srv.date_reference,
                    title=srv.title,
                    byggeri_markering=srv.byggeri_markering,
                    raw_text=_akt_raw_text(srv),
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
            ))

    entries = sorted(entries, key=lambda e: _parse_date_reference(e.date_reference))
    entries = [e.model_copy(update={"nr": i}) for i, e in enumerate(entries, 1)]

    markdown_content = build_markdown_table(entries) if entries else None

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
