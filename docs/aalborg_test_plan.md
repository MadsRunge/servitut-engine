# Aalborg Test Plan

## Mål

Køre hele flowet for Aalborg-sagen gennem Next.js-frontenden og bruge backendens observability-filer til at se, hvor tiden faktisk bruges.

## Før test

Sørg for at følgende kører:

```bash
cd /Users/madsrunge/Developer/servitut/servitut-engine
uv run uvicorn app.api.main:app --reload
```

```bash
cd /Users/madsrunge/Developer/servitut/servitut-engine
./scripts/run_worker.sh
```

```bash
cd /Users/madsrunge/Developer/servitut/servitut-frontend
pnpm dev
```

## Flow

1. Log ind i Next.js-frontenden.
2. Opret eller åbn Aalborg-sagen.
3. Upload dokumenterne, hvis de ikke allerede ligger på sagen.
4. Kør OCR.
5. Når OCR er færdig, kør extraction.
6. Gennemgå review-laget, redegørelse og servituterklæring.

## Hvad vi måler

I backend skal vi især se på:

- hvor mange dokumenter der brugte `pdfplumber_direct`
- hvor mange dokumenter der brugte `ocrmypdf`
- hvor mange dokumenter der gik videre til Pas 2 enrichment
- hvor mange candidate chunks der blev sendt videre
- hvor lang tid OCR og extraction tog samlet

## Hvor data ligger

Observability-filer skrives under:

- `storage/cases/<case_id>/observability/ocr/`
- `storage/cases/<case_id>/observability/extraction/`

## Hvad vi vurderer bagefter

- Er flowet stabilt end-to-end på en meget stor sag?
- Er OCR stadig den største flaskehals?
- Hvor stor andel af dokumenterne kunne tage fast path?
- Er Pas 2 kandidatvolumen rimelig, eller skal chunk-selektion strammes yderligere?
- Er kvaliteten af slutproduktet stadig fagligt acceptabel?
