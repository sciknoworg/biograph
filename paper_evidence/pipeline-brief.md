# The pipeline and discovery loop — Approach, part 2

Reads as a continuation of `approach-brief.md`, which covers the data model and the grounding
check. That brief describes what the system produces from **one** document a human hands it.
This one describes how documents are found, and how the loop decides when to stop.
Self-contained; state at commit `46bae4f` (2026-09-29).

---

## 1. Reproducibility boundary — state this early

The pipeline is **not one program**. Two halves, with different visibility, and a paper must
not imply otherwise:

| component | status | what it does |
|---|---|---|
| `build_site.py` | **public, committed** | prompt construction, the LLM call, grounding check, validation, rendering |
| `schema/*.json` | **public** | the five schemas, embedded verbatim into the prompt |
| `geocode_places.py`, `find_portraits.py`, `access_report.py` | **public** | enrichment and the access audit |
| `find_sources.py`, `download_sources.py`, `run_pipeline.py` | **private, gitignored** | search, fetch, orchestration |

The reason recorded in `.gitignore` is that the discovery tools are "specifically about
finding copyright-adjacent material", and that "only `build_site.py`'s writes into
`subjects/` are the public, committed output of any of this."

So: **the extraction method and its verification are reproducible from the repository; the
acquisition loop is described but not distributed.** That is a genuine limitation, and it is
better stated than discovered by a reviewer. What *is* re-derivable is the record of what
acquisition did — `access_report.py` reconstructs the whole access table from a local
manifest, so anyone running their own collection gets their own numbers.

## 2. One cycle

```
seed → search → filter → download → scope-check + extract (one call) → validate → render → enrich
```

Each cycle chains three scripts. The sequence is what a person would otherwise run by hand;
the loop's contribution is the seeding, the gating and the stopping rule.

## 3. Two seeding modes, both always active

**Mode 1 — taxonomy bootstrap.** A two-level taxonomy, `{subfield: [names]}`, with 2–3
historically notable people per subfield, generated once per domain **from a single fixed
prompt template**. Using the same template for all nine domains is what makes the
cross-domain yield comparison meaningful rather than an artefact of differently-worded asks.

Before searching, every name is checked live against `subjects/` — a name that already has a
folder is skipped, and a subfield whose names are all covered is skipped entirely. The check
runs every cycle against the filesystem rather than a cached flag, so it cannot go stale.

When nothing is left to bootstrap, the loop asks an LLM to **propose new subfields** not
already in the taxonomy — the automated form of the hand-run survey prompt — deduplicated,
capped per survey and in total, and persisted back into the taxonomy file. This is the
mechanism by which the taxonomy grows organically rather than being fully specified up front.

**Mode 2 — people-graph autoseed.** Every person already named in some subject's
`entities.json` who is not yet a subject becomes a candidate seed, gated on **prominence**:
they must be tied to at least `--min-mentions` (default 2) events plus relations *within the
one subject that names them*, with incidental family ties (`married_to`, `family_of`)
excluded from the count.

The gate is the interesting part. A single "married_to" is a passing mention, not evidence
that someone has a documentable life; a person recurring across several dated events is.
Without it, the loop tries to document every incidentally-mentioned name and the corpus
drifts into spouses and one-line colleagues. The count is computed from data already
extracted, so it costs no model call.

## 4. Filtering, and where the only real judgment sits

Candidates are pre-filtered **before** download by a keyword genre score plus a **hard
language gate** — a candidate whose reported language is present and not English is
rejected outright, while a missing or unknown language passes (fail-open, matching how the
rest of the system treats a degraded signal). **No model is involved at this stage.**

**The only judgment that matters happens once, on the full document text, inside the
extraction call.** Scope and extraction are a single LLM call: the model has the whole
document and the scope rules in context, so it decides from what the text says rather than
from what it knows about the name. A rejection is cheap — it emits `fits: false` and stops
instead of generating a graph.

**A negative result worth reporting.** There was once a separate lightweight scope
pre-filter, on the theory that cheap rejection before expensive extraction would save work.
It was removed: it admitted 8 documents the heavy model then rejected outright — a glaciology
survey, an autobiography, a monarch's historiography, and a paper written *by* its own
subject. It was not saving work, only deferring the same rejection while mislabelling
documents on the way. Two-stage cascades are a common design instinct; this is a measured
case where the cheap stage had no discriminative power the expensive stage lacked.

