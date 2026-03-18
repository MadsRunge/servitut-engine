# TMV-import: nuværende løsning og vej til Playwright-flow

## Formål

Dette dokument beskriver:

1. Den nuværende løsning i upload-flowet, hvor brugeren selv logger ind på TMV og downloader PDF-filer manuelt.
2. Hvorfor denne løsning har en teknisk grænse.
3. Hvordan projektet kan udvikles til en Playwright-baseret løsning, hvor brugeren stadig logger ind med MitID, men hvor resten af flowet kan automatiseres i samme browser-session.


## Nuværende løsning

### Brugerflow

På upload-siden findes nu et særskilt TMV-flow med tre trin:

1. Brugeren klikker på `Marker download-start`.
2. Brugeren klikker på linket til `https://www.tinglysning.dk/tmv/`.
3. Brugeren logger ind med MitID, slår ejendommen op i TMV og downloader relevante PDF-filer lokalt.
4. Brugeren går tilbage til Servitut Engine og klikker på `Importér nye PDF'er`.
5. Systemet importerer nye PDF-filer fra en lokal mappe direkte ind i den aktive sag.

Flowet er implementeret på upload-siden og kører oven på det eksisterende dokumentbibliotek og den eksisterende dokumentoprettelse.


### Hvad systemet gør teknisk

Den nuværende løsning består af følgende dele:

- `streamlit_app/pages/2_Upload_Documents.py`
  - Viser TMV-sektionen på upload-siden.
  - Gemmer et download-starttidspunkt i `st.session_state`.
  - Lader brugeren vælge eller acceptere en lokal download-mappe.
  - Kalder importservicen, når brugeren klikker på importknappen.

- `app/services/tinglysning_import_service.py`
  - Scanner den valgte mappe for PDF-filer.
  - Filtrerer væk alle PDF-filer, der ikke er nyere end download-markøren.
  - Beregner SHA-256 hash for hver PDF.
  - Springer filer over, hvis de allerede findes i sagen.
  - Springer filer over, hvis samme fil forekommer flere gange i samme importbatch.
  - Opretter nye filer som almindelige documents via den eksisterende dokumentservice.

- `app/core/config.py`
  - Tilføjer `TINGLYSNING_DOWNLOAD_DIR` som konfigurerbar standardsti.


### Hvor filerne lander

Importerede PDF-filer behandles på samme måde som manuelt uploadede dokumenter:

- Filen gemmes som `original.pdf` under sagens dokumentmappe.
- Metadata gemmes som `metadata.json`.
- Dokumentet vises i dokumentbiblioteket på upload-siden.
- Dokumentet indgår derefter i det normale OCR- og ekstraktionsflow.

Der er altså ikke lavet et særskilt dokumentlager for TMV-import. Det er bevidst, fordi den nuværende løsning skal være så tæt på det eksisterende upload-flow som muligt.


### Deduplikering

Den nuværende import deduplikerer på filindhold, ikke på filnavn.

Det betyder:

- To filer med samme navn men forskelligt indhold importeres som to forskellige dokumenter.
- To filer med forskelligt navn men identisk indhold importeres kun én gang.

Det er vigtigt, fordi TMV-downloads kan skifte filnavne eller navnekonventioner uden at dokumentets indhold ændrer sig.


### Hvorfor den nuværende løsning er begrænset

Den nuværende løsning kan ikke fortsætte direkte fra en allerede åben, manuelt styret browserfane med TMV-login.

Grunden er ikke forretningslogik, men browser- og sessionskontrol:

- Servitut Engine kører som Streamlit-app og har ikke kontrol over en vilkårlig eksisterende browserfane.
- En ekstern browserfane, hvor brugeren selv har logget ind med MitID, eksponerer ikke sin aktive session til appen.
- Cookies, storage og sessionstilstand i den manuelle browserfane kan ikke pålideligt overtages af et separat automatiseringsscript.
- Selv hvis man forsøgte at læse fra brugerens `Downloads`-mappe og samtidig styre en anden browser, ville man stadig ikke have en sikker binding mellem "denne TMV-session" og "denne automatisering".

