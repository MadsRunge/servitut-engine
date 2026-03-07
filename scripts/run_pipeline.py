"""
Kør hele pipeline end-to-end på én akt-PDF med DeepSeek (eller Anthropic).

Pipeline: PDF → OCR → Chunks → Extraction (LLM) → Report (LLM)

Kør:
  uv run python scripts/run_pipeline.py [sti-til-pdf]

Eksempel:
  uv run python scripts/run_pipeline.py docs/sample_cases/40_C_164_indskannetakt.pdf
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.services.chunking_service import chunk_pages
from app.services.extraction_service import extract_servitutter
from app.services.ocr_service import process_document
from app.services.report_service import generate_report

OUTPUT_DIR = Path("/tmp/pipeline_eval")


def hr(char="=", width=70):
    print(char * width)


def main():
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = Path("docs/sample_cases/40_C_164_indskannetakt.pdf")

    if not pdf_path.exists():
        print(f"Fil ikke fundet: {pdf_path}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc_id = pdf_path.stem.replace(" ", "_")
    case_id = f"eval-{doc_id[:20]}"
    ocr_pdf_path = OUTPUT_DIR / f"{doc_id}_ocr.pdf"

    hr()
    print(f"SERVITUT ENGINE — end-to-end pipeline")
    hr()
    print(f"Dokument  : {pdf_path.name}")
    print(f"Case ID   : {case_id}")
    print(f"Provider  : {settings.LLM_PROVIDER}  |  Model: {settings.MODEL}")
    hr()

    # --- TRIN 1: OCR ---
    print("\n[1/4] OCR (ocrmypdf + pdfplumber)...")
    pages = process_document(pdf_path, doc_id, case_id, ocr_pdf_path)
    ok = [p for p in pages if p.confidence >= 0.4]
    blank = [p for p in pages if p.confidence == 0.0]
    print(f"     {len(pages)} sider | {len(ok)} ok | {len(blank)} blanke")
    print(f"     OCR PDF: {ocr_pdf_path}")

    # --- TRIN 2: CHUNKING ---
    print("\n[2/4] Chunking...")
    chunks = chunk_pages(pages, doc_id, case_id)
    print(f"     {len(chunks)} chunks oprettet")

    # --- TRIN 3: EXTRACTION (LLM #1) ---
    print("\n[3/4] Extraction via LLM...")
    servitutter = extract_servitutter(chunks, case_id)
    print(f"     {len(servitutter)} servitutter fundet")
    for i, srv in enumerate(servitutter, 1):
        print(f"     [{i}] {srv.title or '(uden titel)'} — conf={srv.confidence:.2f}")

    if not servitutter:
        print("\n     Ingen servitutter fundet — pipeline stopper her.")
        sys.exit(0)

    # --- TRIN 4: REPORT (LLM #2) ---
    print("\n[4/4] Rapport-generering via LLM...")
    report = generate_report(servitutter, chunks, case_id)
    print(f"     Report ID: {report.report_id}")
    print(f"     Entries  : {len(report.servitutter)}")

    # --- OUTPUT ---
    hr()
    print("\nSERVITUTREDEGORELSE — MARKDOWN TABEL\n")
    if report.markdown_content:
        print(report.markdown_content)
    else:
        print("(Ingen markdown tabel genereret — se entries nedenfor)")

    if report.notes:
        print(f"\nNoter: {report.notes}")

    hr("-")
    print("\nSTRUKTUREREDE ENTRIES:")
    for entry in report.servitutter:
        print(f"\n  Nr. {entry.nr}: {entry.description or '—'}")
        print(f"    Dato/ref     : {entry.date_reference or '—'}")
        print(f"    Påtaleberettig: {entry.beneficiary or '—'}")
        print(f"    Disposition  : {entry.disposition or '—'}")
        print(f"    Retlig type  : {entry.legal_type or '—'}")
        print(f"    Handling     : {entry.action or '—'}")
        print(f"    Projekt-rel. : {'Ja' if entry.relevant_for_project else 'Nej'}")

    # Gem til inspektion
    report_out = OUTPUT_DIR / f"{doc_id}_report.json"
    servitut_out = OUTPUT_DIR / f"{doc_id}_servitutter.json"
    report_out.write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    servitut_out.write_text(
        json.dumps([s.model_dump() for s in servitutter], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    hr()
    print(f"\nGemt til inspektion:")
    print(f"  Rapport    : {report_out}")
    print(f"  Servitutter: {servitut_out}")
    print(f"  OCR PDF    : {ocr_pdf_path}")


if __name__ == "__main__":
    main()
