# Vocabulary coverage matrix

biograph's 22 event types and 27 relation types, read from `schema/`, against the five benchmarks' label spaces.

| cell | meaning |
|---|---|
| `*` clean | clean match |
| `~` partial | partial -- information lost, see note |
| `o` residual | no target label; scored only via the catch-all class |
| `-` none | not expressible in this label space |
| `=` untyped | metric is category-free; type participates untyped |

| biograph type | B1 Biographical | B2 BiographicalEvents | B3 PMOA-TTS | B4 TLEX | B5 Grounding |
|---|---|---|---|---|---|
| `event:birth` | `*` clean | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:death` | `*` clean | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:education` | `~` partial | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:employment_start` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:employment_end` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:role_change` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:invention` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:patent_filed` | `o` residual | `~` partial | `=` untyped | `=` untyped | `~` partial |
| `event:patent_granted` | `o` residual | `~` partial | `=` untyped | `=` untyped | `~` partial |
| `event:publication` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:product_launch` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:public_demonstration` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:conference` | `o` residual | `~` partial | `=` untyped | `=` untyped | `~` partial |
| `event:visit` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:meeting` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:relocation` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:award` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:company_founded` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:company_sold` | `o` residual | `~` partial | `=` untyped | `=` untyped | `~` partial |
| `event:company_renamed` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:retirement` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `event:other` | `o` residual | `~` partial | `=` untyped | `=` untyped | `=` untyped |
| `relation:born_in` | `*` clean | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:died_in` | `*` clean | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:lived_in` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:visited` | `o` residual | `~` partial | `-` none | `-` none | `~` partial |
| `relation:relocated_to` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:worked_at` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:employed_by` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:founded` | `o` residual | `~` partial | `-` none | `-` none | `~` partial |
| `relation:member_of` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:supervised_by` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:mentored` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:collaborated_with` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:met` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:married_to` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:family_of` | `~` partial | `-` none | `-` none | `-` none | `=` untyped |
| `relation:studied_at` | `*` clean | `~` partial | `-` none | `-` none | `=` untyped |
| `relation:educated_by` | `~` partial | `-` none | `-` none | `-` none | `=` untyped |
| `relation:invented` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:patented` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:published` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:developed` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:awarded` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:licensed_to` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:acquired_by` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:sold_to` | `o` residual | `-` none | `-` none | `-` none | `~` partial |
| `relation:renamed_to` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |
| `relation:corresponded_with` | `o` residual | `-` none | `-` none | `-` none | `=` untyped |

## Column defaults

**B1 Biographical** -- no target relation; predicted as the `other` class

**B2 BiographicalEvents** -- collapses to TimeML EVENT; scored by trigger anchoring, not type
- all relation types: `none` -- the role inventory is writer-centric; a relation between two third parties has no role to fill

**B3 PMOA-TTS** -- event text matched by embedding distance; type never compared
- all relation types: `none` -- the corpus is (event, time) tuples; relations.json has no counterpart and is not projected

**B4 TLEX** -- ordering only; type never compared
- all relation types: `none` -- TLEX consumes the timeline, which build() renders from events.json alone. Relation start/end dates are populated for at most 21.5% of any relation type (worked_at) and are not part of the timeline

**B5 Grounding** -- verified per citation, not per type

## Notes per cell

Only where a cell departs from its column's default.

**`event:birth`**
- *B1 Biographical* -- birthdate: event.date; birthplace: event.location

**`event:death`**
- *B1 Biographical* -- deathdate: event.date; deathplace: event.location

**`event:education`**
- *B1 Biographical* -- educatedAt: institution recovered from participants[] role, which is free text, not an enum

**`event:patent_filed`**
- *B5 Grounding* -- 10/14 citations carry a quote (71%) -- the rest cite a page only and are outside this check

**`event:patent_granted`**
- *B5 Grounding* -- 9/11 citations carry a quote (82%) -- the rest cite a page only and are outside this check

**`event:conference`**
- *B5 Grounding* -- 101/107 citations carry a quote (94%) -- the rest cite a page only and are outside this check

**`event:company_sold`**
- *B5 Grounding* -- 8/11 citations carry a quote (73%) -- the rest cite a page only and are outside this check

**`event:other`**
- *B2 BiographicalEvents* -- collapses to EVENT; the corpus's STATE class has no biograph counterpart at all -- a state is by definition not a dateable occurrence (schema/README.md), so every STATE annotation is an unreachable recall ceiling

**`relation:born_in`**
- *B1 Biographical* -- birthplace
- *B2 BiographicalEvents* -- contributes ARGx-LOC only

**`relation:died_in`**
- *B1 Biographical* -- deathplace
- *B2 BiographicalEvents* -- contributes ARGx-LOC only

**`relation:lived_in`**
- *B2 BiographicalEvents* -- contributes ARGx-LOC only

**`relation:visited`**
- *B2 BiographicalEvents* -- contributes ARGx-LOC only
- *B5 Grounding* -- 37/39 citations carry a quote (95%) -- the rest cite a page only and are outside this check

**`relation:relocated_to`**
- *B2 BiographicalEvents* -- contributes ARGx-LOC only

**`relation:worked_at`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only

**`relation:employed_by`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only

**`relation:founded`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only
- *B5 Grounding* -- 68/79 citations carry a quote (86%) -- the rest cite a page only and are outside this check

**`relation:member_of`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only

**`relation:mentored`**
- *B5 Grounding* -- 90/99 citations carry a quote (91%) -- the rest cite a page only and are outside this check

**`relation:met`**
- *B5 Grounding* -- 17/20 citations carry a quote (85%) -- the rest cite a page only and are outside this check

**`relation:family_of`**
- *B1 Biographical* -- ofParent / hasChild / sibling all collapse here. Subtype and direction survive in `note` for 30 of 85 corpus instances (35%): 'Father', 'Mother', 'Brother', 'youngest son'. Reported as combined family-relation recall, with per-subtype figures over the note-bearing subset only, labelled as such

**`relation:studied_at`**
- *B1 Biographical* -- educatedAt
- *B2 BiographicalEvents* -- contributes ARGx-ORG only

**`relation:educated_by`**
- *B1 Biographical* -- educatedAt is institution-valued; educated_by targets a person, so it is a hit only when the gold sentence names a teacher as the institution

**`relation:patented`**
- *B5 Grounding* -- 2/11 citations carry a quote (18%) -- the rest cite a page only and are outside this check

**`relation:published`**
- *B5 Grounding* -- 220/233 citations carry a quote (94%) -- the rest cite a page only and are outside this check

**`relation:licensed_to`**
- *B5 Grounding* -- 8/9 citations carry a quote (89%) -- the rest cite a page only and are outside this check

**`relation:acquired_by`**
- *B5 Grounding* -- 4/5 citations carry a quote (80%) -- the rest cite a page only and are outside this check

**`relation:sold_to`**
- *B5 Grounding* -- 3/6 citations carry a quote (50%) -- the rest cite a page only and are outside this check

## Benchmark labels with no biograph home

The other half of the matrix. A table showing only what biograph can express would hide the gaps this project has to report.

**B1 Biographical - `occupation`** -- No typed home in the schema. entity.subtype is free text and is the literal string 'researcher' for 1393 of 1975 person entities (71%); entity.summary is populated for all 1975 and usually states a profession in prose. Neither is a controlled slot, so occupation is reported N/A and excluded from the macro-average. A separate, clearly-labelled string-match diagnostic against subtype+summary is available and is never folded into the F1.

**B2 BiographicalEvents - `STATE`** -- A TimeML STATE is a static condition. biograph drops those by design: 'an event is a dateable occurrence, not a fact or a description' (schema/README.md). Reported as a measured recall ceiling, not a bug.

**B2 BiographicalEvents - `REP-EVENT`** -- Reporting verbs ('say', 'claim'). biograph has no speech-act type; such sentences yield either nothing or an `other` event.

**B2 BiographicalEvents - `ASP-EVENT`** -- Aspectual verbs ('begin', 'start'). Partially recoverable, since employment_start / employment_end encode aspect in the type itself.

