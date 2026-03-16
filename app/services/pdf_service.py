from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class PdfPageRange:
    start_page: int
    end_page: int
    label: str | None = None


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("pymupdf ikke installeret. Kør: uv sync") from exc

    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return pdf.page_count
    finally:
        pdf.close()


def build_split_suggestion(total_pages: int, pages_per_part: int = 100) -> str:
    if total_pages < 1:
        raise ValueError("PDF'en skal have mindst én side")
    if pages_per_part < 1:
        raise ValueError("Sider pr. del skal være mindst 1")

    lines: list[str] = []
    start_page = 1
    part_number = 1
    while start_page <= total_pages:
        end_page = min(start_page + pages_per_part - 1, total_pages)
        lines.append(f"{start_page}-{end_page} | Del {part_number}")
        start_page = end_page + 1
        part_number += 1
    return "\n".join(lines)


def parse_page_ranges(spec: str, total_pages: int) -> list[PdfPageRange]:
    if total_pages < 1:
        raise ValueError("PDF'en skal have mindst én side")
    if not spec.strip():
        raise ValueError("Angiv mindst ét sideinterval")

    ranges: list[PdfPageRange] = []
    for line_number, raw_line in enumerate(spec.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        interval_text, _, label_text = line.partition("|")
        interval = interval_text.strip()
        if not interval:
            raise ValueError(f"Linje {line_number}: mangler sideinterval")

        if "-" in interval:
            start_text, end_text = (part.strip() for part in interval.split("-", maxsplit=1))
        else:
            start_text = interval
            end_text = interval

        try:
            start_page = int(start_text)
            end_page = int(end_text)
        except ValueError as exc:
            raise ValueError(f"Linje {line_number}: ugyldigt sideinterval '{interval}'") from exc

        if start_page < 1 or end_page < 1:
            raise ValueError(f"Linje {line_number}: sidetal skal starte ved 1")
        if start_page > end_page:
            raise ValueError(f"Linje {line_number}: startside må ikke være større end slutside")
        if end_page > total_pages:
            raise ValueError(
                f"Linje {line_number}: side {end_page} findes ikke i PDF'en ({total_pages} sider)"
            )

        label = label_text.strip() or None
        ranges.append(PdfPageRange(start_page=start_page, end_page=end_page, label=label))

    if not ranges:
        raise ValueError("Angiv mindst ét gyldigt sideinterval")

    sorted_ranges = sorted(ranges, key=lambda page_range: (page_range.start_page, page_range.end_page))
    previous_end = 0
    for page_range in sorted_ranges:
        if page_range.start_page <= previous_end:
            raise ValueError("Sideintervaller må ikke overlappe")
        previous_end = page_range.end_page

    return ranges


def split_pdf_bytes(
    pdf_bytes: bytes,
    ranges: list[PdfPageRange],
    original_filename: str,
) -> list[tuple[str, bytes]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("pymupdf ikke installeret. Kør: uv sync") from exc

    source_pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        base_name = Path(original_filename or "document.pdf").stem or "document"
        outputs: list[tuple[str, bytes]] = []
        for index, page_range in enumerate(ranges, start=1):
            part_pdf = fitz.open()
            try:
                part_pdf.insert_pdf(
                    source_pdf,
                    from_page=page_range.start_page - 1,
                    to_page=page_range.end_page - 1,
                )
                label = _resolve_part_label(page_range, index)
                part_filename = f"{base_name}_{label}.pdf"
                outputs.append((part_filename, part_pdf.tobytes(garbage=3, deflate=True)))
            finally:
                part_pdf.close()
        return outputs
    finally:
        source_pdf.close()


def _resolve_part_label(page_range: PdfPageRange, index: int) -> str:
    if page_range.label:
        normalized = _normalize_filename_component(page_range.label)
        if normalized:
            return normalized
    return f"del-{index:02d}_p{page_range.start_page}-{page_range.end_page}"


def _normalize_filename_component(value: str) -> str:
    normalized = re.sub(r"\s+", "_", value.strip())
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "-", normalized)
    normalized = normalized.strip("._-")
    return normalized or "del"
