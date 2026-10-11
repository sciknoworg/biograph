# Vocabulary coverage matrix

biograph's 22 event types and 27 relation types, read from `schema/`, against the suite's 6 label spaces.

| cell | meaning |
|---|---|
| `*` clean | clean match |
| `~` partial | partial -- information lost, see note |
| `o` residual | no target label; scored only via the catch-all class |
| `-` none | not expressible in this label space |
| `=` untyped | metric is category-free; type participates untyped |

| biograph type | B1 Biographical | B2 BiographicalEvents | B3 WikiLifeTrajectory | B4 WikiBio | B5 EventKG | B6 Grounding |
|---|---|---|---|---|---|---|
| `event:birth` | `*` clean | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:death` | `*` clean | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:education` | `~` partial | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:employment_start` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:employment_end` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:role_change` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:invention` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:patent_filed` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `~` partial |
| `event:patent_granted` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `~` partial |
| `event:publication` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:product_launch` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:public_demonstration` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:conference` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `~` partial |
| `event:visit` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:meeting` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:relocation` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:award` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:company_founded` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:company_sold` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `~` partial |
| `event:company_renamed` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:retirement` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `event:other` | `o` residual | `~` partial | `=` untyped | `~` partial | `=` untyped | `=` untyped |
| `relation:born_in` | `*` clean | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:died_in` | `*` clean | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:lived_in` | `o` residual | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:visited` | `o` residual | `~` partial | `~` partial | `-` none | `=` untyped | `~` partial |
| `relation:relocated_to` | `o` residual | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:worked_at` | `o` residual | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:employed_by` | `o` residual | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:founded` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:member_of` | `o` residual | `~` partial | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:supervised_by` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:mentored` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:collaborated_with` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:met` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:married_to` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:family_of` | `~` partial | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:studied_at` | `*` clean | `~` partial | `~` partial | `-` none | `=` untyped | `=` untyped |
| `relation:educated_by` | `~` partial | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:invented` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:patented` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:published` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:developed` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:awarded` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:licensed_to` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:acquired_by` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:sold_to` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `~` partial |
| `relation:renamed_to` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |
| `relation:corresponded_with` | `o` residual | `-` none | `-` none | `-` none | `=` untyped | `=` untyped |

## Column defaults

**B1 Biographical** -- no target relation; predicted as the `other` class

**B2 BiographicalEvents** -- collapses to TimeML EVENT; scored by trigger anchoring, not type
- all relation types: `none` -- the role inventory is writer-centric; a relation between two third parties has no role to fill

**B3 WikiLifeTrajectory** -- the gold carries no event type; matching is by person, time and place
- all relation types: `none` -- the gold unit is a (person, time, location) triplet, so a relation that carries neither a place nor a date cannot form one

**B4 WikiBio** -- collapses onto the single untyped gold EVENT class; the type itself is never compared
- all relation types: `none` -- the corpus annotates event triggers and target-person mentions only; no relation is annotated

**B5 EventKG** -- recall is name- and date-anchored; no gold row carries a biograph type

**B6 Grounding** -- verified per citation, not per type

## Notes per cell

Only where a cell departs from its column's default.

**`event:birth`**
- *B1 Biographical* -- birthdate: event.date; birthplace: event.location
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:death`**
- *B1 Biographical* -- deathdate: event.date; deathplace: event.location
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:education`**
- *B1 Biographical* -- educatedAt: institution recovered from participants[] role, which is free text, not an enum
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:employment_start`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:employment_end`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:role_change`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:invention`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:patent_filed`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost
- *B6 Grounding* -- 10/14 citations carry a quote (71%) -- the rest cite a page only and are outside this check

**`event:patent_granted`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost
- *B6 Grounding* -- 9/11 citations carry a quote (82%) -- the rest cite a page only and are outside this check

**`event:publication`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:product_launch`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:public_demonstration`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:conference`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost
- *B6 Grounding* -- 101/107 citations carry a quote (94%) -- the rest cite a page only and are outside this check

**`event:visit`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:meeting`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:relocation`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:award`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:company_founded`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:company_sold`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost
- *B6 Grounding* -- 8/11 citations carry a quote (73%) -- the rest cite a page only and are outside this check

**`event:company_renamed`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:retirement`**
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`event:other`**
- *B2 BiographicalEvents* -- collapses to EVENT; the corpus's STATE class has no biograph counterpart at all -- a state is by definition not a dateable occurrence (schema/README.md), so every STATE annotation is an unreachable recall ceiling
- *B4 WikiBio* -- scored as the single untyped gold EVENT class; the type itself has no counterpart and is recorded as lost

