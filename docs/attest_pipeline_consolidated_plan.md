# Samlet implementeringsplan: Attest-pipeline v2

Dette dokument erstatter og syntetiserer de to tidligere planfiler:
- `attest_registration_model_plan.md` — datamodel og canonical struktur
- `stor_attest_pipeline_plan.md` — skalerbarhed og segmentering

Disse to planer løser reelle problemer, men er endnu ikke sammenskrevet til en
implementerbar rygrad. Det gør dette dokument.

---

## Kerneproblemet

Den nuværende pipeline har en implicit antagelse bagt ind i koden:

> `1 Prioritet-blok = 1 canonical servitut`

Det er forkert. Den juridisk atomare enhed i dansk tinglysning er
`dato + løbenummer` — altså `date_reference`. En `Prioritet`-blok kan dække
mange unikke registreringer (Aalborg-mønstret), og en registrering kan strække
sig over mange OCR-sider (stor-attest-mønstret).

Fejlen kan ikke repareres med prompt-tuning. Datamodellen bag pipelinen skal
ændres.

---

## Pipeline-kæden

```
OCR-sider
  │
  ▼
[Trin 1: Segmentering] — deterministisk
  │
  ▼
AttestBlock[]
  │
  ▼
[Trin 2: Assembly] — deterministisk (LLM-fallback kun for unknown)
  │
  ▼
DeclarationBlock[]
  │
  ▼
[Trin 3: Fan-out] — deterministisk
  │
  ▼
RegistrationEntry[]
  │
  ▼
[Trin 4: Scope-resolution] — deterministisk + LLM-assist for svage felter
  │
  ▼
[Trin 5: Enrichment] — LLM-assisteret, smalt scope
  │
  ▼
Canonical entries → Erklæring / Redegørelse
```

`AttestBlock` og `DeclarationBlock` er ikke det samme objekt. `AttestBlock`
er en mekanisk side-baseret opdeling. `DeclarationBlock` er en semantisk enhed
der kan strække sig over mange `AttestBlock`-objekter. Det er vigtigt at holde
disse to lag adskilt.

---

## Datamodeller

Alle modeller skal defineres i `app/models/attest.py` (Pydantic) og evt. spejles
i `app/db/models.py` (SQLModel) for persistence.

### EntryStatus

```python
class EntryStatus(str, Enum):
    AKTIV  = "aktiv"
    AFLYST = "aflyst"
    UKENDT = "ukendt"
```

`EntryStatus` er `UKENDT` som default. Den må aldrig antages at være `AKTIV`
medmindre der er eksplicit bevis for det. Erklæring og redegørelse må ikke
medtage `AFLYST`-entries som aktive rettigheder.

### ScopeType

```python
class ScopeType(str, Enum):
    EXPLICIT_PARCEL_LIST = "explicit_parcel_list"   # navngivne matrikler
    WHOLE_PROPERTY       = "whole_property"          # "gælder hele ejendommen"
    AREA_DESCRIPTION     = "area_description"        # geografisk fritekst
    UNKNOWN              = "unknown"                 # ikke resolveret
```

### AttestBlock

Mekanisk output fra side-parseren. Ingen semantisk tolkning på dette niveau.

```python
class AttestBlockType(str, Enum):
    DECLARATION_START        = "declaration_start"
    DECLARATION_CONTINUATION = "declaration_continuation"
    ANMERKNING_FANOUT        = "anmerkning_fanout"   # liste af dato/løbenumre
    ANMERKNING_TEXT          = "anmerkning_text"     # fritekst-note
    AFLYSNING                = "aflysning"
    UNKNOWN                  = "unknown"

class AttestBlock(BaseModel):
    block_id: str                            # sha256(doc_id:page_start:seq)[:12]
    case_id: str
    document_id: str
    page_start: int
    page_end: int
    raw_text: str
    block_type: AttestBlockType
    candidate_date_references: list[str]     # rå mønstre, ikke valideret endnu
    candidate_archive_number: str | None
    candidate_title: str | None
    candidate_parcel_refs: list[str]
```

