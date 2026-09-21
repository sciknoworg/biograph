# Pilot: where is the scope gate's boundary?

**Run 2026-09-21**, commit `42dde742`, model `qwen3.5-397b-a17b`, extraction core
hash-verified unchanged (8 files). 8 documents, one extraction each, no `--strict-scope`,
no input framing (`transform=()`), `--keep-rejected` throughout.
Report: `experiments/runs/scope_probe_professions/report.json`.

## Why this pilot exists

The PMOA-TTS pilot found the gate refusing a domain wholesale (9/9). But clinical case
reports fail two of `SCOPE_DEFINITION`'s clauses at once — no named subject **and** not a
retrospective essay about technology — so that refusal could not say which clause did the
work. That distinction decides whether the biographical benchmarks (1 and 2) are viable
at all: a refused document produces no output, so every downstream metric reads 0.00 for
reasons that have nothing to do with extraction quality.

This probe varies exactly one thing. Every document is the plain text of an English
Wikipedia biography of a **named person**, truncated to the same 12,000 characters. Only
the subject's field changes. Benchmark 1 (Biographical) is itself Wikipedia-derived, so
this is a faithful genre proxy that touches no dataset whose licence is unresolved.

## Result: the boundary is subject matter, and it is sharp

| slug | field | distance | verdict | events | relations |
|---|---|---|---|---:|---:|
| `woolf` | literature | far | refused | 0 | 0 |
| `kahlo` | art | far | refused | 0 | 0 |
| `owens` | sport | far | refused | 0 | 0 |
| `ellington` | music | far | refused | 0 | 0 |
| `churchill` | politics | far | refused | 0 | 0 |
| `earhart` | aviation | adjacent | **admitted** | 20 | 15 |
| `nightingale` | nursing / statistics | adjacent | **admitted** | 18 | 12 |
| `turing` | computing | control | **admitted** | 31 | 16 |

**Admitted 3/8, and the split is perfect**: 0/5 far, 2/2 adjacent, 1/1 control. The
control passing is what makes the five refusals interpretable — the setup works, so a
refusal is a verdict rather than a misconfiguration.

## Only one clause is doing the work

All five refusals name the *same* clause, verbatim, and none mentions the named-subject
requirement that blocked PMOA-TTS:

> `woolf` — "a general biographical essay about a literary figure, **not a person whose
> life was intertwined with technology development**."
>
> `churchill` — "a general political biography of Winston Churchill, **not** a
> biographical essay about a person whose life was intertwined with a specific
> technology's development."
>
> `owens` — "an athlete whose life centered on track and field competition, **not on the
> development of a specific technology**."

`subject_name` is `null` for all five — nothing is written at all.

The admissions name the same clause, satisfied:

> `earhart` — "life intertwined with **early aviation technology development**."
>
> `nightingale` — "intertwined with development of **modern nursing and statistical data
> visualization**."

So the gate is not asking "is this a biography of a named person?" — all eight are. It is
asking "is this a biography *of a technology*, told through a person?" That is a much
narrower question than "biographical extraction", and it is the single clause that
governs every benchmark decision below.

Nightingale is the informative admission: nursing and data visualisation are not
technology in the engineering sense, and the gate still admitted her on the strength of
"development of" something. The boundary tracks *whether the life produced something*,
not whether the something is a machine.

## Extraction quality on the admitted three

Grounding is checked by the pipeline's own `--check-grounding`, never reimplemented:

| slug | entities | events | relations | quotes verbatim | entity names present | validates |
|---|---:|---:|---:|---|---|---|
| `turing` | 57 | 31 | 16 | 47/47 | 57/57 | yes |
| `earhart` | 44 | 20 | 15 | 33/35 | 44/44 | yes |
| `nightingale` | 65 | 18 | 12 | 30/30 | 65/65 | **no** |

`nightingale` failed schema validation on one event: `event_type: "arrival"`, which is not
among the 22 permitted types. A vocabulary violation, not a scope or grounding failure —
the other 17 events, 12 relations and 65 entities were written, and every quote was
verbatim. Worth carrying as a conformance-rate column: 1 of 3 drafts needed a fix, on 1
of 69 events.

## What this means for each benchmark

- **B1 Biographical** — Wikipedia biographies of arbitrary people. On this evidence the
  gate will refuse the **majority** of them: writers, politicians, athletes, artists and
  musicians are most of any general biography set. B1 is not viable as specified without
  separating the gate from the engine.