Konsekvensen er:

- Brugeren må stadig selv udløse login og download i TMV.
- Servitut Engine kan først automatisere fra det tidspunkt, hvor filerne ligger lokalt på disk.


## Hvorfor Playwright ændrer situationen

Playwright gør det muligt at kontrollere browseren fra start til slut i samme session.

Det betyder ikke, at MitID kan omgås. Det betyder:

- Brugeren åbner et browser-vindue, som Playwright ejer.
- Brugeren logger selv ind med MitID i det vindue.
- Efter login fortsætter automatiseringen i samme browserkontekst, hvor cookies og session allerede findes.

Det er den afgørende forskel.

I stedet for at prøve at "genbruge" en separat manuel fane, bygger man et flow, hvor browseren fra begyndelsen er den samme browser, som automatiseringen senere skal arbejde videre i.


## Målbillede for løsning 2

Løsning 2 er et Playwright-baseret TMV-flow med følgende brugeroplevelse:

1. Brugeren åbner upload-siden i Servitut Engine.
2. Brugeren klikker på `Start TMV-flow`.
3. Systemet starter en Playwright-browser.
4. Browseren åbner TMV.
5. Brugeren logger ind med MitID i Playwright-browseren.
6. Når login er gennemført, fortsætter systemet automatisk:
   - søger på adressen,
   - navigerer til relevante dokumenter,
   - downloader PDF-filer,
   - deduplikerer filerne,
   - opretter dokumenter i sagen,
   - viser status tilbage i Servitut Engine.

MitID er stadig manuelt. Resten kan blive automatiseret.


## Arkitektur for løsning 2

### Hovedprincip

Browserautomatiseringen skal køre som en kontrolleret proces, som Servitut Engine starter og overvåger.

Der er to realistiske måder at gøre det på:

### Model A: Lokal Playwright-proces styret fra Streamlit

Flow:

1. Streamlit-knap starter et backend-kald eller et lokalt script.
2. Scriptet starter Playwright.
3. Playwright downloader filer til en kontrolleret mappe.
4. Når download er færdig, importeres filerne via den eksisterende dokumentservice.

Fordele:

- Simpel at forstå.
- Kort vej fra den nuværende løsning.
- Kræver ikke ny serverarkitektur.

Ulemper:

- Streamlit er ikke ideel til langkørende browserjobs.
- Jobstatus, timeout, recovery og logning bliver hurtigt besværlig.
- Hvis browseren hænger, er brugeroplevelsen skrøbelig.

### Model B: Separat job-runner eller service til browserautomatisering

Flow:

1. Streamlit opretter et TMV-job.
2. En separat worker kører Playwright-jobbet.
3. Worker rapporterer status og resultater tilbage til sagens storage.
4. Streamlit viser fremdrift ved at læse jobstatus.

Fordele:

- Mere robust.
- Bedre til retries, timeout og fejlhåndtering.
- Nemmere at teste og drifte.

Ulemper:

- Mere kode og mere infrastruktur.
- Større løft end den nuværende filimport-løsning.


## Anbefalet migrationsretning

Den anbefalede vej er:

1. Først gøre TMV-automatisering til en afgrænset service med klart input og output.
2. Starte med en lokal Playwright-prototype.
3. Når flowet er stabilt, flytte eksekveringen til en job-runner-model.

Det reducerer risikoen for at bygge kø-, status- og driftssystemer, før selektorer, loginflow og downloadmekanik på TMV er bevist stabile.


## Foreslået servicekontrakt

Før Playwright implementeres, bør der defineres en intern servicekontrakt, så UI og automationslag kobles løst.

Eksempel:

- Input:
  - `case_id`
  - `address`
  - eventuelt `download_mode`
  - eventuelt `headless=False`

- Output:
  - `job_id`
  - `state` (`pending`, `waiting_for_login`, `searching`, `downloading`, `importing`, `completed`, `failed`)
  - `downloaded_files`
  - `imported_documents`
  - `skipped_duplicates`
  - `errors`