### DeclarationBlock

Semantisk assembly af én eller flere sammenhængende `AttestBlock`-objekter.

```python
class DeclarationBlock(BaseModel):
    block_id: str                            # sha256(source_block_ids joined)[:12]
    case_id: str
    document_id: str
    page_start: int
    page_end: int
    source_block_ids: list[str]              # provenance → AttestBlock
    priority_number: str | None
    title: str | None
    archive_number: str | None
    raw_scope_text: str
    raw_parcel_references: list[str]
    has_aflysning: bool                      # mindst én AFLYSNING-block fundet
    status: EntryStatus                      # AKTIV / AFLYST / UKENDT
```

### RegistrationEntry

Den atomare canonical enhed. Alle downstream-produkter bygger på denne.

```python
class RegistrationEntry(BaseModel):
    entry_id: str                            # sha256(doc_id + ":" + (date_reference or block_id))[:12]
    case_id: str
    document_id: str

    # Identitet
    date_reference: str | None               # normaliseret: "YYYYMMDD-NNNNNN"; None hvis ikke fundet
    registered_at: date | None               # None hvis date_reference mangler
    archive_number: str | None
    title: str

    # Provenance
    declaration_block_id: str
    source_pages: list[int]
    is_fanout_entry: bool                    # True hvis arvet fra blok via fan-out

    # Scope
    raw_scope_text: str
    raw_parcel_references: list[str]
    scope_type: ScopeType
    scope_confidence: float                  # 0.0–1.0
    applies_to_parcel_numbers: list[str]     # normaliserede matrikelnumre
    applies_to_primary_parcel: bool

    # Status
    status: EntryStatus
```

---

## Trin 1: Segmentering (deterministisk)

**Mål:** Opdel OCR-sider for attest-dokumenter i `AttestBlock`-objekter.

**Input:** OCR-sider for dokumenter af type `tinglysningsattest`.

**Output:** `AttestBlock[]` gemt i storage og/eller DB.

**Regler:**

- Split på tydelige `Prioritet N` / `Dokument N` / `Dokumenttype`-linjer →
  `DECLARATION_START`
- Sider der ikke starter med ny post men indeholder `Dato/løbenummer`-mønstre
  i listeform → `ANMERKNING_FANOUT`
- Sider der opfylder **mindst ét** af nedenstående mønstre → `AFLYSNING`:
  - Linjen indeholder `Aflyst` efterfulgt af dato-lignende mønster, fx
    `Aflyst den 01.01.2015` eller `Aflyst 01.01.2015`
  - Linjen indeholder `Aflyses` som selvstændig sætningsdel
  - Linjen indeholder `Tinglyst aflysning` eller `Aflysning tinglyst`
  - En tabelcelle indeholder `Aflyst` som eneste indhold (format fra OIS/tinglyst.dk)
- Sider der indeholder `aflyst` som del af fritekst uden de ovenstående mønstre
  (fx "se anmærkninger vedr. delvis aflysning") klassificeres **ikke** som
  `AFLYSNING` — de er `DECLARATION_CONTINUATION` eller `ANMERKNING_TEXT`.
  Usikkerheden om status propagerer til `EntryStatus=UKENDT` i fan-out.
- Sider der er ren fritekst-continuation → `DECLARATION_CONTINUATION` eller
  `ANMERKNING_TEXT`
- Alt andet → `UNKNOWN`

**Invariant:** Hver OCR-side skal tilhøre mindst ét `AttestBlock`. Ingen sider
må tabes.

**LLM:** Ikke tilladt i dette trin.

**Persistence:** `AttestBlock[]` gemmes til storage eller JSONB-felt på
`DocumentTable` efter segmentering. Segmentering er resumable: hvis
`attest_blocks` allerede eksisterer for dokumentet, genbruges de.

---

## Trin 2: Assembly (deterministisk + LLM-fallback for unknown)

**Mål:** Saml `AttestBlock[]` til `DeclarationBlock[]`. Dette er trinnet hvor
sidesplit på tværs af blokgrænser håndteres.

