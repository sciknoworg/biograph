#!/usr/bin/env python3
"""Aggregate the variability study to the numbers a paper can state.

summarise.py prints one block per cell -- 30 of them -- which is the right granularity for
checking the data and the wrong one for making a claim. This rolls those cells up along the
two axes the study was designed around (condition, document length) and reports the paired
comparisons between conditions.

Three things this deliberately does NOT do.

It does not pool the 30 runs of a condition as 30 independent samples. They are nested:
three draws of each of ten documents. Documents differ far more from each other than draws
of one document differ, so pooling would report between-document variance as if it were
run-to-run variability -- which is the opposite of what the study measures. Every figure
here is computed per document first and then aggregated across the ten.

It does not test significance by assuming normality. n is 10 documents. The comparisons are
exact Wilcoxon signed-rank tests over all 2^10 sign assignments, which needs no distributional
assumption and no scipy, and the per-document win/loss count is printed beside the p-value
because with n=10 that is often the more honest summary.

It does not report wall time as a latency measurement. Runs in this study were launched in
overlapping batches against one rate-limited account, and overlapping runs slowed each other
by a measured 2.5-3.5x. Wall time is reported only as what the study cost to produce.

    python paper_evidence/variability/aggregate.py
    python paper_evidence/variability/aggregate.py --markdown
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import itertools
import json
import os
import statistics
import collections
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
MANIFEST = os.path.join(HERE, "manifest.json")

#: The matching rules live in summarise.py and are imported, not restated. What counts as
#: "the same fact found twice" must have exactly one definition, or two scripts will report
#: different agreement figures for the same runs and both will look defensible.
_spec = importlib.util.spec_from_file_location("_summarise", os.path.join(HERE, "summarise.py"))
_sm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sm)
fold, load_run, keys_of = _sm.fold, _sm.load_run, _sm.keys_of

FIELDS = ("entities", "events", "relations")

#: Printed beside every condition, because "low" and "high" name nothing on their own.
CONDITIONS = {
    "elow":  ("anthropic/claude-fable-5.1", "reasoning effort low"),
    "ehigh": ("anthropic/claude-fable-5.1", "reasoning effort high"),
    "t0":    ("qwen3.5-397b-a17b", "temperature 0"),
}


def jaccard(a: set, b: set) -> float | None:
    u = len(a | b)
    return (len(a & b) / u) if u else None


def mean_pairwise_jaccard(sets: list[set]) -> float | None:
    vals = [j for a, b in itertools.combinations(sets, 2)
            if (j := jaccard(a, b)) is not None]
    return statistics.mean(vals) if vals else None


def agreement(sets: list[set]) -> dict:
    """Core / volatile split over n draws, plus mean pairwise Jaccard.

    `core` is the share of the union that EVERY draw found and `singleton` the share only
    one did. Both depend on n and are not comparable across cells of different size; the
    cells here are all n=3. Jaccard is reported alongside because it is pairwise and so
    does not move with n.
    """
    n = len(sets)
    tally = Counter()
    for s in sets:
        for k in s:
            tally[k] += 1
    union = len(tally)
    if not union:
        return {"union": 0, "core": None, "singleton": None, "jaccard": None, "n": n}
    return {"union": union,
            "core": sum(1 for v in tally.values() if v == n) / union,
            "singleton": sum(1 for v in tally.values() if v == 1) / union,
            "jaccard": mean_pairwise_jaccard(sets),
            "n": n}


def cv(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    mu = statistics.mean(vals)
    return (statistics.stdev(vals) / mu) if mu else None


def wilcoxon_exact(diffs) -> tuple[float | None, int, int]:
    """Two-sided exact Wilcoxon signed-rank. -> (p, n_positive, n_negative).

    Zeros are dropped, which is Wilcoxon's own convention and costs power rather than
    validity. Enumerating 2^n sign assignments is exact and instant at n=10; it would not
    be at n=30, and if this study ever grows a third model the enumeration must be replaced
    rather than left to run.
    """
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return None, 0, 0
    pos = sum(1 for x in d if x > 0)
    neg = n - pos
    if n > 22:
        raise SystemExit("wilcoxon_exact: n=%d is too large to enumerate" % n)
    order = sorted(range(n), key=lambda i: abs(d[i]))
    rank = [0.0] * n
    i = 0
    while i < n:                     # mid-ranks for ties in |d|
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            rank[order[k]] = (i + j) / 2 + 1
        i = j + 1
    w = sum(rank[i] for i in range(n) if d[i] > 0)
    total = sum(rank)
    stat = abs(w - total / 2)
    hit = sum(1 for signs in itertools.product((0, 1), repeat=n)
              if abs(sum(r for r, s in zip(rank, signs) if s) - total / 2) >= stat - 1e-9)
    return hit / 2 ** n, pos, neg


def build(manifest) -> dict:
    """-> {(condition, document): cell}, one cell per group of draws."""
    cells: dict[tuple, dict] = {}
    groups: dict[tuple, list] = {}
    for r in manifest["runs"]:
        if not r.get("validated") or not r.get("output"):
            continue
        groups.setdefault((r["condition"], r["document"]), []).append(r)

    for key, runs in groups.items():
        runs.sort(key=lambda r: r["run"])
        loaded = [keys_of(load_run(r["output"])) for r in runs]
        subjects = []
        for r in runs:
            p = os.path.join(REPO_ROOT, r["output"].replace("/", os.sep), "subject.json")
            try:
                with io.open(p, encoding="utf-8") as f:
                    subjects.append(fold((json.load(f) or {}).get("name")))
            except (OSError, ValueError):
                subjects.append(None)
        qv = sum((r.get("grounding") or {}).get("quotes_verbatim") or 0 for r in runs)
        qc = sum((r.get("grounding") or {}).get("quotes_checked") or 0 for r in runs)
        ep = sum((r.get("grounding") or {}).get("entities_present") or 0 for r in runs)
        ec = sum((r.get("grounding") or {}).get("entities_checked") or 0 for r in runs)
        cells[key] = {
            "runs": runs,
            "n": len(runs),
            "length_class": runs[0].get("length_class"),
            "domain": runs[0].get("domain"),
            "counts": {f: [(r.get("counts") or {}).get(f) for r in runs] for f in FIELDS},
            "mean": {f: statistics.mean([(r.get("counts") or {}).get(f) or 0 for r in runs])
                     for f in FIELDS},
            "cv": {f: cv([(r.get("counts") or {}).get(f) for r in runs]) for f in FIELDS},
            "agree": {f: agreement([k[f] for k in loaded]) for f in FIELDS},
            "verbatim": (qv / qc) if qc else None,
            "entity_presence": (ep / ec) if ec else None,
            "quotes_checked": qc,
            "subject_agrees": len(set(subjects)) == 1 and subjects[0] is not None,
            "wall": [r["wall_seconds"] for r in runs],
        }
    return cells


def integrity(manifest) -> list[str]:
    """Check the manifest against the run folders on disk. -> lines to print.

    This runs before any figure is computed, because a number is only as good as the
    provenance of the rows it came from and this study has already lost some. Two faults
    are detectable from the data and both were present in the 2026-10 run.

    A run index is claimed per CONDITION but merged per (document, run). next_index()
    scans the manifest plus the current condition's own output directory, and claim_run()
    takes the index with mkdir in that same directory -- so two conditions running
    concurrently on one document can both claim index N, each succeeding because nothing
    checks the sibling directories. Both then write a row keyed (document, N), and
    _save_manifest_locked merges on that key, so the second row silently replaces the
    first. The lock makes the write atomic; it cannot make two identical keys distinct.
    Galton run_03 and Hooke run_02 each lost a completed low-effort run this way: the
    extraction is still on disk, its wall time, exit code and grounding are gone.

    A folder with a graph and no row at all is the same loss by whatever route, and is
    reported separately because its cause is not always recoverable from the data.
    """
    out = []
    rows = {}
    for r in manifest["runs"]:
        rows.setdefault((r["document"], r["run"]), []).append(r)

    disk = {}
    runs_root = os.path.join(HERE, "runs")
    for model in sorted(os.listdir(runs_root)) if os.path.isdir(runs_root) else []:
        for cond in sorted(os.listdir(os.path.join(runs_root, model))):
            cdir = os.path.join(runs_root, model, cond)
            if not os.path.isdir(cdir):
                continue
            for doc in sorted(os.listdir(cdir)):
                ddir = os.path.join(cdir, doc)
                if not os.path.isdir(ddir):
                    continue
                for name in sorted(os.listdir(ddir)):
                    if not name.startswith("run_") or not os.path.isdir(
                            os.path.join(ddir, name)):
                        continue
                    idx = int(name[4:])
                    disk[(model, cond, doc, idx)] = os.path.isfile(
                        os.path.join(ddir, name, "entities.json"))

    # 1. every row must have its folder, under its own model/condition/document/index
    missing = [r for r in manifest["runs"] if r.get("output")
               and not os.path.isdir(os.path.join(REPO_ROOT,
                                                  r["output"].replace("/", os.sep)))]
    mislaid = [r for r in manifest["runs"] if r.get("output") and not (
        r["output"].endswith("/%s/run_%02d" % (r["document"], r["run"]))
        and ("/%s/" % r["condition"]) in r["output"]
        and r["model"].replace("/", "_") in r["output"])]
    out.append("rows %d, of which validated %d, empty %d, timed out %d"
               % (len(manifest["runs"]),
                  sum(1 for r in manifest["runs"] if r.get("validated")),
                  sum(1 for r in manifest["runs"] if r.get("empty")),
                  sum(1 for r in manifest["runs"] if r.get("timed_out"))))
    out.append("rows whose output folder is missing: %d" % len(missing))
    out.append("rows whose output path disagrees with their own fields: %d" % len(mislaid))
    for r in missing + mislaid:
        out.append("  !! %s run_%02d %s -> %s" % (r["document"], r["run"],
                                                  r["condition"], r["output"]))

    # 2. one index claimed by more than one condition: the row-overwriting fault
    by_di = {}
    for (model, cond, doc, idx), _g in disk.items():
        by_di.setdefault((doc, idx), set()).add(cond)
    collisions = sorted(k for k, v in by_di.items() if len(v) > 1)
    out.append("run indices claimed by more than one condition: %d" % len(collisions))
    for doc, idx in collisions:
        held = sorted(r["condition"] for r in rows.get((doc, idx), []))
        out.append("  !! %s run_%02d claimed by %s; the manifest kept %s"
                   % (doc, idx, ", ".join(sorted(by_di[(doc, idx)])),
                      ", ".join(held) or "nothing"))

    # 3. a graph on disk that no row describes
    orphans = [(m, c, d, i) for (m, c, d, i), g in sorted(disk.items())
               if g and not any(r["condition"] == c and r["model"].replace("/", "_") == m
                                for r in rows.get((d, i), []))]
    out.append("extractions on disk with no manifest row: %d  (excluded from every figure "
               "below -- their grounding and wall time were never recorded)" % len(orphans))
    for m_, c, d, i in orphans:
        out.append("  !! %s %s run_%02d has entities.json but no row" % (c, d, i))

    # 4. a condition must be ONE setting. The whole point of a condition is that its draws
    # differ only by sampling, so any request field that varies inside one is a confound
    # dressed as a result -- and this study has one: 2 of the 30 high-effort runs were made
    # at max_tokens 64000 and the other 28 at 128000, because the cap was raised mid-study
    # once the long documents were seen to be hitting it. On a short document the two are
    # indistinguishable (nothing it can produce approaches either cap), so the confound is
    # confined to the long documents, where the cap decides whether the reply is truncated
    # and continued. Reported here rather than silently averaged over.
    SETTING = ("model", "base_url", "max_tokens", "temperature", "rules_sha",
               "strict_scope", "inclusion_enforced")
    out.append("")
    for cond in sorted({r["condition"] for r in manifest["runs"] if r.get("validated")}):
        runs = [r for r in manifest["runs"] if r.get("validated") and r["condition"] == cond]
        for field in SETTING + ("effort",):
            if field == "effort":
                vals = [((r.get("extra_body") or {}).get("reasoning") or {}).get("effort")
                        for r in runs]
            else:
                vals = [r.get(field) for r in runs]
            spread = {}
            for v, r in zip(vals, runs):
                spread.setdefault(json.dumps(v, sort_keys=True), []).append(r)
            if len(spread) > 1:
                out.append("  !! condition %s is not one setting: %s varies" % (cond, field))
                for v, rs in sorted(spread.items(), key=lambda kv: -len(kv[1])):
                    byl = collections.Counter(r["length_class"] for r in rs)
                    out.append("       %s = %s on %d run(s) (%s)%s"
                               % (field, v, len(rs),
                                  ", ".join("%d %s" % (n, l) for l, n in sorted(byl.items())),
                                  "" if len(rs) > 3 else ": " + ", ".join(
                                      "%s run_%02d" % (r["document"], r["run"]) for r in rs)))
    # Also state the settings that DID hold across every run, since that is the claim.
    core = {json.dumps(r["core_sha256"], sort_keys=True)
            for r in manifest["runs"] if r.get("validated")}
    out.append("  extraction core hashes across every validated run: %d distinct%s"
               % (len(core), " (identical code throughout)" if len(core) == 1 else
                  " -- RUNS WERE NOT MADE BY THE SAME CODE"))
    out.append("  manifest core_verified=%s, divergences=%s"
               % (manifest.get("core_verified"), manifest.get("divergences")))
    return out


def pct(x, nd=1) -> str:
    return "-" if x is None else ("%.*f%%" % (nd, 100 * x))


def med_range(vals, nd=1) -> str:
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    return "%s [%s-%s]" % (pct(statistics.median(vals), nd),
                           pct(min(vals), nd), pct(max(vals), nd))


def report(cells: dict, md: bool) -> None:
    conds = [c for c in ("elow", "ehigh", "t0") if any(k[0] == c for k in cells)]
    docs = sorted({k[1] for k in cells})
    h1 = (lambda t: print("\n## " + t + "\n")) if md else (
        lambda t: print("\n" + t + "\n" + "=" * len(t)))
    row = (lambda *c: print("| " + " | ".join(str(x) for x in c) + " |")) if md else (
        lambda *c: print("  " + "".join(("%-22s" % x) for x in c)))
    rule = (lambda n: print("|" + "|".join([" --- "] * n) + "|")) if md else (lambda n: None)

    print("# Variability study -- aggregate" if md else "VARIABILITY STUDY -- AGGREGATE")
    n_runs = sum(c["n"] for c in cells.values())
    print("\n%d validated runs, %d cells of n=3, %d documents, %d conditions."
          % (n_runs, len(cells), len(docs), len(conds)))

    h1("Run-to-run spread within a document")
    print("Coefficient of variation of the count, computed within each document over its 3")
    print("draws, then aggregated across the 10 documents. Median [min-max] across documents.")
    print("A CV of 0 would mean every draw returned the same number of items.\n")
    row("condition", "entities", "events", "relations", "what it was")
    rule(5)
    for c in conds:
        cs = [cells[(c, d)] for d in docs if (c, d) in cells]
        row(c, *(med_range([x["cv"][f] for x in cs]) for f in FIELDS),
            CONDITIONS.get(c, ("", "?"))[1])

    h1("Agreement on content, not volume")
    print("Within each document, over its 3 draws: the share of the union of all found items")
    print("that EVERY draw found (core), the share only one draw found (volatile), and the")
    print("mean pairwise Jaccard. Median [min-max] across the 10 documents. Matching is by")
    print("folded name for entities, (type, sort date) for events, and (type, folded")
    print("endpoint names) for relations -- summarise.py's rules, imported not restated.\n")
    for f in FIELDS:
        print("\n%s" % f)
        row("condition", "core", "volatile", "Jaccard", "union (median)")
        rule(5)
        for c in conds:
            cs = [cells[(c, d)] for d in docs if (c, d) in cells]
            row(c,
                med_range([x["agree"][f]["core"] for x in cs]),
                med_range([x["agree"][f]["singleton"] for x in cs]),
                med_range([x["agree"][f]["jaccard"] for x in cs]),
                "%g" % statistics.median([x["agree"][f]["union"] for x in cs]))

    h1("Volume, grounding and subject identity")
    print("Mean count per draw, averaged over documents. Verbatim and entity-presence rates")
    print("are POOLED over every quote in the condition (sum verbatim / sum checked), not a")
    print("mean of per-run rates, so a run that checked 300 quotes is not weighted equally")
    print("with one that checked 20.\n")
    row("condition", "ents/draw", "events/draw", "rels/draw", "verbatim", "ent. present",
        "subject")
    rule(7)
    for c in conds:
        cs = [cells[(c, d)] for d in docs if (c, d) in cells]
        qv = sum((r.get("grounding") or {}).get("quotes_verbatim") or 0
                 for x in cs for r in x["runs"])
        qc = sum((r.get("grounding") or {}).get("quotes_checked") or 0
                 for x in cs for r in x["runs"])
        ep = sum((r.get("grounding") or {}).get("entities_present") or 0
                 for x in cs for r in x["runs"])
        ec = sum((r.get("grounding") or {}).get("entities_checked") or 0
                 for x in cs for r in x["runs"])
        row(c, *("%.1f" % statistics.mean([x["mean"][f] for x in cs]) for f in FIELDS),
            "%s (%d)" % (pct(qv / qc if qc else None), qc),
            pct(ep / ec if ec else None),
            "%d/%d agree" % (sum(1 for x in cs if x["subject_agrees"]), len(cs)))

    h1("Does document length change the picture?")
    print("The ten documents are five short (1,858-5,015 chars) and five long (79,929-85,452),")
    print("one of each per domain. Median across the five documents of each class.\n")
    row("condition", "length", "ents/draw", "entity CV", "entity core", "verbatim")
    rule(6)
    for c in conds:
        for lc in ("short", "long"):
            cs = [cells[(c, d)] for d in docs
                  if (c, d) in cells and cells[(c, d)]["length_class"] == lc]
            if not cs:
                continue
            qv = sum((r.get("grounding") or {}).get("quotes_verbatim") or 0
                     for x in cs for r in x["runs"])
            qc = sum((r.get("grounding") or {}).get("quotes_checked") or 0
                     for x in cs for r in x["runs"])
            cvs = [x["cv"]["entities"] for x in cs if x["cv"]["entities"] is not None]
            row(c, lc, "%.1f" % statistics.median([x["mean"]["entities"] for x in cs]),
                pct(statistics.median(cvs)) if cvs else "-",
                med_range([x["agree"]["entities"]["core"] for x in cs]),
                pct(qv / qc if qc else None))

    h1("Condition against condition, paired by document")
    print("Each comparison pairs the two conditions on the SAME document and tests the ten")
    print("differences. 'wins' counts documents favouring the first condition. p is a")
    print("two-sided exact Wilcoxon signed-rank over all 2^10 sign assignments.\n")
    metrics = {
        "entities/draw": lambda x: x["mean"]["entities"],
        "events/draw": lambda x: x["mean"]["events"],
        "entity CV": lambda x: x["cv"]["entities"],
        "entity core": lambda x: x["agree"]["entities"]["core"],
        "entity Jaccard": lambda x: x["agree"]["entities"]["jaccard"],
        "event Jaccard": lambda x: x["agree"]["events"]["jaccard"],
        "verbatim rate": lambda x: x["verbatim"],
    }
    for a, b in itertools.combinations(conds, 2):
        print("\n%s  vs  %s" % (a, b))
        row("metric", "median A", "median B", "median diff", "wins A/B", "p (exact)")
        rule(6)
        for label, get in metrics.items():
            pairs = [(get(cells[(a, d)]), get(cells[(b, d)])) for d in docs
                     if (a, d) in cells and (b, d) in cells]
            pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
            if len(pairs) < 3:
                continue
            diffs = [x - y for x, y in pairs]
            p, npos, nneg = wilcoxon_exact(diffs)
            big = max(abs(x) for pr in pairs for x in pr) > 1.5
            scale = (lambda v: "%.1f" % v) if big else (lambda v: "%.3f" % v)
            row(label, scale(statistics.median([x for x, _ in pairs])),
                scale(statistics.median([y for _, y in pairs])),
                scale(statistics.median(diffs)),
                "%d/%d" % (npos, nneg),
                "-" if p is None else ("%.4f" % p))

    h1("What the study cost to produce")
    print("Wall time is NOT a latency measurement: runs were launched in overlapping batches")
    print("against one rate-limited account, and overlap slowed runs by a measured 2.5-3.5x.\n")
    row("condition", "median/draw", "slowest draw", "total")
    rule(4)
    for c in conds:
        w = [s for d in docs if (c, d) in cells for s in cells[(c, d)]["wall"]]
        row(c, "%.0fs" % statistics.median(w), "%.0fs" % max(w), "%.1f h" % (sum(w) / 3600))
    print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markdown", action="store_true", help="emit pipe tables")
    args = ap.parse_args(argv)
    with io.open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    print("PROVENANCE CHECK" if not args.markdown else "## Provenance check\n")
    for line in integrity(manifest):
        # Indentation is the structure here -- a nested detail belongs under its finding --
        # so the line is printed as built rather than stripped and re-indented.
        print(("  " + line) if not args.markdown else
              ("" if not line.strip() else "- " + line.strip()))
    cells = build(manifest)
    if not cells:
        raise SystemExit("no validated runs in the manifest")
    sizes = {c["n"] for c in cells.values()}
    if sizes != {3}:
        print("NOTE: cells are not all n=3 (sizes %s); the core and volatile shares depend "
              "on n and are not comparable across differently sized cells." % sorted(sizes))
    report(cells, args.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
