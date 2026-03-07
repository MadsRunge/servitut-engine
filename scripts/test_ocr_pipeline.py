"""
Test OCR pipeline end-to-end uden LLM.

Kører: PDF → sidebilleder (pymupdf) → Tesseract OCR → chunks
Printer evalueringsrapport pr. dokument og pr. side.

Kør: uv run python scripts/test_ocr_pipeline.py
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.chunking_service import chunk_pages
from app.services.ocr_service import process_document
from app.utils.text import has_servitut_keywords

SAMPLE_DIR = Path("docs/sample_cases")
OUTPUT_DIR = Path("/tmp/ocr_eval")

# Dansk-relevante servitut-keywords til pre-screening evaluering
SERVITUT_KEYWORDS = [
    "servitut", "deklaration", "tinglysnin", "byrde", "rettighed",
    "påtaleberettig", "vejret", "byggelinier", "byggeservitut",
    "adgangsret", "færdselsret", "hegn", "ledning", "kloakledning",
]


def highlight_keywords(text: str, max_len: int = 300) -> str:
    """Returner de første max_len tegn med keyword-match markeret."""
    lower = text.lower()
    for kw in SERVITUT_KEYWORDS:
        if kw in lower:
            idx = lower.index(kw)
            start = max(0, idx - 60)
            snippet = text[start:start + max_len]
            return f"...{snippet}..."
    return text[:max_len]


def evaluate_document(pdf_path: Path, output_dir: Path) -> dict:
    doc_id = pdf_path.stem.replace(" ", "_")
    images_dir = output_dir / "page_images" / doc_id

    print(f"\n{'='*70}")
    print(f"Dokument: {pdf_path.name}")
    print(f"{'='*70}")

    pages = process_document(pdf_path, doc_id, "eval-case", images_dir)
    chunks = chunk_pages(pages, doc_id, "eval-case")

    # --- Side-statistik ---
    total_chars = sum(len(p.text) for p in pages)
    blank_pages = [p for p in pages if p.confidence == 0.0]
    low_conf_pages = [p for p in pages if 0.0 < p.confidence < 0.5]
    ok_pages = [p for p in pages if p.confidence >= 0.5]
    mean_conf = (
        sum(p.confidence for p in pages if p.confidence > 0) / len(ok_pages)
        if ok_pages else 0.0
    )

    print(f"\nSIDER: {len(pages)} total | {len(ok_pages)} ok | "
          f"{len(low_conf_pages)} lav conf | {len(blank_pages)} blanke")
    print(f"Gns. confidence (ikke-blanke): {mean_conf:.2f}")
    print(f"Total tekst: {total_chars:,} tegn")
    print(f"Chunks: {len(chunks)}")

    # --- Chunks med servitut-keywords ---
    keyword_chunks = [c for c in chunks if has_servitut_keywords(c.text, threshold=1)]
    print(f"\nChunks med servitut-keywords: {len(keyword_chunks)}/{len(chunks)}")

    if keyword_chunks:
        print("\nTOP keyword-chunks:")
        for i, chunk in enumerate(keyword_chunks[:5], 1):
            snippet = highlight_keywords(chunk.text)
            print(f"  [{i}] Side {chunk.page} | Chunk {chunk.chunk_index} | {len(chunk.text)} tegn")
            print(f"      \"{snippet}\"")

    # --- Lav-confidence sider ---
    if low_conf_pages:
        print(f"\nLAV-CONFIDENCE sider (0.0 < conf < 0.5):")
        for p in low_conf_pages[:5]:
            print(f"  Side {p.page_number}: conf={p.confidence:.2f} | {len(p.text)} tegn")
            if p.text:
                print(f"    \"{p.text[:100]}\"")

    # Gem OCR-output til JSON for inspektion
    out_path = output_dir / f"{doc_id}_pages.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            [p.model_dump() for p in pages],
            f,
            ensure_ascii=False,
            indent=2,
        )

    chunks_path = output_dir / f"{doc_id}_chunks.json"
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(
            [c.model_dump() for c in chunks],
            f,
            ensure_ascii=False,
            indent=2,
        )

    return {
        "filename": pdf_path.name,
        "pages": len(pages),
        "blank_pages": len(blank_pages),
        "low_conf_pages": len(low_conf_pages),
        "mean_conf": round(mean_conf, 2),
        "total_chars": total_chars,
        "chunks": len(chunks),
        "keyword_chunks": len(keyword_chunks),
    }


def main():
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    pdfs = sorted(SAMPLE_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"Ingen PDF'er fundet i {SAMPLE_DIR}")
        sys.exit(1)

    print(f"Fandt {len(pdfs)} PDF'er — starter OCR pipeline...\n")

    results = []
    for pdf in pdfs:
        result = evaluate_document(pdf, OUTPUT_DIR)
        results.append(result)

    # --- Samlet opsummering ---
    print(f"\n\n{'='*70}")
    print("SAMLET EVALUERING")
    print(f"{'='*70}")
    print(f"{'Fil':<40} {'Sider':>6} {'Blanke':>7} {'Gns.conf':>9} {'Tegn':>8} {'Chunks':>7} {'KW-hits':>8}")
    print("-" * 70)
    for r in results:
        name = r["filename"][:38]
        print(
            f"{name:<40} {r['pages']:>6} {r['blank_pages']:>7} "
            f"{r['mean_conf']:>9.2f} {r['total_chars']:>8,} "
            f"{r['chunks']:>7} {r['keyword_chunks']:>8}"
        )

    print(f"\nOCR-output gemt i: {OUTPUT_DIR}/")
    print("Inspicér sider: <doc>_pages.json | Inspicér chunks: <doc>_chunks.json")


if __name__ == "__main__":
    main()