**Assembly-algoritme:**

```
current_block = None

for each AttestBlock in document order:

  if block.type == DECLARATION_START:
    if current_block is not None:
      emit current_block
    current_block = new DeclarationBlock(from block)

  elif block.type in [DECLARATION_CONTINUATION, ANMERKNING_FANOUT,
                      ANMERKNING_TEXT, AFLYSNING]:
    if current_block is None:
      # Continuation uden start → opret "orphan" blok
      current_block = new DeclarationBlock(orphan=True, from block)
    else:
      current_block.merge(block)
      if block.type == AFLYSNING:
        current_block.has_aflysning = True

  elif block.type == UNKNOWN:
    # Forsøg LLM-klassifikation (se nedenfor)
    reclassified = llm_classify_block(block)
    # Rekursivt behandl med reclassified type

if current_block is not None:
  emit current_block
```

**Håndtering af `UNKNOWN` via LLM:**

LLM-kaldet er snævert: "Her er teksten fra ét attest-segment. Hvilken type er
det? Svar med én af: `declaration_start`, `declaration_continuation`,
`anmerkning_fanout`, `anmerkning_text`, `aflysning`, `unknown`."

Hvis LLM returnerer `unknown`, appendes blokken til foregående
`DeclarationBlock` med note `contains_unclassified_blocks: True`.

---

## Trin 3: Fan-out (deterministisk)

**Mål:** Materialisér `RegistrationEntry[]` fra `DeclarationBlock`.

**Regler:**

```
for each DeclarationBlock:

  date_refs = extract_and_validate_date_references(block)

  if len(date_refs) == 0:
    # Ingen date_reference fundet → én entry med status UKENDT
    emit RegistrationEntry(
      date_reference=None,
      status=UKENDT,
      is_fanout_entry=False,
      ...
    )

  elif len(date_refs) == 1:
    # Simple case (København/Middelfart-mønster)
    emit RegistrationEntry(
      date_reference=date_refs[0],
      status=AFLYST if block.has_aflysning else AKTIV,
      is_fanout_entry=False,
      ...
    )

  else:
    # Fan-out case (Aalborg-mønster)
    # Udtræk parcelreferencer pr. ANMERKNING_FANOUT-sektion, ikke kun fra blokken
    per_ref_parcel_refs = extract_per_ref_parcel_refs(block)  # dict[date_ref, list[str]]

    for ref in date_refs:
      own_parcel_refs = per_ref_parcel_refs.get(ref, [])

      if own_parcel_refs:
        # Entrien har egne parcelreferencer i ANMERKNING_FANOUT-sektionen
        # → brug dem; arv ikke fra blokken
        raw_scope  = format_scope_from_refs(own_parcel_refs)
        scope_conf = 0.75   # eksplicit, men ikke bekræftet mod case-matrikler endnu
      else:
        # Ingen egne parcelreferencer → arv scope fra blok, men markér lavt
        raw_scope  = block.raw_scope_text
        scope_conf = 0.35   # arvet, ikke eksplicit for denne entry

      emit RegistrationEntry(
        date_reference=ref,
        status=AFLYST if block.has_aflysning else AKTIV,
        is_fanout_entry=True,
        title=block.title,
        raw_scope_text=raw_scope,
        scope_confidence=scope_conf,
        ...
      )
```

**Regel for scope-arv i fan-out:**

- En fan-out entry **må arve** scope fra blokken, hvis `ANMERKNING_FANOUT`-sektionen
  kun indeholder `dato/løbenummer`-linjer og ingen egne matrikelreferencer.
- En fan-out entry **skal have eget scope** (med `scope_confidence=0.75` som
  udgangspunkt) hvis `ANMERKNING_FANOUT`-sektionen indeholder matrikelreferencer
  ved siden af `dato/løbenummer`-linjerne.
