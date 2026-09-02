# Ontology Alignment: Grounding the Taxonomy in Prior Art

`schema/*.schema.json` defines three closed vocabularies from scratch:
four `entity_type` values, twenty-two `event_type` values, and
twenty-seven relation `type` values (§ [Data model reference](data-model.md)).
Before treating that as a novel contribution, it is worth asking plainly:
does the semantic web / cultural-heritage / digital-humanities community
already have an authoritative, citable schema for this? This page answers
that question layer by layer — where an existing standard already covers
a piece of biograph's model exactly, where it covers it partially, and
where none of the reviewed standards cover it at all. The goal is
provenance for the schema itself: reuse the vocabulary where it already
existed, and have a specific, defensible reason for each place it
doesn't.

**Nothing here changes `schema/`.** This is a documented alignment, not a
migration — see [§ Why not just adopt one of these](#why-not-just-adopt-one-of-these-outright)
for why.

## Candidates reviewed

| Source | Governing body / citation | Scope |
|---|---|---|
| **CIDOC-CRM** | ISO 21127:2023; developed by the CIDOC CRM Special Interest Group | The dominant event-centric ontology for cultural-heritage and historical knowledge representation — the closest domain match to "biographical knowledge graph" of anything reviewed. |
| **BIO vocabulary** | Ian Davis & Dan Brickley, [vocab.org/bio/0.1/](https://vocab.org/bio/) | An RDF vocabulary specifically for biographical life-events — genealogy-oriented (birth, marriage, employment, death). |
| **schema.org** | schema.org (Google/Microsoft/Yahoo/Yandex-backed) | General-purpose, web-scale vocabulary; `Person`, `Organization`, `Place`, `Event`, `CreativeWork`. |
| **FOAF** | Dan Brickley & Libby Miller, [xmlns.com/foaf/spec/](http://xmlns.com/foaf/spec/) | General social-graph vocabulary for people, organizations, and agents. |
| **PROV-O** | [W3C Recommendation](https://www.w3.org/TR/prov-o/) | The standard ontology for data provenance: entities, activities, agents, derivation. |
| **Wikidata's property/class model** | Wikimedia Foundation | Already integrated into biograph (`find_portraits.py`'s P569/P18/P625 lookups) — its property vocabulary is the natural next thing to check for relation-type overlap. |
| **Simple Event Model (SEM)** | Van Hage, Malaisé, Segers, Hollink & Schreiber, *"Design and use of the Simple Event Model (SEM)"*, Journal of Web Semantics 9(2), 2011 | A lightweight, domain-agnostic event ontology from the linked-data literature — independent corroboration of the event-Actor-Place-Time pattern. |
| *(noted, not adopted)* WIPO ST.96 | World Intellectual Property Organization | Patent-document XML/metadata standard — the actual authoritative source for patent-specific structure, though document-metadata-oriented rather than knowledge-graph-node-oriented. |

## The event-centric structure itself is not novel — and that's the point

Before the vocabularies: biograph's core structural decision — events as
the join between entities, each event dated, cited, and connecting its
participants via labeled roles (`schema/README.md`'s "Events are the join
between the graph and the timeline") — is not something invented for
this project. It is, verbatim, the "central organizing principle" of
CIDOC-CRM: E5 Event (and its activity subclasses) is *the* mechanism CRM
uses to relate E21 Person, E53 Place, E74 Group, and E71 Human-Made Thing
to one another, rather than connecting them with direct properties. The
same four-class pattern — Event / Actor / Place / Time — is independently
formalized as SEM's entire ontology (`sem:Event`, `sem:Actor`,
`sem:Place`, `sem:Time`, related via `sem:hasActor`/`sem:hasPlace`/`sem:hasTime`).

That two independently-developed ontologies from different communities
(cultural heritage standardization; linked-data/NLP research) converge on
the same shape biograph arrived at independently is worth stating
explicitly in a paper: the *structure* is grounded in established
ontology-engineering practice, even though the specific closed
vocabularies populating that structure are biograph's own. That
structure/vocabulary distinction is what the rest of this page maps out.

## Entities — `entity_type`

| Value | Closest authoritative class(es) | Fit |
|---|---|---|
| `person` | CIDOC-CRM **E21 Person**; schema.org **Person**; FOAF **foaf:Person**; Wikidata **Q5** (human) | Direct, clean match across every source reviewed. |
| `place` | CIDOC-CRM **E53 Place**; schema.org **Place** | Direct match — already the basis of the `attributes.lat`/`lng` + Wikidata P625 verification step. Wikidata has no single canonical "place" class the way it has Q5 for person; places are typed via `P31` against whatever specific class fits (city, country, facility, ...). |
| `organization` | CIDOC-CRM **E74 Group** (with **E40 Legal Body** as a subclass for formally-incorporated entities); schema.org **Organization**; FOAF **foaf:Organization**; Wikidata **Q43229** (organization) | Direct match. |
| `artifact` | Weakest fit of the four. CIDOC-CRM splits "a made thing" across **E71 Human-Made Thing** (physical) and **E28 Conceptual Object** (immaterial) rather than one class, and further splits *making* one across **E12 Production** vs. **E65 Creation** depending on physical/conceptual; schema.org has **CreativeWork** and **Product** but no `Patent` or `Invention` type at all. The actual authoritative standard for patent structure, WIPO ST.96, is a document-metadata schema, not a knowledge-graph class. | No source reviewed treats "the invention/patent/product/publication/award" as one entity category the way biograph's `subtype` field does — this is a place biograph's own domain need (one node per named thing, regardless of what kind of thing) doesn't have a ready-made precedent. |

## Events — `event_type` (22 values)

CIDOC-CRM's own answer to "what should the fixed vocabulary of event
types be" is instructive: **it deliberately doesn't have one.** Only a
handful of structurally distinct event primitives get their own classes
(E67 Birth, E69 Death, E85 Joining, E86 Leaving, E12 Production, E65
Creation — each because it has unique properties, like E67's *P96 by
mother*/*P97 from father*). Every other kind of happening is the generic
E5 Event / E7 Activity, categorized via **P2 has type → E55 Type**, where
E55 Type is explicitly meant to be populated from an external,
domain-specific controlled vocabulary that the *implementing project*
supplies — CRM's specification does not ship one. In other words:
biograph's 22-value `event_type` enum is not a deviation from CIDOC-CRM's
design — it is exactly the kind of artifact CRM's own extension point
(P2/E55) expects a project to define for its own domain.

Where a structurally distinct CIDOC-CRM primitive, or the BIO
vocabulary's person-life-event classes, does exist:

| `event_type` | Precedent |
|---|---|
| `birth` | CIDOC-CRM **E67 Birth**; BIO **bio:Birth** |
| `death` | CIDOC-CRM **E69 Death**; BIO **bio:Death** |
| `retirement` | BIO **bio:Retirement** |
| `employment_start` / `employment_end` | BIO **bio:Employment** — one event, not split into start/end the way biograph's pair is |
| `role_change` | BIO **bio:PositionChange** (BIO further splits this into **bio:Promotion**/**bio:Demotion**, finer-grained than biograph's single value) |
| `company_founded` | BIO **bio:Formation**; structurally, CIDOC-CRM's generic **E65 Creation** of an E74 Group |
| `education` | BIO splits this into **bio:Enrolment** and **bio:Graduation**; biograph keeps one |

Everything else — `invention`, `patent_filed`, `patent_granted`,
`publication`, `product_launch`, `public_demonstration`, `conference`,
`visit`, `meeting`, `company_sold`, `company_renamed`, `award` — has **no
direct class in any source reviewed**. This isn't a coincidence: BIO is a
genealogy vocabulary and simply doesn't model institutional or
technological history at all, and schema.org has no formal event-type
subtyping to speak of. CIDOC-CRM's generic Activity-plus-P2/E55 pattern
is the closest structural fit, but using it still requires exactly the
kind of custom E55 Type vocabulary biograph defines directly as
`event_type`.

## Relations — `type` (27 values, directed)

CIDOC-CRM again prefers to route most of this through an event rather
than a direct property — "X worked at Y" is modeled as an Activity typed
"employment," with *P14 carried out by* connecting the person and *P7
took place at*/*P4 has time-span* anchoring it — which is exactly the
pattern biograph's own `event_id` link on a relation mirrors (a relation
*may* durably summarize an event, rather than always standing alone).
Where CRM does have a small number of direct properties: **P74** has
current or former residence (~ `lived_in`), **P107** has current or
former member (~ `member_of`).

schema.org, by contrast, favors flat properties over event-mediation, and
covers several of these directly: **worksFor** (~ `worked_at`/`employed_by`),
**alumniOf** (~ `studied_at`), **founder** (~ `founded`), **memberOf**
(~ `member_of`), **spouse** (~ `married_to`), **parent**/**children**
(~ `family_of`), **colleague** (~ `collaborated_with`, imperfectly — schema.org's
`colleague` doesn't distinguish a documented professional collaboration
from a general workplace relationship the way biograph's rule of "add one
for every event implying a durable connection" does).

Wikidata's property model — already in use elsewhere in this project —
covers a similar set: **P108** employer (~ `employed_by`/`worked_at`),
**P69** educated at (~ `studied_at`), **P1344** participant in
(~ `met`/`visited`/`conference`-adjacent), **P112** founded by (inverse of
`founded`), **P463** member of (~ `member_of`), **P26** spouse
(~ `married_to`).

**No precedent found** across any source reviewed for: `supervised_by`,
`mentored`, `educated_by` (as a person-to-person relation, distinct from
`studied_at`-to-an-institution), `met`, `corresponded_with`,
`relocated_to`, `licensed_to`, `acquired_by`, `sold_to`, `renamed_to`,
`invented`/`patented`/`published`/`developed`/`awarded` (as directed
person-or-organization → artifact relations), `visited`, `born_in`,
`died_in`. These split into two recognizable buckets: informal
relationship types that general-purpose social vocabularies don't
formalize as directed edges (`mentored`, `collaborated_with`, `met`,
`corresponded_with`), and technology/corporate-history-specific relations
(`licensed_to`, `acquired_by`, `sold_to`, `renamed_to`, the artifact-creation
relations) that sit outside the scope of every vocabulary reviewed,
because none of them targets the history-of-invention/history-of-technology
domain biograph's shipped example (Suntola's Atomic Layer Epitaxy) is
actually drawn from.

## Provenance — `sources[].page` / `sources[].quote`

This is the cleanest alignment in the whole schema, and worth naming
explicitly. A required `(source_id, page)` pair plus an optional `quote`
on every event and relation is structurally the same pattern as PROV-O's
**prov:Entity** related to another **prov:Entity** it was derived from —
specifically **prov:wasDerivedFrom** and **prov:hadPrimarySource** ("a
preceding entity produced by an agent with direct knowledge") — and
overlaps with Dublin Core's **dcterms:source** / **dcterms:bibliographicCitation**.
Unlike the event/relation vocabularies above, this part of biograph's
schema has a direct, authoritative, W3C-Recommendation-level precedent —
worth citing as the actual justification for why `page` is a *required*
field (schema/event.schema.json, schema/relation.schema.json), not an
idiosyncratic house rule.

## Why not just adopt one of these outright

This is the question a reviewer is likely to ask, and the honest answer
from the table above: no single reviewed vocabulary covers biograph's
actual domain — a cited, dated knowledge graph of *history-of-technology*
biography — end to end. CIDOC-CRM covers the entity/event *structure*
precisely but ships no event-type or relation-type vocabulary of its own
by design (P2/E55 exists so a project supplies one). BIO covers a
genealogy-flavored third of the event types and none of the institutional
or invention-history ones. schema.org and Wikidata cover the person/place/organization
entities and several social/employment relations well, since both are
general-purpose and web-scale, but neither has any concept for a patent,
an invention, or a technology license. Adopting any one of them wholesale
would mean either bolting on a large amount of project-specific
vocabulary anyway (so CIDOC-CRM, minimally) or losing the precision the
domain needs (schema.org/FOAF, which have no representation for roughly
half of biograph's relation types at all). The approach taken instead:
reuse the *pattern* these ontologies converge on (event-centric,
provenance-required), and where a specific value is needed that none of
them define, define it directly and note that explicitly, rather than
force-fitting a nearby but semantically different existing term.

## Summary for citation

> Biograph's structural design — a dated, cited event joining typed
> entities via role-labeled participants — follows the event-centric
> pattern that is CIDOC-CRM's (ISO 21127) central organizing principle,
> independently corroborated by the Simple Event Model (Van Hage et al.,
> 2011). Its entity typing (person/place/organization) aligns directly
> with CIDOC-CRM, schema.org, FOAF, and Wikidata; its provenance model
> (a required source page citation per fact) follows the PROV-O pattern
> of an entity derived from and attributed to a primary source. Its
> event- and relation-type vocabularies were defined directly rather than
> reused, because the domain — cited biography of invention and
> institutional history — sits at the intersection of several existing
> vocabularies' scopes (cultural heritage, genealogy, general web
> entities) without falling squarely inside any one of them; where a
> reviewed vocabulary's own design (CIDOC-CRM's E55 Type extension point)
> explicitly anticipates a project supplying its own domain vocabulary,
> that is what was done.

## References

- ISO 21127:2023, *Information and documentation — A reference ontology
  for the interchange of cultural heritage information* (CIDOC-CRM).
  [cidoc-crm.org](https://cidoc-crm.org/)
- Davis, I. & Brickley, D. *BIO: A vocabulary for biographical
  information*, v0.1. [vocab.org/bio/](https://vocab.org/bio/)
- Schema.org. [schema.org/Person](https://schema.org/Person),
  [schema.org/Organization](https://schema.org/Organization)
- Brickley, D. & Miller, L. *FOAF Vocabulary Specification*.
  [xmlns.com/foaf/spec/](http://xmlns.com/foaf/spec/)
- W3C. *PROV-O: The PROV Ontology*, W3C Recommendation.
  [w3.org/TR/prov-o/](https://www.w3.org/TR/prov-o/)
- Van Hage, W.R., Malaisé, V., Segers, R., Hollink, L. & Schreiber, G.
  "Design and use of the Simple Event Model (SEM)." *Journal of Web
  Semantics*, 9(2), 2011.
- Wikidata property documentation, e.g.
  [P108](https://www.wikidata.org/wiki/Property:P108) (employer),
  [P69](https://www.wikidata.org/wiki/Property:P69) (educated at).
- WIPO. *ST.96: Recommendation for the Processing of Intellectual
  Property Information Using XML*.
