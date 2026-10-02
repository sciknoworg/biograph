# The pipeline and discovery loop — Approach, part 2

Reads as a continuation of `approach-brief.md`, which covers the data model and the two
mechanical checks. That brief describes what the system produces from **one** document a human
hands it. This one describes how documents are found, and how the loop decides when to stop.
Self-contained; state re-verified at commit `41440f5` (2026-10-02).

---

## 1. Reproducibility boundary — state this early

The pipeline is **not one program**. Two halves, with different visibility, and a paper must not
imply otherwise:

| component | status | what it does |
|---|---|---|
| `build_site.py` | **public, committed** | prompt construction, the LLM call, grounding and completeness checks, validation, rendering |
| `schema/*.json` | **public** | the five schemas, embedded verbatim into the prompt |
| `geocode_places.py`, `find_portraits.py`, `access_report.py` | **public** | enrichment and the access audit |
| `find_sources.py`, `download_sources.py`, `run_pipeline.py` | **private, gitignored** | search, fetch, orchestration |

The reason recorded in `.gitignore` is that the discovery tools are "specifically about finding
copyright-adjacent material", and that "only `build_site.py`'s writes into `subjects/` are the
public, committed output of any of this."

So: **the extraction method and its verification are reproducible from the repository; the
acquisition loop is described but not distributed.** That is a genuine limitation, and it is
better stated than discovered by a reviewer. What *is* re-derivable is the record of what
acquisition did — `access_report.py` reconstructs the whole access table from a local manifest,
so anyone running their own collection gets their own numbers.

## 2. One cycle

```
seed → search → keyword + language filter → download → scope-check + extract (ONE call)
     → validate → canonicalize → enrich → classify → render
```

Each cycle chains three scripts. The sequence is what a person would otherwise run by hand; the
loop's contribution is the seeding, the gating and the stopping rule.

## 3. Two seeding modes, both always active

**Mode 1 — taxonomy bootstrap.** A two-level taxonomy, `{subfield: [names]}`, with 2–3
historically notable people per subfield, generated once per domain **from a single fixed prompt
template**. Using the same template for all nine domains is what makes the cross-domain yield
comparison meaningful rather than an artefact of differently-worded asks.

Before searching, every name is checked **live against `subjects/`** — a name that already has a
folder is skipped, and a subfield whose names are all covered is skipped entirely. The check
runs every cycle against the filesystem rather than a cached flag, so it cannot go stale.

When Mode 1 has nothing productive left, the loop asks an LLM to **propose new subfields** not
already in the taxonomy — the automated form of the hand-run survey prompt — deduplicated,
capped per survey (`--max-new-subfields` 5) and in total (`--max-subfields` 150), and persisted
back into the taxonomy file. This is the mechanism by which the taxonomy grows organically
rather than being fully specified up front. §6 covers when it fires and when it latches off,
which took three attempts to get right.

**Mode 2 — people-graph autoseed.** Every person already named in some subject's `entities.json`
who is not yet a subject becomes a candidate seed, gated on **prominence**: they must be tied to
at least `--min-mentions` (default 2) events plus relations, counted across **all** documents of
the one subject that names them, with incidental family ties (`married_to`, `family_of`)
excluded from the count.

The gate is the interesting part. A single `married_to` is a passing mention, not evidence that
someone has a documentable life; a person recurring across several dated events is. Without it
the loop tries to document every incidentally-mentioned name and the corpus drifts into spouses
and one-line colleagues. The count is computed from data already extracted, so it costs no model
call.

**The family-tie exclusion was measured, not guessed.** Of the people carrying exactly one
relation and no events, 17% were family ties; the rest were `collaborated_with` (95), `mentored`
(53) and `supervised_by` (36) — connections that *are* weak evidence of a documentable career,
where a marriage is not. Only those two types are excluded, because counting them meant "Mrs.
Prandtl" scored exactly as high as a collaborator.

**Mode 2's pool is scoped to the domain being run**, and this is a cost finding worth a sentence.
The pool used to be the whole corpus while the scope gate was one domain's, so a physics run
downloaded and heavy-model scope-checked bacteriologists and physiologists it was always going
to reject — **measured live at 74% of a 717-name pool, with two thirds of that run's rejections
being "wrong field" rather than "not a biography"**. Nothing is lost by scoping it: those people
only ever become subjects on a run whose domain they fit, and that domain harvests them from its
own subjects. Run each collection in turn and the union is the same graph, at roughly a quarter
of the cost.

## 4. Filtering, and where the only real judgment sits

Candidates are pre-filtered **before** download by a keyword genre score plus a **hard language
gate** — a candidate whose reported language is present and not English is rejected outright,
while a missing or unknown language passes (fail-open, matching how the rest of the system
treats a degraded signal). **No model is involved at this stage.**