- Hvis to fan-out entries under samme blok har divergerende parcelreferencer,
  er det et tegn på at blokken dækker rettigheder på forskellige matrikler.
  Sæt `scope_confidence=0.35` på alle entries i blokken og flag blokken med
  `scope_divergence=True`. Dette underminerer ikke modellen — det er synlig
  usikkerhed der kan reviewes.

**`date_reference`-regel:**

`date_reference` er `str | None`. En entry med `date_reference=None` er
tilladt, men repræsenterer en post der ikke kunne identificeres entydigt.
Sådanne entries sættes til `status=UKENDT` og må ikke medtages i erklæring.
Redegørelse kan vise dem eksplicit med markering "ikke verificeret".

`entry_id` beregnes som:
- `sha256(doc_id + ":" + date_reference)[:12]` når `date_reference` er til stede
- `sha256(doc_id + ":" + declaration_block_id)[:12]` som fallback

Accepterede inputformater (normaliseres alle til `YYYYMMDD-NNNNNN`):
- `01.01.2015 - 123456`
- `01-01-2015/123456`
- `01.01.2015-123456`

OCR-varianter med O/0-forveksling eller manglende tegn: forsøges normaliser;
lykkes det ikke, sættes `date_reference=None`.

**Invariant:** Canonical listen må aldrig indeholde duplikater på
(`document_id`, `date_reference`) for entries hvor `date_reference is not None`.
Ved merge bruges `date_reference` som primær nøgle, `archive_number` som sekundær.

---

## Trin 4: Scope-resolution (deterministisk + LLM-assist)

**Mål:** For hver `RegistrationEntry`: afgør hvilke matrikler den dækker og
med hvilken sikkerhed.

**Rækkefølge:**

1. **Udtræk parcelreferencer** fra `raw_parcel_references` + `raw_scope_text`
   via regulære udtryk (danske matrikelnumre: `\d+[a-z]?`, ejerlav-koder mv.)

2. **Normaliser** matrikelnumre. Anvend historisk mappingtabel for kommunale
   matrikelnumre præ-2007 (kommunesammenlægning). Uden mappingtabel: bevar
   raw og sæt `scope_confidence` til 0.5.

3. **Match** mod case-matrikler (deterministisk set-intersection).

4. **Klassificer scope-type og tildel `scope_confidence`:**

   | Situation | `scope_type` | `scope_confidence` |
   |-----------|-------------|-------------------|
   | Navngivne matrikler ekstraheret og alle matchet mod case-matrikler | `EXPLICIT_PARCEL_LIST` | 0.95 |
   | Navngivne matrikler ekstraheret, delvist match (mindst én ukendt) | `EXPLICIT_PARCEL_LIST` | 0.75 |
   | Tekst indeholder "hele ejendommen" / "samtlige parceller" / "al grund" | `WHOLE_PROPERTY` | 0.80 |
   | Geografisk fritekst uden matrikelnumre, men med stedsnavnsmatch | `AREA_DESCRIPTION` | 0.60 |
   | Geografisk fritekst uden nogen match-signal | `AREA_DESCRIPTION` | 0.40 |
   | Historisk matrikelnummer uden mappingtabel | `EXPLICIT_PARCEL_LIST` | 0.50 |
   | Fan-out entry der arver scope fra blok uden egne parcelrefs | *(arvet fra blok)* | 0.35 |
   | Ingen scope-information overhovedet | `UNKNOWN` | 0.10 |

   **Review-threshold:** Entries med `scope_confidence < 0.50` skal markeres
   til manuel review. Erklæring medtager ikke entries med `scope_confidence < 0.50`
   medmindre brugeren eksplicit accepterer dem.

5. **LLM-assist:** Kun for entries med `scope_type=UNKNOWN` eller
   `scope_confidence < 0.50`. LLM-prompt: "Her er scope-teksten fra en
   tinglysningsregistrering. Angiv scope-type og evt. matrikelnumre."
   LLM må ikke overskrive et allerede resolveret scope (confidence ≥ 0.50).

---

## Trin 5: Enrichment (LLM-assisteret)

**Mål:** Berig svage felter. LLM bruges smalt og kontrolleret.

