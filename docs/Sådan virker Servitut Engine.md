# Sådan virker Servitut Engine

Et program der automatisk læser tinglyste servitutakter og laver en servitutredegørelse.
Du uploader PDF-filerne, klikker dig igennem nogle trin, og får en færdig tabel ud.

---

## Trin 1 — Opret en sag

Du starter med at oprette en sag for ejendommen: giv den et navn og evt. en adresse.
Det er din "mappe" i systemet.

---

## Trin 2 — Upload dokumenter

Du uploader to slags PDF-filer:

- **Tinglysningsattest** — den officielle fortegnelse over alle tinglyste byrder på ejendommen
- **Akter** — de individuelle servitutdokumenter (ét dokument pr. servitut)

Systemet ved selv forskel på de to typer, fordi du uploader dem i separate felter.

---

## Trin 3 — OCR (tekstgenkendelse)

De fleste akter er scannede billeder. Programmet kører automatisk tekstgenkendelse på alle
PDF-siderne, så teksten kan læses og analyseres. Du kan bagefter se en side ad gangen og
kontrollere, at kvaliteten er god nok.

---

## Trin 4 — Udtræk servitutter

Her sker det egentlige arbejde. Programmet bruger Claude (en avanceret sprogmodel) i to skridt:

### Skridt 1 — Tinglysningsattesten som facit

Claude læser attesten og laver en komplet liste over alle servitutter på ejendommen med
løbenummer og titel. Det er denne liste der bestemmer, hvilke servitutter der i alt er.
Ingen akt kan tilføje flere.

### Skridt 2 — Berigelse fra akterne

For hvert aktdokument spørger programmet Claude:

> *"Hvilke af de kendte servitutter fra attesten er beskrevet i denne akt? Hvad siger akten om dem?"*

Claude returnerer berigede detaljer: beskrivelse, påtaleberettiget, rådighedstype,
håndteringsanbefaling og byggemarkeringen (rød/orange/sort).

**Resultatet er en komplet servitutliste, hvor hvert punkt har:**

- Hvad og hvornår — fra attesten
- Hvad det betyder og hvem der håndhæver — fra akterne
- En vurdering af byggekonsekvens — **rød / orange / sort**

| Markering | Betydning |
|-----------|-----------|
| 🔴 Rød | Servitutten har direkte betydning for placering af ny bebyggelse |
| 🟠 Orange | Der skal tages stilling — fx mulig aflysning eller uafklaret omfang |
| ⚫ Sort | Servitutten vedrører ikke projektområdet |

---

## Trin 5 — Vælg målmatrikel

Ejendommen kan have flere matrikler. Du vælger hvilken matrikel rapporten skal handle om.
Systemet finder selv matrikelnumrene fra attesten og vurderer automatisk hvilke servitutter
der gælder netop den valgte matrikel.

---

## Trin 6 — Generer rapporten

Programmet samler alle relevante servitutter for den valgte matrikel og genererer en færdig
redegørelsestabel med 7 kolonner:

| Dato/løbenummer | Beskrivelse | Påtaleberettiget | Rådighed/tilstand | Offentlig/privatretlig | Håndtering | Vedrører projektområdet |
|---|---|---|---|---|---|---|

Du kan eksportere rapporten som:

- **HTML** — klar til print (A3 liggende)
- **Markdown** — åbn i Word eller Notion
- **JSON** — til videre brug i andre systemer

---

## Trin 7 — Sporing og kontrol

Hvis du er i tvivl om et punkt i rapporten, kan du klikke dig tilbage til kilden:

```
Rapportlinje → Servituttens beskrivelse → Tekstuddrag fra akten → Fuld OCR-side → Original PDF-side
```

Hele kæden er synlig, så du altid kan dokumentere, hvorfra en oplysning stammer.

---

## Samlet overblik

```
Upload PDF'er
    ↓
Tekstgenkendelse (OCR)
    ↓
Attest giver listen over servitutter
    ↓
Akterne giver detaljerne pr. servitut
    ↓
Vælg målmatrikel
    ↓
Rapport klar til eksport
```

Hele processen tager typisk **5–10 minutter** afhængigt af antallet af akter.

---

*Servitut Engine er udviklet til brug i landinspektørpraksis og er designet til at matche
den faglige arbejdsgang for servitutredegørelser.*
