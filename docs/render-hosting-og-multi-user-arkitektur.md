# Render hosting og multi-user arkitektur

## Formaal

Dette dokument beskriver den anbefalede hostingstrategi for Servitut Engine paa Render og den bedste vej til at goere projektet multi-user, saa hver bruger faar isoleret data og sager.

Det tager udgangspunkt i den nuvaerende kodebase, hvor:

- Streamlit-UI'en kalder services direkte i Python
- runtime-data gemmes lokalt under `storage/cases`
- OCR koeres via `ocrmypdf`
- der endnu ikke findes auth, brugerbegreb eller ejerforhold paa sager

Relevante kodepunkter:

- `streamlit_app/Home.py`
- `streamlit_app/pages/3_Run_OCR.py`
- `streamlit_app/pages/7_Extract_Servitutter.py`
- `app/services/storage_service.py`
- `app/services/ocr_service.py`
- `app/api/main.py`

## Konklusion

Den bedste kortsigtede loesning er:

- deploy paa Render som en enkelt Docker-baseret web service
- koer Streamlit som den offentlige app
- mount en persistent disk til runtime-data
- behold lokal artifact-cache til OCR, sider, chunks og rapporter

Den bedste langsigtede multi-user loesning er:

- auth + brugeridentitet
- ejerskab paa sager og dokumenter
- metadata i Postgres
- filer og OCR-artefakter i objektstorage
- OCR og extraction som baggrundsjob i worker-service

## Hvorfor Render passer til den nuvaerende arkitektur

Projektet er stateful i dag. Streamlit-siderne taler ikke med en separat hostet backend som primaer vej; de importer direkte service-laget og laeser/skriver filer lokalt. Det betyder:

- UI og business logic forventer delt lokal adgang til `storage/`
- OCR-run producerer flere afledte filer pr. dokument
- reruns og cache afhænger af at tidligere artefakter stadig findes paa disk
- `ocrmypdf` kraever systempakker og CPU-tid

Det peger paa en container med persistent disk, ikke en stateless hostingmodel.

## Anbefalet v1 paa Render

### Setup

Koer appen som en enkelt Render web service med Docker:

- expose kun Streamlit udadtil
- mount persistent disk, fx paa `/app/storage`
- saet `STORAGE_DIR=/app/storage`
- start appen med Streamlit paa Render-porten

Eksempel paa startkommando:

```bash
streamlit run streamlit_app/Home.py --server.port $PORT --server.address 0.0.0.0
```

### Systemafhaengigheder

Containeren skal installere de pakker, som `ocrmypdf` typisk forventer:

- `tesseract-ocr`
- `tesseract-ocr-dan`
- `tesseract-ocr-eng`
- `ghostscript`
- `qpdf`
- eventuelt billedvaerktoejer, hvis OCR-pipelinen senere kraever det

### Miljoevariabler

Mindst disse env vars boer saettes i Render:

```env
STORAGE_DIR=/app/storage
PROMPTS_DIR=/app/prompts
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
MODEL=claude-sonnet-4-6
OCR_LANGUAGE=dan+eng
OCR_DESKEW=true
OCR_JOBS=2
```

`OCR_JOBS` boer vaelges konservativt i cloud-drift, saa OCR ikke laaser hele instansen for andre brugere.

### Hvad denne model giver dig

- hurtig vej til en fungerende offentlig version
- minimal refaktorering af nuvaerende kode
- reuse af eksisterende OCR/cache-flow
- enkel drift og enkel fejlfinding

### Hvad denne model ikke loeser

- ingen rigtig brugerisolering endnu
- lange OCR-job koerer i samme procesmiljoe som UI
- en travl bruger kan paavirke alle andre brugere
- lokal disk som primaer storage er ikke en god langsigtet SaaS-model

## Multi-user paa nuvaerende filstorage

Hvis du vil have flere brugere hurtigt uden at lave hele platformen om, er den mest pragmatiske model:

- tilfoej auth
- tilfoej `owner_user_id` paa `Case`
- laeg sager under bruger-separerede stier
- filtrer alle opslag paa aktiv bruger

### Foreslaaet datamodelekspansion

Tilfoej mindst disse felter:

#### `Case`

- `owner_user_id: str`
- eventuelt `shared_with_user_ids: list[str]`

#### `Document`

- ingen separat ejer er strengt noedvendig, hvis dokumenter altid tilhoerer en case

### Foreslaaet storage-layout

I stedet for:

```text
storage/cases/{case_id}/...
```

brug:

```text
storage/users/{user_id}/cases/{case_id}/
  case.json
  documents/{doc_id}/original.pdf
  documents/{doc_id}/ocr.pdf
  ocr/{doc_id}_pages.json
  chunks/{doc_id}_chunks.json
  servitutter/{servitut_id}.json
  reports/{report_id}.json
```

### Noedvendige kodeaendringer i denne model

1. Indfoer et brugerbegreb i appen
2. Udvid `Case` med `owner_user_id`
3. Flyt `storage_service` fra global case-root til bruger-root
4. Sikr at `list_cases()` kun returnerer sager for aktiv bruger
5. Sikr at alle load/save-kald verificerer, at casen tilhoerer den aktuelle bruger

### Vigtig sikkerhedsregel

Brug aldrig klient-sendt `user_id` direkte som filsti. Den aktive bruger skal komme fra auth-laget, ikke fra en URL-parameter eller hidden field i Streamlit.

## Auth-anbefaling

Projektet har ikke auth i dag. Hvis flere brugere skal bruge systemet, er auth ikke valgfrit.

Den simpleste vej er:

- ekstern auth-provider
- gem kun det noedvendige bruger-id og email i din egen app
- brug auth-sessionen til at afgore, hvilke sager brugeren maa se

Det vigtigste arkitekturmssigt er ikke hvilken provider du vaelger, men at du faar et stabilt `user_id`, som kan baere ejerskab i hele systemet.

## Anbefalet v2 SaaS-arkitektur

Hvis Servitut Engine skal bruges af flere rigtige kunder, boer du ikke blive paa ren lokal filstorage.

Den anbefalede retning er:

### Komponenter

- Streamlit web service
- API/service-lag
- worker-service til OCR og extraction
- Postgres til metadata
- objektstorage til PDF'er og afledte filer

### Ansvarsfordeling

#### Streamlit

- login
- sagsoversigt
- upload
- statusvisning
- review og rapporter

#### API/service-lag

- opret sager
- opret dokumentmetadata
- opret jobs
- hent brugerens data
- adgangskontrol

#### Worker

- OCR
- sideudtraek
- chunking
- extraction
- rapportgenerering

#### Postgres

- users
- cases
- documents
- jobs
- servitutter
- reports
- audit/statusfelter

#### Objektstorage

- `original.pdf`
- `ocr.pdf`
- page images
- chunks/json-artefakter
- rapportfiler

## Hvorfor denne arkitektur er bedre

- flere brugere kan arbejde samtidigt
- web-requesten bliver ikke blokeret af lange OCR-job
- metadata og adgangskontrol bliver mere robuste
- filer kan versioneres, flyttes og backup'es bedre
- du bliver ikke laast til en enkelt disk paa en enkelt instans

## Anbefalet migrationsplan

### Fase 1

Deploy nuvaerende app paa Render som en enkelt service med persistent disk.

Maal:

- faa en fungerende offentlig beta
- laer driftsbehov, job-varighed og brugeradfaerd

### Fase 2

Tilfoej auth og sagsejerskab paa nuvaerende storage-model.

Maal:

- hver bruger ser kun egne sager
- sager og filer er logisk isoleret

### Fase 3

Flyt metadata til Postgres, men behold eventuelt filerne paa disk i en overgang.

Maal:

- faa robuste relationer mellem bruger, case, dokument og job
- slip for at laese alt fra JSON-filer ved hver operation

### Fase 4

Flyt filer og artefakter til objektstorage og koer OCR/extraction i worker.

Maal:

- skalerbar drift
- bedre fejltaalelighed
- bedre performance under samtidig brug

## Konkret anbefaling til dette projekt

Hvis maalet er "andre skal kunne bruge systemet snart", saa goer dette:

1. Deploy Streamlit paa Render i Docker med persistent disk
2. Installér OCR-systempakker i Dockerfile
3. Tilfoej login
4. Tilfoej `owner_user_id` paa `Case`
5. Flyt storage-layout til `storage/users/{user_id}/cases/{case_id}`

Hvis maalet er "flere virksomheder skal kunne bruge det stabilt", saa planlaeg denne refaktorering:

1. auth
2. Postgres
3. objektstorage
4. worker-jobmodel
5. tydelig separation mellem UI, API og background processing

## Beslutning

Den anbefalede forretningsmaessigt bedste vej er derfor:

- nu: Render + Docker + persistent disk + brugerlogik i appen
- senere: Postgres + objektstorage + worker-arkitektur

Det giver den korteste vej til produktion uden at male projektet op i et hjoerne.
