"""The vocabulary coverage matrix: biograph's 22 event types and 27 relation types
against the five benchmarks' label spaces.

This is a design document that happens to be executable. It is generated, not written by
hand, for two reasons: the row labels come from schema/ so the table can never drift from
the data model it describes, and the benchmark-5 column is measured from the corpus so
the grounding column reports what is actually citable rather than what ought to be.

    python -m experiments.harness.coverage            markdown, to stdout
    python -m experiments.harness.coverage --latex    LaTeX booktabs, for the paper
    python -m experiments.harness.coverage --csv      one row per (type, benchmark)

Cell vocabulary -- five values, not three, because "partial" was carrying too much:

    clean     1:1 with a benchmark label; nothing is lost in the projection.
    partial   maps, with a named loss: a three-way collapse, a direction that has to be
              recovered from free text, a precision mismatch.
    residual  the benchmark has no label for this, but does have a catch-all (the
              `other` class in Biographical). Predicting `other` here is CORRECT when
              the gold is `other`, so these rows are scored -- they just cannot ever
              earn credit for a target relation. Distinguished from `none` because
              conflating them would make the `other` class look like a gap.
    none      not expressible in this benchmark's label space at all. Contributes to
              Prediction.unmapped and to nothing else.
    untyped   the benchmark's metric does not use categories. The type participates in
              scoring without being type-matched. Three of the five benchmarks are like
              this, which is the point: the taxonomy risk is concentrated in two of
              them, and generalization is tested by the three that never touch it.

The asymmetric half of the matrix -- benchmark labels with no biograph home -- is in
UNMAPPED_BENCHMARK_LABELS below and printed underneath the table. A coverage matrix that
only shows what biograph can express would hide exactly the gap this project needs to
report (Biographical's `occupation`).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

from . import vocab

CELLS = {
    "clean":    ("*", "clean match"),
    "partial":  ("~", "partial -- information lost, see note"),
    "residual": ("o", "no target label; scored only via the catch-all class"),
    "none":     ("-", "not expressible in this label space"),
    "untyped":  ("=", "metric is category-free; type participates untyped"),
}

E = "event:"
R = "relation:"


# --------------------------------------------------------------------------
# 1. Biographical (Plum et al. 2022, SIGIR) -- sentence-level relation extraction.
#    Label space: birthdate, birthplace, deathdate, deathplace, occupation, ofParent,
#    educatedAt, hasChild, sibling, other.
#
#    The two dated relations are not relations in biograph at all: birthdate and
#    deathdate live in events.json as event_type birth/death with a FuzzyDate, so the
#    output adapter reads them from there. birthplace/deathplace have two possible
#    sources -- the born_in/died_in relation (152 and 64 in the corpus) and the birth /
#    death event's own `location` field (52.6% and 26.5% populated) -- and the adapter
#    takes their union, since a benchmark sentence states the fact once and either
#    route finding it is a hit.

BIOGRAPHICAL = {
    "column": "B1 Biographical",
    "default": "residual",
    "default_note": "no target relation; predicted as the `other` class",
    "cells": {
        E + "birth": ("clean", "birthdate: event.date; birthplace: event.location"),
        E + "death": ("clean", "deathdate: event.date; deathplace: event.location"),
        E + "education": ("partial", "educatedAt: institution recovered from participants[] "
                                     "role, which is free text, not an enum"),
        R + "born_in": ("clean", "birthplace"),
        R + "died_in": ("clean", "deathplace"),
        R + "studied_at": ("clean", "educatedAt"),
        R + "educated_by": ("partial", "educatedAt is institution-valued; educated_by "
                                       "targets a person, so it is a hit only when the "
                                       "gold sentence names a teacher as the institution"),
        R + "family_of": ("partial", "ofParent / hasChild / sibling all collapse here. "
                                     "Subtype and direction survive in `note` for 30 of "
                                     "85 corpus instances (35%): 'Father', 'Mother', "
                                     "'Brother', 'youngest son'. Reported as combined "
                                     "family-relation recall, with per-subtype figures "
                                     "over the note-bearing subset only, labelled as such"),
        R + "married_to": ("residual", "Biographical has no spouse relation; `other`"),
    },
    "unmapped_labels": {
        "occupation": "No typed home in the schema. entity.subtype is free text and is "
                      "the literal string 'researcher' for 1393 of 1975 person entities "
                      "(71%); entity.summary is populated for all 1975 and usually states "
                      "a profession in prose. Neither is a controlled slot, so occupation "
                      "is reported N/A and excluded from the macro-average. A separate, "
                      "clearly-labelled string-match diagnostic against subtype+summary "
                      "is available and is never folded into the F1.",
    },
}


# --------------------------------------------------------------------------
# 2. Guidelines and a Corpus for Extracting Biographical Events (ISA 2022,
#    arXiv 2206.03547). Label space is NOT a biographical event taxonomy: it is a
#    subset of ISO-TimeML classes -- EVENT, STATE, ASP-EVENT, REP-EVENT -- plus
#    writer-centric SemAF roles (writer-ARG0, writer-ARGx, ARGx-LOC, ARGx-ORG,
#    ARGM-TIME).
#
#    So all 22 biograph event types collapse onto a single label. Scoring is
#    trigger-anchored: did an event get extracted whose span/label aligns with the
#    annotated trigger token, with the subject as a participant and a date attached.
#    Type accuracy is not measurable against this corpus in either direction, and the
#    matrix says so rather than inventing a correspondence.

BIOEVENTS = {
    "column": "B2 BiographicalEvents",
    "default": "partial",
    "default_note": "collapses to TimeML EVENT; scored by trigger anchoring, not type",
    "cells": {
        E + "other": ("partial", "collapses to EVENT; the corpus's STATE class has no "
                                 "biograph counterpart at all -- a state is by definition "
                                 "not a dateable occurrence (schema/README.md), so every "
                                 "STATE annotation is an unreachable recall ceiling"),
        R + "born_in": ("partial", "contributes ARGx-LOC only"),
        R + "died_in": ("partial", "contributes ARGx-LOC only"),
        R + "lived_in": ("partial", "contributes ARGx-LOC only"),
        R + "visited": ("partial", "contributes ARGx-LOC only"),
        R + "relocated_to": ("partial", "contributes ARGx-LOC only"),
        R + "worked_at": ("partial", "contributes ARGx-ORG only"),
        R + "employed_by": ("partial", "contributes ARGx-ORG only"),
        R + "member_of": ("partial", "contributes ARGx-ORG only"),
        R + "founded": ("partial", "contributes ARGx-ORG only"),
        R + "studied_at": ("partial", "contributes ARGx-ORG only"),
    },
    "relation_default": ("none", "the role inventory is writer-centric; a relation "
                                 "between two third parties has no role to fill"),
    "unmapped_labels": {
        "STATE": "A TimeML STATE is a static condition. biograph drops those by design: "
                 "'an event is a dateable occurrence, not a fact or a description' "
                 "(schema/README.md). Reported as a measured recall ceiling, not a bug.",
        "REP-EVENT": "Reporting verbs ('say', 'claim'). biograph has no speech-act type; "
                     "such sentences yield either nothing or an `other` event.",
        "ASP-EVENT": "Aspectual verbs ('begin', 'start'). Partially recoverable, since "
                     "employment_start / employment_end encode aspect in the type itself.",
    },
}


# --------------------------------------------------------------------------
# 3. PMOA-TTS (arXiv 2505.20323) + the relative-timeline framework (arXiv 2504.12350).
#    (event, time) tuples, event text free-form, time in hours from presentation.
#    The published metric matches events by cosine distance between S-PubMedBert
#    embeddings and never compares categories, so every biograph type participates
#    untyped. This is why it is the first adapter built: it exercises the whole
#    input/output path with no taxonomy mapping to debug at the same time.

PMOA_TTS = {
    "column": "B3 PMOA-TTS",
    "default": "untyped",
    "default_note": "event text matched by embedding distance; type never compared",
    "cells": {},
    "relation_default": ("none", "the corpus is (event, time) tuples; relations.json has "
                                 "no counterpart and is not projected"),
}


# --------------------------------------------------------------------------
# 4. TLEX (arXiv 2406.05265). Consumes a TimeML temporal graph and returns exact
#    timelines. biograph has no TLINKs, so the adapter derives interval relations from
#    sort_start/sort_end -- which means the graph is consistent by construction and
#    TLEX's consistency check is trivially satisfied. The informative output is
#    indeterminacy: how much of a timeline is genuinely unordered because the source
#    only gave a year. That is a property of date PRECISION, not of event type, so the
#    per-type column is uniform and the real table is the precision one below.

TLEX = {
    "column": "B4 TLEX",
    "default": "untyped",
    "default_note": "ordering only; type never compared",
    "cells": {},
    "relation_default": ("none", "TLEX consumes the timeline, which build() renders from "
                                 "events.json alone. Relation start/end dates are "
                                 "populated for at most 21.5% of any relation type "
                                 "(worked_at) and are not part of the timeline"),
}


# --------------------------------------------------------------------------
# 5. Grounding / FActScore-adapted. Not an external dataset: build_site.py
#    --check-grounding, applied to a sample of subjects/ and to benchmark-derived
#    subjects, read as closed-book atomic-claim verification. The column is MEASURED
#    from the corpus: a type whose citations rarely carry a quote is a type this check
#    cannot speak for, and that varies by type from 18% to 100%.

GROUNDING = {
    "column": "B5 Grounding",
    "default": "untyped",
    "default_note": "verified per citation, not per type",
    "cells": {},          # filled by measure_quote_coverage()
    "quote_threshold": 0.95,
}


COLUMNS = [BIOGRAPHICAL, BIOEVENTS, PMOA_TTS, TLEX, GROUNDING]


# --------------------------------------------------------------------------- measured

def measure_quote_coverage(subjects_glob: str | None = None) -> dict[str, tuple[int, int]]:
    """Per-type share of source citations that carry a verbatim-checkable quote.

    `quote` is optional in the schema ('only for pivotal events, not every one'), so the
    grounding check's reach is an empirical property of the corpus, not a guarantee. It
    is 94-100% for every common type and as low as 18% for `patented` (n=11)."""
    root = subjects_glob or os.path.join(vocab.REPO_ROOT, "subjects")
    counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for kind, key in (("events", "event_type"), ("relations", "type")):
        for path in glob.glob(os.path.join(root, "**", f"{kind}.json"), recursive=True):
            try:
                with open(path, encoding="utf-8") as f:
                    items = json.load(f)
            except (OSError, ValueError):
                continue
            prefix = E if kind == "events" else R
            for item in items:
                if not isinstance(item, dict):
                    continue
                row = prefix + str(item.get(key))
                for cite in item.get("sources") or []:
                    counts[row][1] += 1
                    if isinstance(cite, dict) and (cite.get("quote") or "").strip():
                        counts[row][0] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def _grounding_cells() -> dict[str, tuple[str, str]]:
    measured = measure_quote_coverage()
    out = {}
    for row in vocab.all_types():
        quoted, total = measured.get(row, (0, 0))
        if not total:
            out[row] = ("none", "not present in the corpus; nothing to verify")
            continue
        rate = quoted / total
        cell = "untyped" if rate >= GROUNDING["quote_threshold"] else "partial"
        note = f"{quoted}/{total} citations carry a quote ({rate:.0%})"
        if cell == "partial":
            note += " -- the rest cite a page only and are outside this check"
        out[row] = (cell, note)
    return out


# --------------------------------------------------------------------------- build

def build() -> tuple[list[str], list[dict], list[str]]:
    rows = list(vocab.all_types())
    GROUNDING["cells"] = _grounding_cells()

    table = []
    problems = []
    for row in rows:
        entry = {"type": row}
        for col in COLUMNS:
            if row in col["cells"]:
                cell, note = col["cells"][row]
            elif row.startswith(R) and col.get("relation_default"):
                cell, note = col["relation_default"]
            else:
                cell, note = col["default"], col["default_note"]
            if cell not in CELLS:
                problems.append(f"{col['column']}/{row}: unknown cell {cell!r}")
            entry[col["column"]] = (cell, note)
        table.append(entry)

    known = set(rows)
    for col in COLUMNS:
        for row in col["cells"]:
            if row not in known:
                problems.append(f"{col['column']} maps {row!r}, which is not in schema/ "
                                f"-- the matrix has drifted from the data model")
    return rows, table, problems


# --------------------------------------------------------------------------- render

def to_markdown() -> str:
    rows, table, problems = build()
    heads = [c["column"] for c in COLUMNS]
    out = ["# Vocabulary coverage matrix", "",
           f"biograph's {len(vocab.event_types())} event types and "
           f"{len(vocab.relation_types())} relation types, read from `schema/`, against "
           f"the five benchmarks' label spaces.", "",
           "| cell | meaning |", "|---|---|"]
    out += [f"| `{sym}` {name} | {desc} |" for name, (sym, desc) in CELLS.items()]
    out += ["", "| biograph type | " + " | ".join(heads) + " |",
            "|---|" + "---|" * len(heads)]
    for entry in table:
        cells = [f"`{CELLS[entry[h][0]][0]}` {entry[h][0]}" for h in heads]
        out.append(f"| `{entry['type']}` | " + " | ".join(cells) + " |")

    # A note that applies to every row of a column belongs to the column, not to 49
    # repetitions of itself, so both kinds of default are stated once here and then
    # suppressed from the per-row list below.
    out += ["", "## Column defaults", ""]
    boilerplate = set()
    for col in COLUMNS:
        out.append(f"**{col['column']}** -- {col['default_note']}")
        boilerplate.add(col["default_note"])
        if col.get("relation_default"):
            cell, note = col["relation_default"]
            out.append(f"- all relation types: `{cell}` -- {note}")
            boilerplate.add(note)
        out.append("")

    out += ["## Notes per cell", "",
            "Only where a cell departs from its column's default.", ""]
    for entry in table:
        notes = {h: entry[h][1] for h in heads
                 if entry[h][0] in ("clean", "partial", "none")
                 and entry[h][1] not in boilerplate}
        if notes:
            out.append(f"**`{entry['type']}`**")
            out += [f"- *{h}* -- {n}" for h, n in notes.items()]
            out.append("")

    out += ["## Benchmark labels with no biograph home", "",
            "The other half of the matrix. A table showing only what biograph can "
            "express would hide the gaps this project has to report.", ""]
    for col in COLUMNS:
        for label, why in (col.get("unmapped_labels") or {}).items():
            out.append(f"**{col['column']} - `{label}`** -- {why}")
            out.append("")

    if problems:
        out += ["## PROBLEMS", ""] + [f"- {p}" for p in problems]
    return "\n".join(out)


def to_csv() -> str:
    rows, table, _ = build()
    lines = ["biograph_type,benchmark,cell,note"]
    for entry in table:
        for col in COLUMNS:
            cell, note = entry[col["column"]]
            lines.append(f'"{entry["type"]}","{col["column"]}","{cell}","{note}"')
    return "\n".join(lines)


def to_latex() -> str:
    rows, table, _ = build()
    heads = [c["column"].split(" ", 1)[0] for c in COLUMNS]
    sym = {k: {"clean": r"$\bullet$", "partial": r"$\circlefillleft$", "residual": r"$\circ$",
               "none": r"--", "untyped": r"$\square$"}[k] for k in CELLS}
    out = [r"\begin{tabular}{l" + "c" * len(heads) + "}", r"\toprule",
           "biograph type & " + " & ".join(heads) + r" \\", r"\midrule"]
    for entry in table:
        cells = [sym[entry[c["column"]][0]] for c in COLUMNS]
        out.append(r"\texttt{" + entry["type"].replace("_", r"\_") + "} & "
                   + " & ".join(cells) + r" \\")
    out += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--latex", action="store_true")
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    text = to_latex() if args.latex else to_csv() if args.csv else to_markdown()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text + "\n")
    _, _, problems = build()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
