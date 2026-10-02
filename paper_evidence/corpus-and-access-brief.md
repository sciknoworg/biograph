# The corpus and the access findings — condensed brief for the WWW paper

Third companion to `approach-brief.md` and `harness-brief.md`. Self-contained: assumes no access
to the repository. Every figure re-derived at commit `41440f5` (2026-10-02). Figures carry their
denominators; anything not independently verified says so.

---

> ## The corpus predates the current prompt
>
> **Read this before citing any count below.** The completeness rules landed at `a155c27`
> (2026-09-29) and **no commit has touched `subjects/` since** — so every one of the 233 subjects
> was extracted under a prompt that did not ask for completeness. Re-running the same two
> documents under the current prompt yields **1.8–3.6× more entities**
> (`findings-brief.md` §2).
>
> **What is unaffected:** subject and document counts, domain composition, the access table (§4),
> the geocoding and portrait coverage (§5), and every grounding figure — those describe the data
> that exists and the documents that were fetched.
>
> **What is affected:** entity, event and relation *volume*, and anything derived from it
> (entities per document, type distributions, graph density). Report these as produced under the
> earlier prompt. `approach-brief.md` §9 lays out the three options and recommends simply saying
> so.

## 1. What the corpus is

**233 subjects across 260 documents and 9 domains: 5,545 entities, 3,714 events, 2,941
relations.** One subject is one person; each document about that person gets its own folder, and
accounts are merged only at render time.

| domain | subjects |
|---|---:|
| physics | 60 |
| chemistry | 44 |
| life sciences & medicine | 43 |
| materials science | 33 |
| mathematics & computation | 24 |
| engineering | 11 |
| computer science | 9 |
| earth & space sciences | 8 |
| agriculture & food technology | 1 |

Entity composition: person 1,975 · organization 1,663 · artifact 1,058 · place 849.

Date precision across 3,714 events: year 2,448 · day 538 · month 299 · range 235 · decade 78 ·
circa 78 · season 36 · century 2. **Two thirds of the record is year-precision**, which is a
property of the sources rather than of the extractor, and it constrains every temporal claim the
corpus can support.

Provenance: **6,678 citations, 6,516 carrying a verbatim quote (97.6%)**. The 162 without one are
all in two document folders — the two founding subjects, extracted before quotes became
mandatory at `36d289b`. **258 of 260 documents are at 100%.** See `approach-brief.md` §4.1; do
not describe `quote` as optional.

## 2. How it was built

An autonomous discovery loop, run per domain, each cycle: search → filter → download →
scope-check + extract (one call) → validate → render → enrich. Full account in
`pipeline-brief.md`.

**Two seeding modes.**
- *Mode 1 (taxonomy bootstrap)* — a two-level field/subfield taxonomy with 2–3 historically
  notable names per subfield, generated once per domain from a single fixed prompt template. The
  same template for every domain is what makes cross-domain comparison meaningful.
- *Mode 2 (people-graph autoseed)* — persons already extracted into the graph become search seeds
  when they clear a prominence gate: at least 2 events or relations *within the subject that
  mentions them*, excluding incidental family ties (`married_to`, `family_of`), so a one-line
  mention of a spouse does not become a search target.

**Stopping is yield-based, not capped.** `--survey-patience` (default 3) latches taxonomy growth
off after three consecutive surveys that produce no new subject; Mode 1 then runs out of names
and the run converges on its own. Hard caps exist but are backstops. Cycles run per domain:
physics 89, chemistry 83, computer science 11, life sciences 9, mathematics 8, engineering 7,
earth & space 6, agriculture 6. *(Recorded during the runs; not re-derivable at this commit.)*

**Scope is filtered in two layers**, and they must not be conflated — only the first is active
for a human running the tool by hand, or for the benchmark harness.

*Always on* (`SCOPE_DEFINITION`, in the prompt on every call): the document must be a
**biographical or historical retrospective essay following a specific person's life intertwined
with a specific technology's development**, by a historian or domain scientist, long enough to
extract dated life events from. A tribute, obituary, festschrift or memoir written about them by
someone else counts. This is the binding constraint; see `approach-brief.md` §6 for its measured
boundary.

*Added only by `--strict-scope`*, which the automated pipeline passes — four further
requirements, any one of which rejects: **English**, **one central figure**, **substantial**, and
**in this domain** (supplied by the taxonomy, not hardcoded).

So the corpus was collected under all five constraints, while the ablation results in
`harness-brief.md` were produced under the first alone.

## 3. Selection biases — state these before anyone asks

The corpus is not a sample of the history of science. Four filters shape it, and each is
measurable rather than speculative:

- **Open access only.** A document the pipeline cannot fetch cannot enter the corpus. 33% of
  attempts succeeded (§4), so roughly two thirds of the identified literature is absent.
- **English only.** Requirement 1. Non-anglophone biographical scholarship is excluded by
  construction.
- **Technology-biography only**, and it is narrow: a controlled probe refused 0/5 biographies of
  writers, artists, athletes, musicians and politicians while admitting 2/2 in aviation and
  nursing/statistics (`approach-brief.md` §6).