**The only judgment that matters happens once, on the full document text, inside the extraction
call.** Scope and extraction are a single LLM call: the model has the whole document and the
scope rules in context, so it decides from what the text says rather than from what it knows
about the name. A rejection is cheap — it emits `fits: false` and stops instead of generating a
graph, **12–34s in practice against roughly 2 minutes for a real extraction**.

**Two negative results, both worth reporting, because both are design instincts that failed.**

*A cheap scope pre-filter before expensive extraction.* Removed. It admitted 8 documents the
heavy model then rejected outright — a glaciology survey, an autobiography, a monarch's
historiography, and a paper written *by* its own subject. It was not saving work, only deferring
the same rejection while mislabelling documents on the way. Two-stage cascades are a common
design instinct; this is a measured case where the cheap stage had no discriminative power the
expensive stage lacked.

*An LLM genre classifier at search time.* Also removed. It was a third opinion from a model that
had read nothing but a title and abstract, and it was measurably bad at it: it passed a Bunin
novel, an Olbia terracotta dig, a COVID-in-pregnancy study and a diabetic retinopathy model,
each with an invented justification about "a person's life intertwined with a technology's
development". Its false passes were not free — each became a download and then a full heavy
scope call.

Together these say something sharper than either alone: **on this task, a model given less text
does not give a cheaper version of the same judgment. It gives a different and worse one**, and
it confabulates a justification in the house style while doing so.

## 5. Scope is two layers

*Always on*, for any caller: the document must be a biographical or historical retrospective
essay following a specific person's life **intertwined with a specific technology's
development**.

*Added by `--strict-scope`*, which the pipeline passes and the benchmark harness never does —
four further requirements, any one of which rejects:

1. **English**, judged from the text rather than metadata.
2. **One central figure** — rejecting joint biographies, families, research groups, and
   histories of a field or institution where no single life is followed. The stated test: could
   you write one person's dated life timeline from this document, and is that person
   unambiguously who it is about?
3. **Substantial** — a genuinely prolific contributor, documented well enough to draw a real
   dated timeline from.
4. **In this domain**, judged from what the document says the work was.

Requirement 4's instruction is explicit that eminence in a neighbouring field is not in-scope,
"however distinguished" — which is why the corpus is domain-coherent rather than a general
collection of scientists.

**Requirement 4 comes from the taxonomy, not from the code.** It is passed in by
`--scope-domain`, so discovery and extraction judge the same field and collecting a new domain
needs a new taxonomy file rather than a source edit. This matters for the generalization claim:
the system is not a materials-science tool pointed at a materials taxonomy, it is a
biography-extraction tool whose domain *is* whichever taxonomy it is given.

## 6. Stopping: a plateau, and three attempts to define one

`--run-to-completion` runs cycles back to back until one cycle **creates zero new subjects,
proposes zero new subfields, and searches the exact same set of names as the previous cycle.**
Hard caps are backstops with generous defaults, not review gates — `--max-total-subjects` 100,
`--max-subfields` 150, `--max-cycles` 500, `--max-new-subjects` 5/cycle, `--max-downloads`
20/cycle — so a taxonomy typo cannot exhaust an API budget or a disk overnight.

The third plateau condition is load-bearing. "Zero new subjects this cycle" is not convergence —
a taxonomy name that keeps failing to find a document would keep the loop alive indefinitely,
re-searched every cycle. Requiring the *name set* to be unchanged is what distinguishes a
genuine plateau from a stall. A cycle that raises an unhandled error always reports the name set
as changed: a crash is not evidence that nothing was left to do.

**Getting this right took three corrections, and the sequence is a better methods paragraph than
the final rule is.** Each failure was a different wrong definition of "done":

1. **Survey only when nothing is left to search.** This condition can never be reached: a
   taxonomy name stops being pending only once it becomes a subject, which needs a document that
   both downloads *and* passes scope. Names whose documents are all publisher-403s stay pending
   forever. **Mode 1 sat at the same 64 names for 26 cycles**, with the survey — the only source
   of new names — gated behind something that could not occur.
2. **So also survey when the pool is stale** (same names as last cycle). But gating staleness on
   the pipeline-wide creation count tied Mode 1's progress to Mode 2's: cycle 6 created Humphry
   Davy via Mode 2, so cycle 7 was not judged stale, skipped the survey, found nothing, and the
   convergence check **ended the run with 734 names still unconverted**. Staleness is now about
   Mode 1 alone.
3. **Surveying has to stop when it stops paying.** A field whose biographical literature is thin
   does not announce itself by running out of names — it keeps accepting new subfields forever,
   each with pioneers whose retrospectives were never written or never made open. The computer
   science run did exactly that: **eight consecutive cycles added five subfields apiece and
   produced one subject between them.** Only `--max-subfields` would have stopped it, about ten
   hours later, by measuring the wrong thing.

The fix is `--survey-patience` (default 3): after three consecutive surveys with no subject to
show for them, **taxonomy growth latches off for the rest of the run**. Mode 1 then genuinely
runs out of names, the plateau check sees no subjects, no subfields and an unchanged name list,
and the run converges on its own. The counter is persisted, so a plain re-run resumes converged
rather than quietly re-inflating.