**Hvad LLM bruges til:**
- Normalisering af rodet titel-tekst
- Udfyldning af `archive_number` når den er uklar i OCR
- Metadata-komplettering fra tilknyttede akter (akt-berigelse)

**Hvad LLM ikke bruges til:**
- Tælling af canonical poster
- Identifikation af blokgrænser
- Afgørelse af om en `date_reference` eksisterer
- Afgørelse af om en post er aflyst

Akt-berigelse (fra tilknyttede dokumenter) må ikke overskrive et klart
attest-scope. Akt-data er supplerende, ikke autoritativt.

---

## Skalerbarhed og resumable pipeline

For store attester (50+ sider):

- Segmentering (Trin 1) gemmes til storage efter completion — kan genbruges
- Fan-out (Trin 3) eksekveres per `DeclarationBlock` — fejl på én blok stopper
  ikke de øvrige
- Progress-events: `segmenting_attest`, `assembling_blocks`,
  `extracting_entries`, `resolving_scope`
- Ved delfejl: geneksekvér kun fejlede blokke, genbrrug allerede processerede

---

## Produktlag

Erklæring og redegørelse bygger på identisk canonical model. De må ikke
implementere eigen parsinglogik.

**Erklæring** filtrerer på:
- `status == AKTIV`
- `applies_to_primary_parcel == True` eller `applies_to_parcel_numbers` ∩ case-matrikler ≠ ∅

**Redegørelse** tillader derudover:
- Gruppering under `declaration_block_id` (vise "12 registreringer under
  Deklaration vedr. hegn")
- Inkludering af entries med lav `scope_confidence` med eksplicit markering

Begge produkter skal medføre `source_pages` og `entry_id` til sporbarhed.

---

## Hvad der ikke er i scope for MVP

- Perfekt historisk matrikelresolution for alle edge cases
- Automatisk parallel scheduler
- Ny UI-editor i Next.js
- Semantisk retrieval over hele attesten
- Avanceret dedup på tværs af dokumenter i samme sag

---

## Success-kriterier

Løsningen er god nok når:

1. Aalborg repræsenterer mange `RegistrationEntry` under én `DeclarationBlock`
   uden specialkode
2. København og Middelfart producerer korrekte 1:1-entries uden særlig case-logik
3. Aflyst registrering havner ikke i erklæring som aktiv rettighed
4. En 140-siders attest kan behandles uden at samle alt i ét prompt-kald
5. Pipeline kan genoptages efter delvise fejl
6. Erklæring og redegørelse bygger på identisk canonical model

---

## Implementeringsrækkefølge

| # | Opgave | Output | Verificering |
|---|--------|--------|--------------|
| 1 | Definer `AttestBlock`, `DeclarationBlock`, `RegistrationEntry`, `EntryStatus`, `ScopeType` i `app/models/attest.py` | Pydantic-modeller | Pydantic-validering + unit tests |
| 2 | Byg regelbaseret side-parser → `AttestBlock[]` | `app/services/attest/segmenter.py` | Unit tests på real OCR fra Aalborg + Middelfart |
| 3 | Byg assembly-algoritme → `DeclarationBlock[]` | `app/services/attest/assembler.py` | Assert korrekt blokantal på kendte cases |
| 4 | Byg fan-out + `date_reference`-validering → `RegistrationEntry[]` | `app/services/attest/fanout.py` | Assert Aalborg N entries, Middelfart 1 entry |
| 5 | Byg scope-resolution (regelbaseret del) | `app/services/attest/scope_resolver.py` | Unit tests med kendte matrikelrefs |
| 6 | Integrer med storage og progress-events | `app/services/storage_service.py` | Resumable kørsel på stor Aalborg-attest |
| 7 | Tilføj LLM-assist som smalt enrichment-lag | `app/services/attest/enricher.py` | Ingen regression på Middelfart/København |
| 8 | Kobl produktlag (erklæring/redegørelse) til ny canonical model | `app/services/report_service.py` | Fuld pipeline-kørsel end-to-end på alle cases |
