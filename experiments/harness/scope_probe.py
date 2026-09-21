"""Measure the scope gate alone: which documents does SCOPE_DEFINITION admit?

This is not a benchmark -- there is no gold and nothing is scored. It answers the
question that has to be settled before any biographical benchmark is worth building:
the extraction prompt carries a genre precondition, and a document it refuses produces
no output at all, so every downstream metric would read 0.00 for a reason that has
nothing to do with extraction quality.

PMOA-TTS already showed the gate refusing a domain wholesale (9/9, see
docs/pmoa-tts-scope-pilot.md). But case reports fail two of SCOPE_DEFINITION's clauses
at once -- no named subject, and not a retrospective essay about technology -- so a
refusal there cannot tell you which clause did the work. This probe varies one thing:
the subject's field, across documents that are all biographies of named people from one
source in one format.

It uses the same Sandbox and Runner as a real benchmark, so the pipeline it measures is
the pipeline the paper describes, hash-verified against the repository afterward.

    python -m experiments.harness.scope_probe --corpus experiments/corpora/scope_pilot
    python -m experiments.harness.scope_probe --corpus <dir> --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import os
import time

from . import sandbox
from .interface import BenchmarkDoc
from .runner import ModelConfig, Runner

REPO_ROOT = sandbox.REPO_ROOT


def load_corpus(corpus_dir: str) -> list[BenchmarkDoc]:
    """Read <corpus>/index.json plus one .txt per entry."""
    with io.open(os.path.join(corpus_dir, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    docs = []
    for row in index:
        path = os.path.join(corpus_dir, row["slug"] + ".txt")
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
        docs.append(BenchmarkDoc(
            doc_id=row["slug"], slug=row["slug"], name=row["name"], text=text, gold=None,
            transform=(),                      # deliberately none: the document as published
            meta={k: row[k] for k in ("field", "expectation", "source_url") if k in row}))
    return docs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, help="directory holding index.json and <slug>.txt")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="load the corpus and print what would be sent; no model calls")
    ap.add_argument("--keep-sandbox", action="store_true")
    ap.add_argument("--gate-off", action="store_true",
                    help="ablation: pass --ignore-scope, so the verdict is recorded but not "
                         "enforced. Measures the extractor on documents the gate refuses. "
                         "Reported as a separate condition, never merged with a gate-on run")
    args = ap.parse_args(argv)

    docs = load_corpus(args.corpus)
    print("%d documents from %s\n" % (len(docs), args.corpus))

    if args.dry_run:
        for d in docs:
            print("  %-12s %-22s %6d chars  %s"
                  % (d.slug, d.meta.get("field", ""), len(d.text), d.meta.get("expectation", "")))
        return 0

    cfg = ModelConfig.from_env()
    run_id = args.run_id or ("scope_probe_" + time.strftime("%Y%m%dT%H%M%S"))
    sb = sandbox.make(run_id)
    print("sandbox %s  (commit %s)" % (sb.root, sb.commit[:12]))
    if sb.dirty:
        # The paper cites a commit; a dirty core file means the cited commit is not what ran.
        print("  WARNING: uncommitted changes in core files: %s" % ", ".join(sb.dirty))

    runs_dir = os.path.join(REPO_ROOT, "experiments", "runs", run_id)
    os.makedirs(runs_dir, exist_ok=True)
    runner = Runner(sb, cfg, adapter_name="scope_probe",
                    cache_dir=os.path.join(runs_dir, "cache"),
                    ignore_scope=args.gate_off)
    condition = "gate_off" if args.gate_off else "gate_on"
    print("condition: %s\n" % condition)

    rows = []
    for doc in docs:
        ex = runner.extract(doc)
        scope = ex.scope or {}
        rows.append({
            "slug": doc.slug,
            "field": doc.meta.get("field", ""),
            "expectation": doc.meta.get("expectation", ""),
            "in_scope": bool(ex.in_scope),
            "fits": scope.get("fits"),
            "gate_enforced": scope.get("gate_enforced"),
            "reason": scope.get("reason", ""),
            "subject_name": (ex.subject or {}).get("name") if ex.subject else None,
            "events": len(ex.events),
            "relations": len(ex.relations),
            "entities": len(ex.entities),
            "exit_code": ex.exit_code,
            "wall_seconds": round(ex.wall_seconds, 1),
        })
        runner.cleanup_subject(doc.slug)

    divergences = sb.verify()
    admitted = [r for r in rows if r["in_scope"]]
    # In the ablation the verdict no longer decides anything, so what matters is whether the
    # extractor produced a graph -- including, and especially, for documents it judged unfit.
    produced = [r for r in rows if r["events"] or r["relations"]]

    print("\n==== %s: verdict 'fits' %d/%d, produced a graph %d/%d ====\n"
          % (condition, len(admitted), len(rows), len(produced), len(rows)))
    print("%-12s %-20s %-10s %7s %7s  %s"
          % ("slug", "field", "verdict", "events", "rels", "expectation"))
    for r in rows:
        print("%-12s %-20s %-10s %7d %7d  %s"
              % (r["slug"], r["field"][:20], "fits" if r["in_scope"] else "UNFIT",
                 r["events"], r["relations"], r["expectation"]))
    if args.gate_off:
        salvaged = [r for r in produced if not r["in_scope"]]
        print("\nextracted despite an UNFIT verdict: %d" % len(salvaged))

    report = {
        "run_id": run_id,
        "condition": condition,
        "manifest": sb.manifest(),
        "core_verified": not divergences,
        "divergences": divergences,
        "model": cfg.model,
        "corpus": os.path.relpath(args.corpus, REPO_ROOT).replace(os.sep, "/"),
        "admitted": len(admitted),
        "produced_a_graph": len(produced),
        "total": len(rows),
        "rows": rows,
    }
    with io.open(os.path.join(runs_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\nreport -> experiments/runs/%s/report.json" % run_id)

    if divergences:
        print("\nEXTRACTION CORE DIVERGED FROM THE REPOSITORY:")
        for d in divergences:
            print("  " + d)
        return 2
    print("extraction core verified unchanged (%d files)" % len(sb.hashes))
    if not args.keep_sandbox:
        sandbox.discard(sb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
