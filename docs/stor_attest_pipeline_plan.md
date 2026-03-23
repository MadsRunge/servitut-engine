# Plan for stor tinglysningsattest-pipeline

## Baggrund
Den nuvaerende attest-pipeline bryder sammen paa meget store sager. I den konkrete sag havde brugeren:
- ca. 10.000 OCR-sider samlet
- en tinglysningsattest paa ca. 140 sider

OCR kunne gennemfoeres, men canonical extraction fra attesten fejlede i praksis, fordi hele attesten ender som et enkelt stort LLM-kald.

## Hvad den nuvaerende loesning goer
I dag sker attest-udtraek saadan:
1. OCR-sider chunkes til `Chunk`-objekter.
2. `extract_canonical_from_attest()` samler alle attest-chunks pr. dokument.
3. `_extract_from_doc_chunks(..., source_type="tinglysningsattest")` kalder `_extract_document_servitutter()`.
4. `_extract_document_servitutter()` bygger et samlet `chunks_text` ved at concatenere alle chunks for dokumentet.
5. Hele teksten sendes ind i prompten `extract_tinglysningsattest.txt` som ét LLM-kald.

Det virker for mindre attester, men ikke for meget store attester. Fejlen er derfor arkitektonisk, ikke bare en prompt-tuning-fejl.

## Kernen i den nye loesning
Attest-ekstraktion skal deles i to trin:

### Trin A: deterministisk segmentering og indexering
Maalet er ikke fuld juridisk forstaaelse, men at opdele attesten i mindre, stabile enheder.

Output:
- `attest_sections` eller tilsvarende segmenter pr. case/doc
- sideintervaller
- raatekst pr. segment
- lette metadata, fx:
  - segment_type
  - mulig date_reference
  - mulig archive_number
  - mulig titeltekst
  - fundne matrikelreferencer

Segmentering skal vaere regelbaseret og resumable. Hvis en attest har 140 sider, skal systemet kunne gemme et mellemresultat efter segmenteringen.

### Trin B: targeted LLM extraction paa mindre segmenter
LLM skal kun kaldes paa mindre tekstvinduer eller konkrete attestposter, ikke paa hele dokumentet.

Output:
- canonical servitutliste som i dag
- men nu bygget fra mange mindre extraction-units
- merge/dedup bagefter

## Anbefalet implementering

## Fase 1: nyt attest-index-lag
Indfoer et nyt backend-lag, fx:
- `AttestSegment`
- eller et JSONB-baseret `attest_index` pr. dokument/case

Hvert segment boer mindst have:
- `segment_id`
- `case_id`
- `document_id`
- `page_start`
- `page_end`
- `text`
- `heading`
- `candidate_date_reference`
- `candidate_archive_number`
- `candidate_title`
- `raw_scope_text`
- `raw_parcel_references`
- `extraction_status`

Foerste version behoever ikke ny relationel tabel, hvis JSONB paa case/document er hurtigere at lande. Men segmenter maa ikke kun leve i memory.

## Fase 2: deterministisk segmentering
Byg en segmenter, der arbejder direkte paa OCR-siderne for attest-dokumenter.

Regelideer:
- split paa tydelige loebenumre / dato-loebenummer-formater
- split paa linjer med aktnummer
- split paa tabel-lignende poster
- fasthold sideintervaller
- tillad overlap mellem segmenter, hvis en post gaar over sidebrud

Vigtigt:
- hellere for mange segmenter end for faa
- segmenter maa gerne markeres som `uafklarede`, hvis parseren ikke er sikker
- hver side skal ende i mindst ét segment, saa vi undgaar "tabte" attestdele

## Fase 3: targeted extraction-service
Tilfoej en ny attest-specifik extraction-path, fx:
- `extract_canonical_from_attest_indexed()`

Flow:
1. load eller byg attest-index
2. koer LLM extraction pr. segment eller lille segment-batch
3. parse resultater til foreloebige canonical items
4. merge paa `date_reference`, `archive_number` og tekstnaere signaler
5. producer endelig canonical liste

Segment-batching:
- start med 1 segment pr. kald for robusthed
- tillad senere batching af 2-5 segmenter, hvis samlet tegnmaengde er under et sikkert loft

## Fase 4: merge og kvalitetssikring
Efter segmentvis extraction skal backend merge resultaterne deterministisk.

Regler:
- `date_reference` er primaer noegle naar tilgaengelig
- `archive_number` er sekundaer noegle
- ellers tekstnaer fallback paa titel + sideinterval

Hvert canonical item boer gemme proveniens:
- hvilke segmenter det kom fra
- hvilke sider det bygger paa
- confidence paa merge

## Fase 5: progress og resume
Store attester maa kunne koeres som en robust pipeline, ikke et alt-eller-intet kald.

Tilfoej progress-events for:
- `segmenting_attest`
- `extracting_attest_segment`
- `merging_attest_segments`

Ved fejl skal vi kunne:
- genkoere kun fejlede segmenter
- genbruge eksisterende attest-index
- genbruge allerede lykkede segment-extractions

## API- og storage-konsekvenser
Det nuvaerende `canonical_list` paa `Case` kan bevares som slutprodukt.
Det nye er mellemleddene:
- attest-index
- segment-extraction-status
- eventuelt segment-resultater

Minimal pragmatisk version:
- behold `canonical_list` som cache
- tilfoej `attest_index` og evt. `attest_extraction_runs`

## Streamlit og senere Next.js
Streamlit kan faa stor nytte af dette i debug/review:
- vis antal segmenter
- vis hvilke sider der tilhoerer hvilke segmenter
- vis hvilke segmenter der fejlede

Next.js behoever ikke vise hele maskinrummet, men boer kunne vise:
- at stor attest behandles i batches
- at extraction stadig er i gang
- at pipeline kan genoptages

## Konkrete kodepunkter der sandsynligvis skal aendres
- `app/services/extraction_service.py`
  - ny attest-specifik indexed path
- `app/services/extraction/llm_extractor.py`
  - stop med at sende hele attest-dokumenter som ét `chunks_text`
- `prompts/extract_tinglysningsattest.txt`
  - justeres til segment-niveau frem for "hele attesten"
- `app/services/storage_service.py`
  - persistens for attest-index / segmentstatus
- evt. nye modeller i `app/models/` og `app/db/models.py`

## MVP-afgraensning
Foerste version boer levere dette og ikke mere:
- deterministisk attest-segmentering
- segmentvis canonical extraction
- merge til eksisterende canonical liste
- resume ved delvise fejl
- progress-events

Foerste version boer ikke omfatte:
- ny eksport
- ny UI-editor
- avanceret parallel scheduler
- semantisk retrieval over hele attesten

## Success-kriterier
Loesningen er god nok, naar:
- en attest paa 100+ sider kan behandles uden at samle alt i ét prompt-kald
- extraction kan genoptages efter delvise fejl
- canonical liste stadig bliver komplet nok til downstream chunk-scoring og enrichment
- brugeren oplever "langsommere men robust", ikke "umuligt"

