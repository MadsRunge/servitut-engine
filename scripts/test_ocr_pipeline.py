"""
Test OCR pipeline end-to-end uden LLM på én akt-PDF.

Pipeline: original.pdf → ocrmypdf → ocr.pdf → pdfplumber → chunks

Kør: uv run python scripts/test_ocr_pipeline.py [sti-til-pdf]

Eksempel:
  uv run python scripts/test_ocr_pipeline.py docs/sample_cases/40_C_164_indskannetakt.pdf
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.chunking_service import chunk_pages
from app.services.ocr_service import process_document
from app.utils.text import has_servitut_keywords

OUTPUT_DIR = Path("/tmp/ocr_eval")

SERVITUT_KEYWORDS = [
    "servitut", "deklaration", "tinglysnin", "byrde", "rettighed",
    "påtaleberettig", "vejret", "byggelinier", "byggeservitut",
    "adgangsret", "færdselsret", "hegn", "ledning",
]


def highlight_keywords(text: str, max_len: int = 300) -> str:
    lower = text.lower()
    for kw in SERVITUT_KEYWORDS:
        if kw in lower:
            idx = lower.index(kw)
            start = max(0, idx - 60)
            return f"...{text[start:start + max_len]}..."
    return text[:max_len]


def main():
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        # Fallback til den mindste akt som default
        pdf_path = Path("docs/sample_cases/40_C_164_indskannetakt.pdf")

    if not pdf_path.exists():
        print(f"Fil ikke fundet: {pdf_path}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc_id = pdf_path.stem.replace(" ", "_")
    ocr_pdf_path = OUTPUT_DIR / f"{doc_id}_ocr.pdf"

    print(f"Dokument : {pdf_path.name}")
    print(f"OCR-output: {ocr_pdf_path}")
    print(f"{'='*70}")

    pages = process_document(pdf_path, doc_id, "eval-case", ocr_pdf_path)
    chunks = chunk_pages(pages, doc_id, "eval-case")

    # --- Side-statistik ---
    blank = [p for p in pages if p.confidence == 0.0]
    low   = [p for p in pages if 0.0 < p.confidence < 0.4]
    ok    = [p for p in pages if p.confidence >= 0.4]
    mean_conf = sum(p.confidence for p in ok) / len(ok) if ok else 0.0
    total_chars = sum(len(p.text) for p in pages)

    print(f"\nSIDER: {len(pages)} total | {len(ok)} ok | {len(low)} lav conf | {len(blank)} blanke")
    print(f"Gns. confidence (ikke-blanke): {mean_conf:.2f}")
    print(f"Total tekst: {total_chars:,} tegn | Chunks: {len(chunks)}")

    # --- Lav-confidence sider ---
    if low:
        print(f"\nLAV-CONFIDENCE sider:")
        for p in low:
            print(f"  Side {p.page_number}: conf={p.confidence:.2f} | {len(p.text)} tegn")
            if p.text:
                print(f"    \"{p.text[:120]}\"")

    # --- Chunks med servitut-keywords ---
    kw_chunks = [c for c in chunks if has_servitut_keywords(c.text, threshold=1)]
    print(f"\nChunks med servitut-keywords: {len(kw_chunks)}/{len(chunks)}")

    if kw_chunks:
        print("\nTOP keyword-chunks:")
        for i, chunk in enumerate(kw_chunks[:8], 1):
            snippet = highlight_keywords(chunk.text)
            print(f"\n  [{i}] Side {chunk.page} | Chunk {chunk.chunk_index} | {len(chunk.text)} tegn")
            print(f"      \"{snippet}\"")

    # --- Alle sider ---
    print(f"\n{'='*70}")
    print("ALLE SIDER:")
    for p in pages:
        marker = "✓" if p.confidence >= 0.7 else "~" if p.confidence > 0.0 else "∅"
        print(f"  {marker} Side {p.page_number:>3} | conf={p.confidence:.2f} | {len(p.text):>5} tegn")

    # Gem til inspektion
    pages_out = OUTPUT_DIR / f"{doc_id}_pages.json"
    chunks_out = OUTPUT_DIR / f"{doc_id}_chunks.json"
    pages_out.write_text(
        json.dumps([p.model_dump() for p in pages], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    chunks_out.write_text(
        json.dumps([c.model_dump() for c in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nGemt til inspektion:")
    print(f"  Sider : {pages_out}")
    print(f"  Chunks: {chunks_out}")
    print(f"  OCR PDF: {ocr_pdf_path}")


if __name__ == "__main__":
    main()