- **Inversely biased against fame.** Re-verified at this commit: **Einstein, Curie, Darwin,
  Leibniz, Lovelace, Newton, Pasteur, Bohr, Feynman, Maxwell and Faraday are all absent** from
  the 233. Tesla and Edison are present, and arrived via the *engineering* domain rather than as
  scientists. The mechanism is that retrospective, open-access biographical essays about the very
  famous are comparatively rare — they are written as books, which are not open — while a
  mid-career materials chemist is more likely to be commemorated in an open-access tribute or
  festschrift.

That last point is the most interesting one for a WWW audience: **the accessible biographical
record is not the canonical one.** What a machine can assemble from open literature is a
different history of science from the one in textbooks.

## 4. The access findings

Every document the pipeline ever tried to fetch is recorded in a local manifest;
`scripts/access_report.py` re-derives the table, so the claim can be checked against another run
rather than taken on trust.

**4,292 documents attempted. 1,395 obtained (33%).**

| outcome | count | share |
|---|---:|---:|
| `failed_permanent` | 1,746 | 40.7% |
| **downloaded** | **1,395** | **32.5%** |
| `skipped_no_url` | 451 | 10.5% |
| `failed` (transient) | 437 | 10.2% |
| duplicate | 257 | 6.0% |
| never attempted | 6 | 0.1% |

**How refusals were expressed** (n = 2,136):

| mechanism | count | share |
|---|---:|---:|
| 403 refused | 1,240 | 58.1% |
| HTML where a PDF was advertised | 590 | 27.6% |
| 404 missing | 140 | 6.6% |
| timeout / connection reset | 14 | 0.6% |
| other | 152 | 7.1% |

**By provider** (≥10 attempts, ranked by refusals):

| provider | obtained | refused | 403 | HTML | 404 |
|---|---:|---:|---:|---:|---:|
| onlinelibrary.wiley.com | **0** | 297 | 297 | 0 | 0 |
| core.ac.uk | 96 | 182 | 56 | 0 | 108 |
| academic.oup.com | **0** | 137 | 137 | 0 | 0 |
| link.springer.com | 1 | 128 | 0 | 128 | 0 |
| iopscience.iop.org | 11 | 105 | 0 | 105 | 0 |
| mdpi.com | **0** | 103 | 103 | 0 | 0 |
| sciencedirect.com | **0** | 76 | 76 | 0 | 0 |
| ncbi.nlm.nih.gov | **0** | 70 | 0 | 70 | 0 |
| nature.com | **0** | 65 | 0 | 65 | 0 |
| pubs.acs.org | **0** | 56 | 56 | 0 | 0 |
| tandfonline.com | 1 | 56 | 56 | 0 | 0 |
| ieeexplore.ieee.org | 1 | 42 | 2 | 0 | 1 |
| dl.acm.org | 2 | 36 | 36 | 0 | 0 |
| royalsocietypublishing.org | **0** | 26 | 26 | 0 | 0 |
| **cambridge.org** | **111** | 13 | 1 | 3 | 9 |

And the other side of the ledger — providers that refused nothing: arXiv 41/0, Frontiers 33/0,
PLOS 27/0, SciELO 15/0, Copernicus 12/0, plus several university repositories (Toronto 11/0, Iowa
11/0) and JCI 10/0. J-Stage 23 obtained against 1 refusal, OSTI 13/10.

**Cambridge is the sharpest single row in the table and belongs in the paper.** 111 obtained
against 13 refusals, 9 of which are 404s — a broken index, not a policy. It is the second-largest
single source of the corpus and it sits in the same table as Wiley's 0/297. Same kind of
publisher, same kind of content, opposite posture toward an identified robot. **The variable is
policy, not business model**, and one row demonstrating that is worth more than the aggregate.

### Reading this honestly — the framing the paper must use

**A 403 is a refusal of an identified robot, not proof of a paywall.** MDPI is fully open access
and still refuses 103 of 103. Collapsing these numbers into "paywalled" would overstate a case
that does not need it, and a reviewer who knows MDPI's model would catch it immediately.

The three failure kinds are different claims:
- **403** — an active policy decision about automated clients.
- **HTML, not PDF** — a landing page, paywall interstitial or consent wall. The document may well
  be readable by a human at that exact address.
- **404** — a broken link in the index. Neither policy nor paywall; belongs in neither column.

**The defensible claim is narrower than "paywalled" and still substantial: these documents are
open to a human and closed to a machine. A corpus cannot be built from literature that only
renders in a browser.** That is the sentence to build the publisher argument on.

### Conversion: obtained documents to subjects

| domain | staged | subjects | rate |
|---|---:|---:|---:|
| life sciences & medicine | 159 | 59 | 37% |
| mathematics & computation | 96 | 26 | 27% |
| agriculture & food technology | 4 | 1 | 25% |
| engineering | 50 | 11 | 22% |
| earth & space sciences | 46 | 8 | 17% |
| physics | 387 | 59 | 15% |
| materials science | 65 | 8 | 12% |
| computer science | 94 | 9 | 10% |
| *architecture probe* | 2 | 0 | 0% |
| *military/naval probe* | 1 | 0 | 0% |

