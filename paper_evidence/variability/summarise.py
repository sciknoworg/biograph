#!/usr/bin/env python3
"""Summarise run-to-run variability: spread in volume, and agreement on content.

Counts are the shallow measure. "Entity counts ranged 15-41" sounds alarming and says
almost nothing, because it cannot distinguish two situations that matter very differently
to a paper:

  a) every draw extracts a different set of facts        -- the method is unreliable
  b) every draw extracts the same core and differs in    -- the method is reliable, and
     how much peripheral detail it volunteers               volume is a verbosity artefact

So this reports both: the spread in counts, and how many items are common to ALL draws
versus how many appear in only one. That distinction is the finding.

Matching is deliberately generous, because the question is whether two draws found the same
*fact*, not whether they spelled it identically:

  entities   folded name, or any alias matching another run's name
  events     (event_type, date.sort_start) -- the type and when it happened
  relations  (type, folded source name, folded target name)

A stricter key would inflate disagreement by counting "Helsinki University of Technology"
against "Helsinki University of Technology (HUT / TKK)" as two different findings.

    python paper_evidence/variability/summarise.py
    python paper_evidence/variability/summarise.py --markdown
"""
from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "manifest.json")


def fold(s) -> str:
    flat = "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                   if not unicodedata.combining(c))
    return " ".join(flat.casefold().split())


def load_run(rel_out: str) -> dict:
    root = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                        rel_out.replace("/", os.sep))
    out = {}
    for name in ("entities", "events", "relations"):
        p = os.path.join(root, name + ".json")
        try:
            with io.open(p, encoding="utf-8") as f:
                out[name] = [i for i in json.load(f) if isinstance(i, dict)]
        except (OSError, ValueError):
            out[name] = []
    return out


def keys_of(run: dict) -> dict[str, set]:
    names = {e.get("id"): e.get("name") for e in run["entities"]}
    ents = set()
    for e in run["entities"]:
        ents.add(fold(e.get("name")))
    evs = set()
    for ev in run["events"]:
        d = ev.get("date") or {}
        evs.add((ev.get("event_type"), d.get("sort_start")))
    rels = set()
    for r in run["relations"]:
        rels.add((r.get("type"), fold(names.get(r.get("source"))),
                  fold(names.get(r.get("target")))))
    return {"entities": ents, "events": evs, "relations": rels}


def spread(vals) -> str:
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    return "%d-%d (median %g)" % (min(vals), max(vals), statistics.median(vals))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)

    with io.open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)

    # Grouped by (document, MODEL, temperature, prompt). Two conditions over one document are two
    # distributions and must never be pooled -- and the COMMIT is part of the condition,
    # because the prompt itself changes between commits. Grouping on temperature alone silently
    # pooled five runs made before the completeness rules with five made after, which differ by
    # 3.6x in entity count: the pooled figure described neither prompt. The model is in the key
    # for the same reason -- a five-model comparison pooled into one block describes no model.
    # The prompt is identified by rules_sha where a run recorded one, because a commit that
    # touches nothing in the prompt should not split a condition in two.
    by_doc: dict[tuple, list] = {}
    for r in manifest["runs"]:
        by_doc.setdefault((r["document"], r.get("model"), r.get("temperature"),
                           r.get("rules_sha") or r["commit"][:7]), []).append(r)

    for (doc, model, temp, prompt), runs in sorted(
            by_doc.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2] or 0, kv[0][3])):
        doc = "%s  (%s, temperature %g, prompt %s)" % (
            doc, model or "model?", temp if temp is not None else -1, prompt)
        runs.sort(key=lambda r: r["run"])
        print("\n" + "=" * 78)
        print("%s -- %d run(s) of %s" % (doc, len(runs), runs[0]["model"]))
        print("=" * 78)

        print("\n%-5s %7s %7s %7s %7s %10s %9s" %
              ("run", "ents", "events", "rels", "wall", "quotes", "valid"))
        for r in runs:
            c, g = r.get("counts") or {}, r.get("grounding") or {}
            qv, qc = g.get("quotes_verbatim"), g.get("quotes_checked")
            rate = ("%d/%d %.0f%%" % (qv, qc, 100 * qv / qc)) if qc else "-"
            print("%-5d %7s %7s %7s %6.0fs %10s %9s" %
                  (r["run"], c.get("entities"), c.get("events"), c.get("relations"),
                   r["wall_seconds"], rate, "yes" if r.get("validated") else "NO"))

        print("\nspread")
        for field in ("entities", "events", "relations"):
            print("  %-10s %s" % (field, spread([(r.get("counts") or {}).get(field)
                                                 for r in runs])))
        rates = [100 * (r["grounding"]["quotes_verbatim"] / r["grounding"]["quotes_checked"])
                 for r in runs if (r.get("grounding") or {}).get("quotes_checked")]
        if rates:
            print("  %-10s %.0f-%.0f%% (median %.0f%%)"
                  % ("verbatim", min(rates), max(rates), statistics.median(rates)))
        print("  %-10s %.0f-%.0fs" % ("wall", min(r["wall_seconds"] for r in runs),
                                      max(r["wall_seconds"] for r in runs)))

        # --- the part that matters: do the draws agree on content?
        loaded = [keys_of(load_run(r["output"])) for r in runs if r.get("output")]
        n = len(loaded)
        if n < 2:
            continue
        print("")
        print("dispersion (sample sd, n-1; CV = sd/mean, comparable across metrics)")
        print("  %-12s %8s %8s %9s %7s" % ("", "mean", "sd", "variance", "CV"))
        series = {
            "entities": [(r.get("counts") or {}).get("entities") for r in runs],
            "events": [(r.get("counts") or {}).get("events") for r in runs],
            "relations": [(r.get("counts") or {}).get("relations") for r in runs],
            "verbatim %": [100 * r["grounding"]["quotes_verbatim"] / r["grounding"]["quotes_checked"]
                           for r in runs if (r.get("grounding") or {}).get("quotes_checked")],
            "wall s": [r["wall_seconds"] for r in runs],
        }
        for label, vals in series.items():
            vals = [v for v in vals if v is not None]
            if len(vals) < 2:
                continue
            mu = statistics.mean(vals)
            sd = statistics.stdev(vals)
            print("  %-12s %8.1f %8.2f %9.1f %6.1f%%"
                  % (label, mu, sd, statistics.variance(vals), 100 * sd / mu if mu else 0))

        print("\nagreement across %d draws (how many draws each item appears in)" % n)
        print("  %-10s %6s %8s %8s %8s" % ("", "union", "in all", "in >=half", "in one"))
        for field in ("entities", "events", "relations"):
            tally = Counter()
            for keys in loaded:
                for k in keys[field]:
                    tally[k] += 1
            union = len(tally)
            in_all = sum(1 for v in tally.values() if v == n)
            in_half = sum(1 for v in tally.values() if v >= (n + 1) // 2)
            in_one = sum(1 for v in tally.values() if v == 1)
            print("  %-10s %6d %8d %8d %8d   core %.0f%% of union"
                  % (field, union, in_all, in_half, in_one,
                     100 * in_all / union if union else 0))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
