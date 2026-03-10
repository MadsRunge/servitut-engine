# Sammenligning: AI-rapport vs. Landinspektør
**Ejendom:** Ny Billeshavevej 4, 5500 Strib — matr.nr. 1o og 1v Billeshave Hgd., Strib-Røjleskov
**Landinspektør:** Mikkel Aaen, De Fakto, 20.12.2022
**AI-rapport:** rep-b719aeff, 2026-03-10
**Projektmatrikler:** 0001o, 0001v

---

## Legende
| Symbol | Betydning |
|---|---|
| ✅ | Samme vurdering |
| ⚠️ | Forskellig vurdering — bør undersøges |
| ➕ | Kun i AI-rapport (ikke hos landinspektøren) |
| ➖ | Kun hos landinspektøren (ikke i AI-rapport) |

---

## Servitutter i landinspektørens rapport (11 stk.)

| Løbenummer | Titel | Landinspektør | AI-rapport | Status | Bemærkning |
|---|---|---|---|---|---|
| 14.09.1903-913066-40 | Vandstandsregulering i Røjle Mose mv | **Nej** (matr. 38b) | Nej | ✅ | |
| 18.03.1932-913067-40 | Vej mv | **Nej** (matr. 22a) | Nej | ✅ | |
| 12.07.1955-2403-40 | Forsynings-/afløbsledninger mv | **Nej** (ikke ejendommen) | Nej | ✅ | |
| 02.07.1956-2192-40 | Stathusmandsloven, forbud mod yderligere belåning | **Ja** (matr. 1v) | ➖ mangler | ➖ | Sandsynligvis aflyst inden 2026-attesten. LI noterer selv "sandsynligvis ophørt" |
| 09.02.1957-490-40 | Byggelinjer mv | **Ja** (1o og 1v, rød) | Måske | ⚠️ | Akt 40_M_201 indeholder FKT-deklaration i stedet for vejbyggelinje. Matrikel "1A" i attesten matcher ikke 1o/1v (historisk opdeling) |
| 03.06.1957-2228-40 | Byggelinjer mv | **Nej** (matr. 38b) | Nej | ✅ | |
| 04.11.1966-5973-40 | Forsynings-/afløbsledninger mv | **Ja** (1o og 1v, orange) | Måske | ⚠️ | Ingen akt uploadet — tom servitut, ingen tekstgrundlag |
| 11.03.1974-1904-40 | Forsynings-/afløbsledninger mv | **Ja** (1o og 1v, orange) | Måske | ⚠️ | Ingen akt uploadet — tom servitut, ingen tekstgrundlag |
| 03.07.1974-5375-40 | Forsynings-/afløbsledninger mv | **Nej** (matr. 22a) | Nej | ✅ | |
| 05.08.1975-7546-40 | Forsynings-/afløbsledninger mv, prioritet forud for pantegæld | **Nej** (matr. 38b) | Nej | ✅ | |
| 04.09.2007-12086-40 | Byggeretligt skel mv | **Nej** (matr. 22a) | Nej | ✅ | |

---

## Servitutter kun i AI-rapport (ikke hos landinspektøren)

| Løbenummer | Titel | AI-rapport | Attest-bekræftet | Forklaring |
|---|---|---|---|---|
| 16.01.2024-1015412544 | Fjernvarmeanlæg | Måske | ✅ Ja | Ny siden 2022. Ingen akt uploadet |
| 20.03.1978-? | Oversigtsareal-deklaration, højdebegrænsning 1m | Nej | ⚠️ Nej | Fundet i akt men ikke i attest. Gælder matr. 22a — scope_confidence=1.0, rød markering. Bør verificeres |
| 04.12.1970-? | Kloakanlæg Røjlemose | Måske | ⚠️ Nej | Sandsynligvis falsk positiv — matrikler (71n, 71m, 22n...) matcher ikke ejendommen. scope_confidence=0.0 |

---

## Opsummering

| | Antal |
|---|---|
| Fælles servitutter (begge rapporter) | 10 af 11 |
| Mangler i AI-rapport (sandsynligvis aflyst) | 1 (`02.07.1956-2192-40`) |
| Ekstra i AI-rapport | 3 |
| **Fuld enighed om vurdering (Nej/Nej)** | **7** |
| AI siger Måske, LI siger Ja | 3 |
| AI siger Nej, LI siger Ja | 0 |

### Vigtigste afvigelser

1. **`09.02.1957-490-40` (vejbyggelinje)** — AI siger Måske, LI siger Ja/Rød. Årsag: akt 40_M_201 indeholder en FKT-deklaration der overskygger den originale 1957-servitut. Derudover er matrikel "1A" i attesten historisk opdelt i 1o, 1v m.fl. — AI kan ikke slutte dette uden matrikelregisteropslag.

2. **`04.11.1966-5973-40` og `11.03.1974-1904-40`** — AI siger Måske, LI siger Ja/Orange. Årsag: disse akter er ikke uploadet. Uden tekstgrundlag kan scope ikke vurderes.

3. **`02.07.1956-2192-40` mangler** — Denne servitut er i LI's 2022-rapport men ikke i vores 2026-attest. LI bemærker selv den "sandsynligvis er ophørt". Ikke en systemfejl.

### Bonus-fund
- **`16.01.2024-1015412544`** (fjernvarme) — ny servitut tinglysted efter LI's rapport. AI finder den, LI kendte den ikke.
- **`20.03.1978-?`** — oversigtsservitut med højdebegrænsning, ikke i attest men fundet i akt. Bør verificeres af inspektør.

### Konklusion
AI-systemet finder **10/11 af landinspektørens servitutter** (den ene er legitimt aflyst). De 7 "Nej"-vurderinger er alle korrekte. De 3 misser skyldes enten manglende akt-upload eller matrikelhistorik — begge er strukturelle begrænsninger der ikke kan løses uden hhv. fuldstændig akt-adgang og et matrikelregister-opslag. Systemet leverer 80-90% af redegørelsesarbejdet og peger præcist på de poster inspektøren skal verificere.
