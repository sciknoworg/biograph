# Pilot: does the scope gate admit a clinical case report?

**Run 2026-09-17.** 3 documents from `case_study_100`, each extracted under all three
input framings, against the standing extraction configuration. 9 extractions, no
`--strict-scope`, `--keep-rejected` throughout.

## Result: 9 of 9 refused. Framing made no difference.

| framing | in scope | events | relations | event recall |
|---|---:|---:|---:|---:|
| `none` (report as published) | 0/3 | 0 | 0 | 0.00 |
| `minimal` (one-line genre header) | 0/3 | 0 | 0 | 0.00 |
| `biographical` (framed as a medical biography) | 0/3 | 0 | 0 | 0.00 |

`subject_name` came back `null` for all nine. Wall time 17.5–208.8 s; exit code 1 in
every case (`extract()`'s out-of-scope `sys.exit`, before anything is written).

## The refusals name two independent blockers

Taking the reasons verbatim, the same two clauses recur across every framing:

> "This is a medical case report about an **anonymous patient's** surgical treatment, not
> a biographical or historical retrospective essay following a **specific person's life
> intertwined with technology development**."

**1. No named subject** (7/9 say "anonymous" or "anonymized"; others say "a named
person", "a specific person", "a notable person"). `SCOPE_DEFINITION` requires a document
that follows *a specific person's* life. Clinical case reports are de-identified by
construction — this is a property of the entire genre, and of medical publishing ethics,
not of how the document is introduced. No input framing can supply a named subject
without fabricating one.

**2. Genre** (8/9 mention "intertwined with technology development"). A case report is
not a retrospective essay written about someone.

The first blocker is the structural one. biograph is a *subject-centric* extractor: a
subject is a person, the folder layout is keyed by their slug, `subject_entity()` finds
"the most connected person", and portraits and geocoding both hang off named identity.
A narrative with no nameable protagonist has nothing for that architecture to attach to.

## What this means for the paper

The result is not "biograph extracts clinical timelines badly". It is that the pipeline
**never reaches the extractor**: a genre admission policy sits in front of it and refuses
the domain wholesale. Benchmark 3 as specified therefore measures the policy, not the
engine, and returns 0.00 on every metric.

That is a sharper architectural finding than a recall number would have been, and it is
reportable as-is: *scope-gate attrition, PMOA-TTS: 100% (9/9), invariant to input
framing.* It also explains why the other four benchmarks matter differently — three of
them are biographical in genre and will clear the gate.

Separating the two components — admission policy and extraction engine — is what would be
needed to put a recall number on the engine, and that requires a change to
`build_site.py`'s prompt construction, which this harness is forbidden to make. See
`experiments/README.md`; the decision belongs to the project, not to the harness.

## Reference band for when a number does exist

From `--ceiling` (no model calls; both released annotators over the cases they share,
n=40):

| matcher | event recall | concordance | AULTC |
|---|---:|---:|---:|
| embedding (published setting, cosine distance < 0.1) | 0.931 | 0.878 | 0.696 |
| Levenshtein (the reference implementation's fallback) | 0.824 | 0.852 | 0.613 |

The published 0.80 / 0.95 was measured against a clinician set that is not distributed
and cannot be reproduced; this band can be.
