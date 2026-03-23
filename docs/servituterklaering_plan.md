# Plan for servituterklaering, sporbarhed og kvalitetskontrol

## Formaal
Naeste produktspor er ikke chat eller eksport, men et mere driftsklart review-lag med:
- en separat artefakt/model for `Servituterklaering`
- tydelig sporbarhed fra hver servitut til kilde og matrikelkobling
- kvalitetskontrol pr. servitut

Servituterklaeringen skal vaere en lettere, mere operationel leverance end redegoerelsen. Den skal vise alle servitutter for ejendommen, ogsaa dem der er usikre, fordi netop usikkerheden er fagligt vigtig for landinspektoeren.

## Produktprincipper
- Alle servitutter vises, ikke kun sikre matches.
- Uklar eller historisk matrikelkobling skal fremhaeves, ikke filtreres vaek.
- Tinglysningsattesten er fortsat canonical kilde, men aktindhold og historiske matrikelnumre skal kunne skabe afvigelser, som brugeren kan se.
- Kvalitetskontrol sker pr. servitut, ikke pr. enkeltfelt.

## Ny artefakt
Indfoer en separat model som fx `Servituterklaering` med:
- `declaration_id`
- `case_id`
- `target_parcel_numbers`
- `created_at`
- `rows`
- `notes`
- `manually_reviewed`

Hver row boer bygge paa en eksisterende `Servitut`, men gemmes som selvstaendig snapshot, saa erklaeringen kan bevares selv hvis senere extraction koeres om.

## Obligatoriske kolonner i v1
- `priority`
- `date_reference`
- `title`
- `archive_number`
- `beneficiary`
- `remarks`
- `applies_to_parcel_numbers`

`remarks` skal vaere et fagligt kondenseret felt, der forklarer afvigelser eller forbehold, fx:
- "Kun fundet i akt, ikke bekraeftet i attest"
- "Historisk matrikelreference, kobling uafklaret"
- "Scope afledt fra attest"
- "Lav confidence i scope-vurdering"

## Sporbarhed og DB
Det eksisterende grundlag er allerede godt:
- `Servitut.evidence`
- `scope_source`
- `scope_basis`
- `scope_confidence`
- `confirmed_by_attest`
- `raw_parcel_references`

Naeste DB-loeft boer vaere at tilfoeje servitutniveau-reviewfelter, fx:
- `review_status`: `klar | kraever_kontrol | historisk_matrikel | mangler_kilde | kun_i_akt`
- `review_reason`
- `reviewed_by`
- `reviewed_at`

Det boer ligge paa `Servitut`, saa baade review-UI og erklaering kan bruge samme vurdering.

## Hvordan erklaeringen bygges
1. Laes alle servitutter for sagen.
2. Annoter hver servitut mod valgte matrikler med eksisterende scope-logik.
3. Beregn `review_status` ud fra regler:
   - `kun_i_akt`, hvis `confirmed_by_attest = false`
   - `historisk_matrikel`, hvis scope er `Måske` og rae matrikelreferencer ikke matcher aktuelle matrikler
   - `mangler_kilde`, hvis evidens er tom
   - `kraever_kontrol`, hvis confidence eller scope_confidence er lav
   - ellers `klar`
4. Byg erklaeringsraekker som et snapshot.

## UI i Next.js
Tilfoej en ny fane i sagsrummet: `Servituterklaering`.

Visningen skal vaere en kompakt tabel med:
- sortering fra aeldste til nyeste
- tydelig matrikelkolonne
- statusbadge for kvalitetskontrol
- mulighed for at aabne evidens og reviewdetaljer pr. servitut

Review-panelet skal ikke vise hele Streamlit-transparensen, men brugeren skal kunne se:
- hvorfor en servitut er markeret usikker
- hvilke matrikler den ser ud til at vedroere
- om den kun findes i akt eller ogsaa i attest
- hvilke evidenschunks vurderingen bygger paa

## MVP-raekkefoelge
1. Udvid `Servitut` med reviewfelter og simple regler for `review_status`.
2. Indfoer `Servituterklaering` som separat model + storage/API.
3. Byg backend-service der genererer snapshot-raekker fra servitutter.
4. Tilfoej ny erklaeringsfane i Next.js.
5. Kobl review-status og remarks til tabellen.

## Bevidste fravalg i foerste version
- eksport til Excel, PDF eller Word
- feltniveau-review
- AI-chat
- tung manuel editor som i redegoerelsesflowet

Foerste version skal bevise, at vi kan levere en stabil, sporbar og fagligt anvendelig servituterklaering for hver sag.
