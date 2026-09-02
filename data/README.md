# data/

Source PDFs are **not committed** to this repository (`data/*.pdf` is
gitignored). Both papers handled so far are publisher-hosted (Wiley, in
both current cases) — we don't have redistribution rights to the PDF
itself, only the right to read and extract from a copy legitimately
obtained.

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