## 5. Scope is two layers

*Always on*, for any caller: the document must be a biographical or historical retrospective
essay following a specific person's life **intertwined with a specific technology's
development**.

*Added by `--strict-scope`*, which the pipeline passes and the benchmark harness never does —
four further requirements, any one of which rejects: **English**; **one central figure**
(rejecting joint biographies, research groups, and field histories where no single life is
followed); **substantial** (a prolific contributor, documented well enough to draw a dated
timeline from); and **in this domain**, judged from what the document says the work was.

Requirement 4's instruction is explicit that eminence in a neighbouring field is not
in-scope, "however distinguished" — which is why the corpus is domain-coherent rather than a
general collection of scientists.

## 6. Stopping: a plateau, not a cap

`--run-to-completion` runs cycles back to back until one cycle **creates zero new subjects,
proposes zero new subfields, and searches the exact same set of names as the previous
cycle.**

The third condition is the load-bearing one. "Zero new subjects this cycle" is not
convergence — a taxonomy name that keeps failing to find a document would keep the loop alive
indefinitely, re-searched every cycle. Requiring the *name set* to be unchanged is what
distinguishes a genuine plateau from a stall.

Hard caps exist (`--max-total-subjects`, `--max-subfields`, `--max-cycles`,
`--max-new-subjects`, `--max-downloads`) but they are **backstops with generous defaults, not
review gates** — they exist so a taxonomy typo cannot exhaust an API budget or a disk
overnight. Measured cycles to plateau: physics 89, chemistry 83, computer science 11,
mathematics 8, life sciences 9, engineering 7, earth & space 6, agriculture 6.

## 7. Exactly-once, across restarts

Every candidate the pipeline ever downloads is recorded in a manifest, extended with
`extract_status` and slug once extraction has run. A candidate is therefore **downloaded once
and scope-checked once**, across any number of cycles, restarts or separate invocations. This
is what makes the access table (`corpus-and-access-brief.md` §4) a complete census of attempts
rather than a sample: 4,292 entries, each with its outcome.

## 8. Design decisions that shaped the data, and why

- **No review gate before writing.** Extraction writes straight into `subjects/`. Taken
  deliberately, not overlooked: at this scale a human reading every draft before it lands is
  not possible. The consequences are measured rather than assumed — 2.6% of quotes absent from
  source, and drafts that fail validation are reported as such.
- **Set aside the item, not the document.** When one event or relation cannot be repaired —
  an unusable date, a broken citation — it is written to `events.rejected.json` /
  `relations.rejected.json` with its reason instead of failing the whole subject. 85 such
  files exist. The alternative loses a good extraction over one bad row; a dateless event once
  cost an entire subject before this existed.
- **Credentials never on a command line.** The orchestrator logs every command it runs, so a
  key in `argv` is a key written in plaintext into the log on every cycle and readable by
  anything that can list processes. Keys pass through the child's *environment*; non-secret
  settings stay on `argv` where seeing them in the log is useful. Each child gets only the
  keys it needs.
- **Enrichment happens at write time.** Geocoding runs as each subject is written, so a
  subject arrives with its map populated rather than waiting for a later sweep. This was a
  fix: subjects created before the step existed rendered an empty map view, which reads as a
  broken page rather than as missing data.

## 9. What this section can and cannot claim

**Can:** that a single fixed taxonomy template across nine domains, with a prominence-gated
graph expansion and a plateau stopping rule, collected 233 subjects from 1,395 obtained
documents without per-domain hand tuning; that the only model judgment is made once, on full
text; and that the cheap-prefilter cascade was tried and measured as useless here.

**Cannot:** that the loop is reproducible from the artifact — the orchestration is private.
**Cannot:** that yield differences across domains are purely a property of the field; they
compound with what each domain's literature makes fetchable.
**Cannot:** that "confirmed open access in cycle 1 predicts yield" — see
`corpus-and-access-brief.md` §7; that pattern was not re-derived at this commit.