**Caveat that must travel with this table.** It sums to 181 subjects against the corpus's 233,
and the per-domain figures do not match §1 (materials science: 8 here, 33 there). Two causes: the
earliest materials-science work predates the manifest's domain tracking, and a subject keeps the
folder of whichever domain reached it first, so manifest attribution and folder layout diverge.
**Use §1 for corpus composition and this table only for conversion rates within a domain's own
run.** Do not present them as one consistent breakdown.

The two probes are informative precisely because they produced nothing: architecture and
construction technology, and military and naval technology, were each surveyed and yielded 0
subjects.

## 5. Secondary coverage, with provenance tiers

Both enrichments record *how* each value was obtained, so weak results are auditable rather than
invisible.

**Geocoding — 800 of 849 place entities (94.2%)**, resolved against Wikidata P625 with the QID
stored beside the coordinates. Basis distribution: `country` 515 · `most_linked` 219 ·
`document` 57 · `historical_most_linked` 8 · `historical_document` 1. **Two thirds of pins are
country-level**, which matters for how a map figure may be captioned — it is a coverage map, not
a "where the work happened" map. The 49 unmapped are mostly not gazetteer entries at all
(`Oxford PV facility`, `Merchiston Campus`, `North of Sweden`).

**Portraits — 150 person entities across 137 of 233 subjects.** Two tiers, and the split is the
interesting part: **145 `birth_year_verified`** (the candidate's Wikidata P569 matches a birth
event already in that subject's own data — purely mechanical, no model call) against only **5
`description_verified`** (an LLM judges whether a candidate's Wikidata description is specific
enough, used only when no birth year settles it). A third tier, `unverified`, is defined as
unusable and must not be used to attach a photo.

Almost all identity confirmation is therefore mechanical rather than model-judged, which is the
claim worth making. 13 subjects fail the birth-year check — including Yuan Longping, where
Wikidata's P569 says 1929 while its own description says 1930–2021 — and are deliberately left
without a portrait rather than matched loosely.

## 6. Known data-quality issues

- **The corpus predates the current prompt.** See the callout at the top and
  `approach-brief.md` §9. This is the largest open validity question in the paper, and it is a
  writing decision rather than a bug.
- **19 subjects (41 documents) have unverifiable source provenance** — their staged text was
  overwritten by a filename collision, fixed forward at `aa60af1`. See `approach-brief.md` §7.1.
  The manifest records DOI, URL and provider, so some fraction is re-fetchable; nothing has been
  attempted.
- **2.6% of quotes are absent from their source in any form** (139 of 5,394), with 10.2% more
  present but not verbatim. `approach-brief.md` §7. This is an **upper bound**: five subjects
  whose quotes all fail while 80–100% of their entity names are present carry 35% of the flagged
  quotes, and those are document mismatch rather than invention.
- **A numeric trap in the grounding report.** `subjects_with_an_unverified_quote` is **139** and
  the count of quotes absent in any form is **also 139**. Unrelated quantities: 139 of 214 scored
  subjects contain at least one unverified quote; 139 of 5,394 quotes are absent. Do not let one
  number do both jobs.
- **Vocabulary gaps surface as validation failures.** The 22-type event enum has no slot for
  military or organisational movement; a model extracting a Nightingale biography invented
  `deployment` and `arrival` and the draft failed validation. Reproduced in both scope
  conditions, so it is a coverage gap rather than a sampling artefact.
- **`entity.subtype` is free text**, and is the literal string `'researcher'` for 1,393 of 1,975
  person entities (71%) — it is not a controlled vocabulary and should not be described as one.

## 7. Must not be claimed

- **Entity, event or relation volume as current-prompt output.** The callout at the top.
- **"Paywalled."** Say *refused to an automated client*. MDPI refuses 103/103 while being fully
  open access.
- **`quote` as optional**, or citation reach below 100% as a schema property. §1.
- **The per-domain conversion table as a corpus breakdown.** §4.
- **"Confirmed open access in cycle 1 predicts domain yield."** This pattern was recorded during
  the runs and is directionally consistent with §4's conversion table, but the cycle logs do not
  attribute cycles to domains cleanly, so the specific pairs were **not re-derived at this
  commit**. Either re-derive them from the per-domain logs before citing, or cite the conversion
  table instead.
- **A map of where the work happened.** Two thirds of pins are country centroids.
- **The corpus as representative** of the history of science. §3.

## 8. How to re-derive

```bash
python scripts/access_report.py --markdown --min-attempts 10
python scripts/pipeline_status.py
python scripts/geocode_places.py --review     # lists every weakly-resolved pin
python -m experiments.harness.cli --benchmark grounding
```

The manifest and the staged source text are local and gitignored — the manifest records file
paths and search history, and the text carries redistribution questions the project has not
resolved. **The script travels and the data does not**, which is the point: the access claim is
re-derivable by anyone running their own collection rather than being a table to take on trust.
