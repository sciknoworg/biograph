# data/

Source documents are **not committed** to this repository — neither the
original PDFs (`data/*.pdf`) nor the extracted text the pipeline archives
alongside them (`data/*.txt`). Both are gitignored. We don't have
redistribution rights to the source itself, only the right to read and
extract from a copy legitimately obtained.

This holds for automatically discovered open-access sources too, and the
distinction is worth stating plainly: extracting text changes the format,
not the copyright. "Open access" spans everything from CC-BY (redistributable
with attribution) through to free-to-read-only (not redistributable), and
this pipeline records no per-source license field — `sources.json` carries
title, authors, year, publication, DOI and URL, but nothing about
redistribution rights. Publishing the text would need that evidence
per source; until it's collected, the text stays local.

Keeping it locally is not incidental — `data/<slug>.txt` is what the
grounding check re-verifies quotes against, so it has to survive after the
PDF is deleted.

What *is* committed, and what actually matters for reproducibility, is
the citation: every source a subject draws from is fully described in
that subject's own `sources.json` — title, authors, year, publication,
DOI, and URL where available — plus page-level provenance on every
individual event and relation (`sources[].page`; see
[`schema/README.md`](../schema/README.md)). That's what lets a reader
verify a claim without the PDF needing to sit in this repo.

This file is a quick index of what's been handled, without opening every
subject folder.

## Sources handled so far

| Subject | Title | Authors | Year | DOI |
|---|---|---|---|---|
| [`suntola`](../subjects/suntola/) | A Short History of Atomic Layer Deposition: Tuomo Suntola's Atomic Layer Epitaxy | Riikka L. Puurunen | 2014 | [10.1002/cvde.201402012](https://doi.org/10.1002/cvde.201402012) |
| [`aleskovskii`](../subjects/aleskovskii/) | From V. B. Aleskovskii's "Framework" Hypothesis to the Method of Molecular Layering/Atomic Layer Deposition | Anatolii A. Malygin, Victor E. Drozd, Anatolii A. Malkov, Vladimir M. Smirnov | 2015 | [10.1002/cvde.201502013](https://doi.org/10.1002/cvde.201502013) |

Add a row here (and the full entry in the subject's `sources.json`) any
time a new source is added, whether found by hand or by a future
discovery pipeline.

## If you have the PDF locally

`scripts/build_site.py --pdf` expects it at `data/<slug>.pdf` (or
wherever `--pdf` points) and records that path in `sources.json`'s
`file` field. That field documents a **local convention**, not a
guarantee the file is present in the repo — re-running extraction, or
checking a `sources[].page` citation against the original, both need
your own copy of the PDF; neither needs it to be in git.