**`relation:born_in`**
- *B1 Biographical* -- birthplace
- *B2 BiographicalEvents* -- contributes ARGx-LOC only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:died_in`**
- *B1 Biographical* -- deathplace
- *B2 BiographicalEvents* -- contributes ARGx-LOC only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:lived_in`**
- *B2 BiographicalEvents* -- contributes ARGx-LOC only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:visited`**
- *B2 BiographicalEvents* -- contributes ARGx-LOC only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event
- *B6 Grounding* -- 37/39 citations carry a quote (95%) -- the rest cite a page only and are outside this check

**`relation:relocated_to`**
- *B2 BiographicalEvents* -- contributes ARGx-LOC only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:worked_at`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:employed_by`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:founded`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only
- *B6 Grounding* -- 68/79 citations carry a quote (86%) -- the rest cite a page only and are outside this check

**`relation:member_of`**
- *B2 BiographicalEvents* -- contributes ARGx-ORG only

**`relation:mentored`**
- *B6 Grounding* -- 90/99 citations carry a quote (91%) -- the rest cite a page only and are outside this check

**`relation:met`**
- *B6 Grounding* -- 17/20 citations carry a quote (85%) -- the rest cite a page only and are outside this check

**`relation:family_of`**
- *B1 Biographical* -- ofParent / hasChild / sibling all collapse here. Subtype and direction survive in `note` for 30 of 85 corpus instances (35%): 'Father', 'Mother', 'Brother', 'youngest son'. Reported as combined family-relation recall, with per-subtype figures over the note-bearing subset only, labelled as such

**`relation:studied_at`**
- *B1 Biographical* -- educatedAt
- *B2 BiographicalEvents* -- contributes ARGx-ORG only
- *B3 WikiLifeTrajectory* -- places a person somewhere but carries no time; contributes only when an event_id supplies a dated event

**`relation:educated_by`**
- *B1 Biographical* -- educatedAt is institution-valued; educated_by targets a person, so it is a hit only when the gold sentence names a teacher as the institution

**`relation:patented`**
- *B6 Grounding* -- 2/11 citations carry a quote (18%) -- the rest cite a page only and are outside this check

**`relation:published`**
- *B6 Grounding* -- 220/233 citations carry a quote (94%) -- the rest cite a page only and are outside this check

**`relation:licensed_to`**
- *B6 Grounding* -- 8/9 citations carry a quote (89%) -- the rest cite a page only and are outside this check

**`relation:acquired_by`**
- *B6 Grounding* -- 4/5 citations carry a quote (80%) -- the rest cite a page only and are outside this check

**`relation:sold_to`**
- *B6 Grounding* -- 3/6 citations carry a quote (50%) -- the rest cite a page only and are outside this check

## Benchmark labels with no biograph home

The other half of the matrix. A table showing only what biograph can express would hide the gaps this project has to report.

**B1 Biographical - `occupation`** -- No typed home in the schema. entity.subtype is free text and is the literal string 'researcher' for 1393 of 1975 person entities (71%); entity.summary is populated for all 1975 and usually states a profession in prose. Neither is a controlled slot, so occupation is reported N/A and excluded from the macro-average. A separate, clearly-labelled string-match diagnostic against subtype+summary is available and is never folded into the F1.

**B2 BiographicalEvents - `STATE`** -- A TimeML STATE is a static condition. biograph drops those by design: 'an event is a dateable occurrence, not a fact or a description' (schema/README.md). Reported as a measured recall ceiling, not a bug.

**B2 BiographicalEvents - `REP-EVENT`** -- Reporting verbs ('say', 'claim'). biograph has no speech-act type; such sentences yield either nothing or an `other` event.

**B2 BiographicalEvents - `ASP-EVENT`** -- Aspectual verbs ('begin', 'start'). Partially recoverable, since employment_start / employment_end encode aspect in the type itself.

**B4 WikiBio - `EVENT-GR`** -- Light and grammatical verbs -- annotate HOW an event is expressed rather than that one occurred. Read and counted, never scored.

**B4 WikiBio - `EVENT-MOD`** -- Modality. As EVENT-GR.

**B5 EventKG - `wikipedia:link`** -- Two entities are linked and co-temporal, with no relation type asserted. A large share of the gold. Has no target in any typed vocabulary, biograph's included.

**B5 EventKG - `P170 / P127 / P136`** -- Wikidata creator, owned-by and genre. Properties of works and objects rather than of a life; no biograph relation describes them.

