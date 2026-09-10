# Reading the biographical record

This project builds knowledge graphs from retrospective essays, obituaries and
memorial articles about scientists. That work has a precondition nobody states:
the documents have to be *readable by a machine*. Most of them are not.

Every document the pipeline has ever tried to fetch is recorded in
`.pipeline_manifest.json`, along with what came back. `scripts/access_report.py`
turns that record into a report:

```bash
python3 scripts/access_report.py              # the report
python3 scripts/access_report.py --markdown   # as Markdown tables
```

The manifest is local and gitignored — it records file paths and search history —
so the script is committed and the data is not. Anyone running this pipeline
generates their own numbers from their own runs.

## What this corpus found

Across five domains — materials science, chemistry, physics, computer science,
and the Earth and space sciences — the pipeline attempted **3,122 documents and
obtained 968 of them: 31%.**

The rest were refused, and how they were refused varies by publisher:

| Publisher | Obtained | Refused | 403 | HTML instead of PDF |
|---|---:|---:|---:|---:|
| Wiley | **0** | 246 | 246 | 0 |
| Springer | 1 | 101 | 0 | 101 |
| IOP | 11 | 98 | 0 | 98 |
| Oxford University Press | **0** | 85 | 85 | 0 |
| MDPI | **0** | 76 | 76 | 0 |
| Elsevier (ScienceDirect) | **0** | 55 | 55 | 0 |
| ACS | **0** | 51 | 51 | 0 |
| Taylor & Francis | **0** | 46 | 46 | 0 |
| Nature | **0** | 46 | 0 | 46 |
| AIP / Physics Today | **0** | 45 | 19 | 26 |
| ACM | 2 | 34 | 34 | 0 |
| **Royal Society** | **0** | 22 | 22 | 0 |

And what worked:

| Source | Obtained | Refused |
|---|---:|---:|
| Cambridge University Press | 71 | 12 |
| CORE | 61 | 146 |
| arXiv | 38 | **0** |
| J-Stage | 21 | **0** |
| Frontiers | 20 | **0** |
| PLOS | 18 | **0** |
| Copernicus (*History of Geo- and Space Sciences*) | 11 | **0** |

## What this does and does not show

**It does not show that all of this is paywalled**, and saying so would overstate
a case that does not need it. MDPI is a fully open-access publisher and still
returned 403 to all 76 attempts; that can only be bot-blocking. Springer, IOP,
Nature and PubMed Central mostly returned HTML landing pages rather than refusing
outright — the document may well be readable by a human at that address.

The defensible claim is narrower, and still substantial:

> These documents are open to a human and closed to a machine.

The requests were not disguised. `scripts/download_sources.py` sends a
descriptive `User-Agent` naming the project, its repository and a contact
address, exactly as the politeness conventions of every one of these services
ask. It was refused anyway, 954 times with an outright 403.

## Why it matters for this kind of work

The 31% figure is not the interesting number on its own. What matters is *which*
31%, because the effect is not random.

The one journal most precisely on target for this project — the Royal Society's
*Biographical Memoirs of Fellows of the Royal Society*, which exists for no other
purpose than recording the lives of scientists — refused every single attempt.
The Earth and space sciences domain converged at 8 subjects not because the
biographical literature is thin, but because the discovery engines kept finding
it in Wiley and Royal Society journals and the pipeline could not read a word.

Compare computing, which failed differently and instructively: its documents
downloaded fine and were then rejected as out of scope, because computing's
history is written collectively — "the history of ALGOL", three-founder
narratives — rather than as individual lives. One field is unreachable; the other
is reachable but not biographical. Only the first is a publishing decision.

A corpus of the history of science can only be built from what a machine may
read. Open access that does not survive automated retrieval is not open in any
sense this work can use.

## Reproducing it

Run the report against your own manifest after any run. The provider table ranks
by documents refused and only lists providers with at least `--min-attempts`
(default 10) attempts, so a single unlucky link never appears as a finding.
Per-domain outcomes at the end show what happened to documents that *were*
obtained — how many became subjects, and therefore how much of the loss is access
and how much is scope.