Det gør det muligt at starte med en simpel implementering og senere skifte eksekveringsmodel uden at ændre UI-kontrakten væsentligt.


## Implementeringstrin fra nuværende løsning til løsning 2

### Fase 1: Stabiliser nuværende importflow som genbrugelig base

Formål:

- Sikre at den nuværende lokale importservice kan bruges uændret som sidste led i Playwright-flowet.

Arbejdsopgaver:

- Beholde `import_downloaded_pdfs(...)` som den fælles importmekanisme.
- Gøre download-mappe og eventuelle jobmapper eksplicitte.
- Sikre at importresultat er struktureret og kan vises i UI.
- Eventuelt udvide med mere detaljeret logging pr. fil.

Resultat:

- Playwright behøver kun at levere PDF-filer til en mappe.
- Importlogikken genbruges i stedet for at blive skrevet om.


### Fase 2: Introducér en Playwright-service udenfor Streamlit-sidelogik

Formål:

- Flytte browserlogik væk fra Streamlit-siden.

Ny komponent:

- `app/services/tmv_browser_service.py` eller tilsvarende modul.

Ansvar:

- Starte browser.
- Oprette browser context.
- Sætte downloadmappe.
- Åbne TMV.
- Vente på at brugeren logger ind.
- Navigere videre, når login er bekræftet.
- Hente filer.
- Returnere status og downloadresultat.

Vigtigt:

- Streamlit-siden må ikke kende TMV-selektorer direkte.
- Selektorer, navigation og ventelogik skal ligge i service- eller automationlaget.


### Fase 3: Tilføj eksplicit login-state og job-state

Formål:

- Gøre flowet robust og forståeligt for brugeren.

Der bør indføres en jobmodel, f.eks.:

- `tmv_job_id`
- `case_id`
- `status`
- `started_at`
- `last_heartbeat_at`
- `download_dir`
- `import_result`
- `error_message`

Status bør mindst kunne skelne mellem:

- `pending`
- `browser_started`
- `waiting_for_login`
- `login_confirmed`
- `searching_property`
- `listing_documents`
- `downloading_documents`
- `importing_documents`
- `completed`
- `failed`
- `cancelled`

Det er nødvendigt, fordi brugerens manuelle MitID-step ellers bliver et sort hul i UX'en.


### Fase 4: Implementér TMV-navigation og downloadstrategi

Formål:

- Automatisere de trin, der i dag udføres manuelt efter login.

Der skal afklares og implementeres:

- Hvordan adressen søges frem i TMV.
- Hvordan korrekt ejendom vælges, hvis flere resultater matcher.
- Hvordan systemet finder dokumentlisten.
- Hvordan systemet identificerer relevante PDF-filer.
- Hvordan downloads trigges stabilt.
- Hvordan systemet ved, at alle downloads er afsluttet.

Der bør arbejdes med:

- robuste Playwright-locators,
- eksplicitte wait-strategier,
- download-events,
- timeout-grænser,
- recovery hvis enkelte dokumenter fejler.


### Fase 5: Genbrug eksisterende importservice som sidste trin

Når Playwright har lagt filerne i den kontrollerede download-mappe:

- kaldes den eksisterende importservice,
- filer deduplikeres,
- documents oprettes i sagen,
- resultat vises i UI.

Det er vigtigt, fordi download og import er to forskellige ansvar:

- Playwright skaffer filer.
- Importservicen afgør, hvad der skal gemmes i sagen.


### Fase 6: Flyt til job-runner når browserflowet er bevist

Når prototypen virker stabilt, bør browserjobbet flyttes ud af Streamlit-request/response-lignende flow.

Det kan ske ved:

- separat proces,
- baggrundsworker,
- API-endpoint + worker,
- eller anden lokal jobmanager.

Målet er:

- bedre kontrol over timeout,
- mulighed for cancellation,
- bedre logning,
- mindre risiko for at UI fryser eller mister tilstand.


## Sikkerhed og compliance

Playwright-løsningen skal designes med samme sikkerhedsforståelse som det manuelle flow.

Det betyder:

- MitID-godkendelsen udføres stadig af brugeren.
- Credentials må ikke gemmes i kode eller miljøvariabler.
- Session cookies må kun bruges inden for den kontrollerede browserkontekst og bør ikke persisteres uden et klart behov.
- Downloadede dokumenter kan være følsomme og skal fortsat behandles som sagsdata.
- Logging må ikke ukritisk skrive persondata, fulde søgestrenge eller dokumentindhold.


## Centrale tekniske risici

### 1. TMV's DOM og navigation kan ændre sig

Playwright-løsningen bliver følsom over for ændringer i TMV's HTML, knapper, labels og søgeflow.

Konsekvens:

- Selektorer kan bryde uden ændringer i vores egen kodebase.

Modtræk:

- Centralisér selektorer.
- Skriv integrationstests omkring de mest kritiske flows.
- Gør fejlbeskeder operationelle og præcise.


### 2. Login-detektion kan være skrøbelig

Det skal afgøres præcist, hvordan systemet ved, at MitID-login er gennemført.

Muligheder:

- URL-skift,
- synligt element efter login,
- fravær af login-knap,
- kendt TMV-side efter redirect.

Hvis denne detektion er for løs, bliver resten af flowet ustabilt.


### 3. Download-komplethed er ikke trivial

Det er ikke nok at klikke på et link.

Systemet skal vide:

- hvilke downloads der blev startet,
- hvilke der blev færdige,
- hvilke der fejlede,
- og om samme fil blev tilbudt flere gange.

Det er derfor vigtigt at bruge Playwrights download-events og ikke kun filsystem-polling.


### 4. Streamlit er ikke ideel som orkestreringsmotor

Hvis hele Playwright-flowet bindes direkte til en Streamlit-knap uden jobmodel:

- bliver recovery svær,
- brugeren kan miste status ved rerun,
- browserprocesser kan blive hængende.

Derfor bør jobmodellen tænkes ind tidligt, selv hvis første prototype er simpel.


## Teststrategi for løsning 2

### Enhedstests

Fokus:

- jobstatus-overgange,
- importresultat,
- deduplikering,
- fejlhåndtering,
- mapping mellem downloadresultat og documents.

Disse tests skal ikke kræve rigtig browser.


### Service-tests med mocks

Fokus:

- at Playwright-servicen reagerer korrekt på:
  - timeout,
  - manglende søgeresultat,
  - flere søgeresultater,
  - mislykkede downloads,
  - tom dokumentliste.

Her mockes browser- eller page-laget.


### Manuelle integrationskørsler

Fokus:

- rigtig MitID-login i Playwright-browser,
- rigtig søgning på TMV,
- rigtig download af PDF-filer,
- rigtig import i sagen.

Dette bliver nødvendigt, fordi MitID- og TMV-flowet ikke realistisk kan dækkes fuldt af almindelige CI-tests.


## Konkrete anbefalinger til næste implementering

Den praktiske rækkefølge bør være:

1. Opret en ren TMV-browserservice med klart input/output.
2. Implementér en minimal Playwright-prototype, som kun:
   - åbner TMV,
   - venter på login,
   - downloader én kendt PDF til en kontrolleret mappe.
3. Udvid til søgning på adresse og download af alle relevante dokumenter.
4. Kobl resultatet på den eksisterende importservice.
5. Indfør jobstatus og baggrundseksekvering, når browserflowet fungerer stabilt.

Det er den laveste-risiko vej fra den nuværende løsning til løsning 2.


## Kort konklusion

Den nuværende løsning er bevidst konservativ:

- brugeren logger ind og downloader selv i TMV,
- Servitut Engine importerer derefter nye lokale PDF-filer direkte i sagen.

Løsning 2 kræver ikke, at MitID fjernes fra flowet. Den kræver, at login sker i en browser, som Playwright kontrollerer fra starten. Når det er tilfældet, kan resten af TMV-flowet automatiseres i samme session.

Den rigtige vej frem er derfor ikke at forsøge at "overtage" en manuel browserfane, men at indføre et kontrolleret browserjob med Playwright og genbruge den eksisterende importservice som sidste led.