**And it deliberately does not reset on just any subject.** Replaying the computer science run
showed why: cycle 10 produced one subject from a name the taxonomy *already had*, which under a
naive reset would have restarted surveying at cycle 11 and left the run with no termination
condition again. **A subject found from an existing name is not evidence that *surveying* pays.**

Measured cycles to plateau: physics 89, chemistry 83, computer science 11, life sciences 9,
mathematics 8, engineering 7, earth & space 6, agriculture 6. *(Recorded during the runs; the
cycle logs do not attribute cycles to domains cleanly enough to re-derive these at this commit.)*

## 7. Exactly-once, across restarts

Every candidate the pipeline ever downloads is recorded in a manifest, extended with
`extract_status` and slug once extraction has run. A candidate is therefore **downloaded once and
scope-checked once**, across any number of cycles, restarts or separate invocations. This is what
makes the access table (`corpus-and-access-brief.md` §4) a complete census of attempts rather
than a sample: 4,292 entries, each with its outcome.

**A technical failure is not a terminal state, and that distinction is load-bearing.** A timeout,
a dropped connection, or a build that wrote files but failed validation leaves the candidate
eligible again next cycle, up to `--max-extract-attempts`, after which it is marked
`extract_failed_permanent` and left alone. A retry reuses the slug a prior attempt already
claimed, so it overwrites that attempt's folder instead of leaving an orphaned duplicate.

**A circuit breaker separates "this document failed" from "the server is down".** After
`--circuit-breaker-threshold` consecutive technical failures, extraction stops for the rest of
the cycle and the remaining candidates are left *untouched* — not marked failed — for the next
cycle. One clear log line instead of a queue burned one call at a time against an unresponsive
server.

**Content rejections never count toward either.** A scope refusal is a correct, final answer, and
reading the verdict file rather than the filesystem is what makes that work: judging by "does
`subject.json` exist" was a proxy that failed in both directions, because `subject.json` lives
at the person level and outlives any single document. A correct rejection on a slug that already
had a directory looked like "wrote it but validation failed", became a technical failure, and
spent a heavy extraction call on a question the model had already answered — up to
`--max-extract-attempts` times.

## 8. Design decisions that shaped the data, and why

- **No review gate before writing.** Extraction writes straight into `subjects/`. Taken
  deliberately, not overlooked: at this scale a human reading every draft before it lands is not
  possible. The consequences are measured rather than assumed — 2.6% of quotes absent from
  source, and drafts that fail validation are reported as such.
- **Set aside the item, not the document.** When one event or relation cannot be repaired — an
  unusable date, a broken citation — it is written to `events.rejected.json` /
  `relations.rejected.json` with its reason instead of failing the whole subject. 85 such files
  exist. **Thirteen complete extractions were discarded over exactly this** before it existed,
  typically one conference or publication event the model listed without attaching anyone to it.
- **File the subject under the person the document is about**, not the search term that found it.
  The extraction reports `scope.subject_name`, and it routinely differs: this pipeline reaches
  documents by searching for someone who may only be *mentioned* in them, so a Rotblat biography
  surfaced by "Harold Kroto" would otherwise land in `subjects/kroto/`.
- **Credentials never on a command line.** The orchestrator logs every command it runs, so a key
  in `argv` is a key written in plaintext into the log on every cycle and readable by anything
  that can list processes. Keys pass through the child's *environment*; non-secret settings stay
  on `argv` where seeing them in the log is useful. Each child gets only the keys it needs.
- **Enrichment happens at write time.** Geocoding runs as each subject is written, so a subject
  arrives with its map populated rather than waiting for a later sweep. This was a fix: subjects
  created before the step existed rendered an empty map view, which reads as a broken page
  rather than as missing data.
- **Order within post-processing is not cosmetic.** The name is canonicalized *before* source
  metadata is injected, because injection re-renders the page and would otherwise publish
  whichever name variant happened to win; `related_fields` is read *before* the content hints are
  consumed, because the scratch file is deleted on read.

## 9. What this section can and cannot claim

**Can:** that a single fixed taxonomy template across nine domains, with a prominence-gated graph
expansion and a yield-based stopping rule, collected 233 subjects from 1,395 obtained documents
without per-domain hand tuning; that the only model judgment is made once, on full text; and
that **two cheaper-judgment designs were tried and measured as actively harmful**, not merely
unhelpful.

**Cannot:** that the loop is reproducible from the artifact — the orchestration is private.
**Cannot:** that yield differences across domains are purely a property of the field; they
compound with what each domain's literature makes fetchable.
**Cannot:** that "confirmed open access in cycle 1 predicts yield" — see
`corpus-and-access-brief.md` §7; that pattern was not re-derived at this commit.
**Cannot:** that the corpus this loop produced reflects the current prompt. Every subject
predates the completeness rules; see `approach-brief.md` §9.
