# Plan for generel attest-model paa tværs af Aalborg, København og Middelfart

## Problem
Den nuværende canonical extraction antager i praksis ofte, at:

- én synlig attestblok med `Prioritet` svarer til én servitut
- titel, løbenummer og scope kan udtrækkes samlet fra samme lokale tekstvindue

Det holder nogenlunde i enklere cases som København og Middelfart, men ikke i Aalborg.

I Aalborg findes der mindst ét andet mønster:

- én deklarationsblok med fælles titel og metadata
- mange efterfølgende `Dato/løbenummer`-registreringer under `Anmærkninger`
- registreringerne er selvstændige canonical poster, selv om indholdet ligner hinanden

Det er derfor ikke nok at gøre prompten skarpere. Modellen bag pipeline skal ændres.

## Designprincip
Systemet skal modellere tinglysningsattesten i to niveauer:

1. `DeclarationBlock`
- en synlig attestblok med `Prioritet`, titel, aktnr., rå scope-tekst og anden fælles metadata

2. `RegistrationEntry`
- én atomar registrering identificeret ved `date_reference`
- dette er den canonical enhed i systemet

En `DeclarationBlock` kan have:

- præcis én `RegistrationEntry` i simple cases
- mange `RegistrationEntry` i fan-out-cases som Aalborg

Dermed bliver Aalborg ikke en specialregel. Det bliver blot en anden forekomst af samme generelle model.

## Hvad der skal være canonical
Canonical-listen skal bygges af `RegistrationEntry` og ikke af `Prioritet`.

Minimumsfelter pr. canonical entry:

- `date_reference`
- `registered_at`
- `source_document`
- reference til oprindelig `DeclarationBlock`
- `title` eller arvet titel fra blokken
- `archive_number` eller arvet aktnr.
- `raw_scope_text`
- `raw_parcel_references`
- `scope_source`

Regel:

- ingen canonical post uden unik `date_reference`
- samme titel maa gerne forekomme mange gange
- samme `Prioritet` maa gerne materialisere mange canonical poster

## Foreslået pipeline

### Trin 1: Deterministisk attest-parsing
Byg en regelbaseret parser, som læser OCR-siderne og opdeler attesten i `DeclarationBlock`-objekter.

Parseren skal kunne:

- finde start på en blok via `Dokument`, `Prioritet`, `Dokumenttype`, titel-linjer mv.
- samle continuation-sider til samme blok indtil næste blok starter
- genkende at `Anmærkninger` kan være continuation og ikke bare støj
- opsamle alle `date_reference`-linjer der hører til blokken

LLM skal ikke bruges til at afgøre blokgrænser i første omgang.

### Trin 2: Fan-out til canonical entries
Når en `DeclarationBlock` er samlet:

- opret én `RegistrationEntry` pr. unikt `date_reference`
- arv titel, aktnr. og rå scope-felter fra blokken til hver entry
- markér om entry er eksplicit hovedregistrering eller arvet fra anmærkningsfan-out

Dette er punktet hvor Aalborg og Middelfart/København forenes i én model.

### Trin 3: Scope-resolution mod ejendommens matrikler
Efter fan-out, men før akt-berigelse, køres en deterministisk scope-resolution.

Input:

- `raw_scope_text`
- `raw_parcel_references`
- case-matrikler
- normaliseringsregler for historiske/nutidige matrikelnumre

Output pr. canonical entry:

- `applies_to_parcel_numbers`
- `scope_basis`
- `scope_confidence`
- evt. `applies_to_primary_parcel`

Dette trin skal ske her, fordi:

- mappingen må ikke ske på hele `DeclarationBlock`, hvis blokken faner ud til mange registreringer
- mappingen skal være til stede før erklæring, redegørelse og akt-berigelse

### Trin 4: Akt-berigelse
Akter bruges derefter til:

- uddybning af titel og indhold
- bekræftelse eller udfyldning af scope når attesten er svag
- ekstra metadata til erklæring og redegørelse

Akt-berigelse må som udgangspunkt ikke overskrive et klart attest-scope.

### Trin 5: Produktlag
Samme canonical entries skal kunne drive begge slutprodukter:

1. Erklæring
- kompakt oversigt over de canonical registreringer der er relevante for sagen
- reviewstatus og sporbarhed

2. Redegørelse
- faglig vurdering af relevans for projektets matrikler
- mulighed for gruppering eller sammenfatning, men uden at miste reference til de underliggende `date_reference`

Det betyder:

- erklæring og redegørelse skal ikke have hver deres parsinglogik
- de skal dele samme canonical og scope-resolvede grundlag

## Hvor LLM stadig giver mening
LLM bør bruges smalt og kontrolleret:

- til at foreslå titel når bloktekst er rodet
- til at strukturere svage scope-formuleringer
- til fallback når parseren ikke kan klassificere en blok sikkert

LLM bør ikke være primær mekanisme for:

- tælling af canonical poster
- identifikation af blokgrænser
- afgørelse af om en `date_reference` findes

## Hvad der gør løsningen generel
Løsningen er generel, hvis den kan rumme mindst disse mønstre:

### Mønster A: enkel blok
København/Middelfart-lignende:

- én blok
- ét `date_reference`
- titel og scope står lokalt i samme tekst

### Mønster B: fan-out blok
Aalborg-lignende:

- én blok
- mange `date_reference`
- fælles titel/scope arves til mange registreringer

### Mønster C: svag continuation
- titel står på side 1
- scope eller aktnr. fortsætter på senere side
- parseren samler blokken før fan-out

Hvis modellen kan dække disse tre mønstre, er den ikke case-kodet.

## MVP for implementering
Første version bør levere:

- en ny attest-parser med `DeclarationBlock`
- fan-out til `RegistrationEntry`
- scope-resolution efter fan-out
- fortsat lagring af canonical output i eksisterende storage-lag
- tydelig provenance fra canonical entry tilbage til blok og sider

Første version bør ikke forsøge:

- perfekt juridisk semantik i alle fritekstfelter
- automatisk historisk matrikelopløsning i alle edge cases
- aggressiv prompt-tuning for at redde en forkert datamodel

## Success-kriterier
Løsningen er god nok når:

- Aalborg kan repræsentere mange canonical poster under samme deklarationsblok
- København og Middelfart stadig virker uden særlig case-logik
- erklæring og redegørelse bygger på samme canonical model
- systemet ikke er afhængigt af at ændre prompt eller segmentregler per sag

## Anbefalet næste skridt

1. Indfør interne modeller for `DeclarationBlock` og `RegistrationEntry`
2. Omskriv attest-pipelinen, så canonical build er deterministisk og blok-baseret
3. Flyt scope-resolution til efter fan-out
4. Bevar LLM som berigelseslag, ikke som tælle- eller parsermotor