- **B2 BiographicalEvents** — same population, same problem.
- **B3 PMOA-TTS** — already refused 9/9, for an additional and more structural reason.
- **B4 TLEX / B5 Grounding** — unaffected; neither depends on admitting new genres.

## The ablation: what the extractor does when the gate is removed

**Run 2026-09-21**, commit `ff7902c`, same 8 documents, `--gate-off` (which passes
`build_site.py --ignore-scope`). The verdict is still requested and still recorded — only
its power to stop the run is removed — so every row below is paired with its gate-on
counterpart above. Report: `experiments/runs/scope_probe_gate_off/report.json`.

| slug | verdict | entities | events | relations | quotes verbatim | entity names | validates |
|---|---|---:|---:|---:|---|---|---|
| `woolf` | UNFIT | 82 | 37 | 39 | 76/76 | 82/82 | yes |
| `kahlo` | UNFIT | 60 | 21 | 18 | 39/39 | 60/60 | yes |
| `owens` | UNFIT | 50 | 27 | 13 | 39/40 | 50/50 | yes |
| `ellington` | UNFIT | 63 | 25 | 36 | 61/61 | 63/63 | yes |
| `churchill` | UNFIT | 57 | 35 | 27 | 62/62 | 57/57 | yes |
| `earhart` | fits | 45 | 35 | 19 | 54/54 | 45/45 | yes |
| `nightingale` | fits | 57 | 18 | 19 | 36/37 | 57/57 | **no** |
| `turing` | fits | 56 | 28 | 25 | 53/53 | 56/56 | yes |

**Produced a graph: 8/8, against 3/8 with the gate on.** The verdict itself did not move —
the same five documents are still judged UNFIT, in the same terms — so this is the gate
being removed, not the model changing its mind.

The result that matters: **the five refused documents extract at the same quality as the
admitted ones.** All five validate. Grounding across all eight is 420/422 quotes verbatim
(99.5%) and 470/470 entity names present (100%); over the five UNFIT documents alone it is
277/278 (99.6%). Churchill yields 35 events and 27 relations from 12,000 characters, all of
it quoted verbatim from the source.

So the genre precondition was the *only* obstacle. The extractor is not specialised to
technology biography in any way that shows up in output quality — it was simply never
allowed to see these documents.

### The one failure is a vocabulary gap, and it reproduces

`nightingale` failed schema validation in **both** conditions, on the same class of error:
invented event types for military movement — `deployment` and `arrival`, neither in the
22-type enum, where `relocation` or `other` would have served. It is the only document in
either run that failed, and it fails identically with the gate on and off, so it is a
property of the vocabulary's coverage of military/organisational life events, not of the
ablation. Worth a conformance column in the paper: 1 of 8 drafts, 2 of 211 events.

## The decision this forces

Two honest papers follow, and they are different papers:

1. **Report the admission policy as the contribution.** Scope-gate attrition becomes a
   headline result: the pipeline is a *technology-biography* extractor and says so,
   refusing out-of-genre input rather than producing plausible wrong output. Defensible,
   and cheap — the evidence is already in this table. But it cannot support a claim of
   domain generality, because the domains were refused.
2. **Separate the gate from the engine.** Add a flag that runs extraction without the
   genre precondition, so the extractor can be measured on documents the gate would
   refuse. This requires modifying `build_site.py`'s prompt construction, which this
   harness is forbidden to do (`experiments/README.md`), and the modified configuration
   would have to be reported as a distinct condition — not as "the pipeline as it runs".

Claim 2 is what "works in principle for other domains" requires. Claim 1 is what the
gate-on artifact supports.

**The ablation above resolves this: both are now available, and they are the same run
reported twice.** `--ignore-scope` exists (commit `ff7902c`), the verdict survives it as
an observation, and the paired table is the evidence for each claim:

- gate on -> the admission policy's attrition, 3/8, with the refusals' own reasons
- gate off -> the extractor's quality on the refused subset, 99.6% grounded, 5/5 valid

Benchmarks 1 and 2 are therefore viable **as a gate-off condition**, reported as such and
never merged with gate-on numbers. What remains before either can be scored is their
output adapter and their data licence, not the gate.

## Reproducing

```bash
python experiments/corpora/fetch_scope_pilot.py
python -m experiments.harness.scope_probe --corpus experiments/corpora/scope_pilot
```

Corpus text is Wikipedia (CC BY-SA 4.0), fetched on demand and never redistributed —
`experiments/corpora/` is gitignored.
