"""Run one benchmark end to end.

    python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --dry-run
    python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --limit 25
    python -m experiments.harness.cli --benchmark pmoa_tts --data-root <dir> --repeats 3

--dry-run does everything except call the model: it loads the corpus, builds the input
text, prints what would be sent, and stops. It costs nothing, and it is how you check
that the input adapter and the slug rules are right before spending an API budget on
finding out.

Nothing here writes to the repository outside experiments/. Extraction runs in a
throwaway sandbox whose copy of the extraction core is hash-checked before and after
(see sandbox.py); a divergence fails the run rather than being reported as a footnote.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

from . import sandbox
from .runner import ModelConfig, Runner

REPO_ROOT = sandbox.REPO_ROOT
RUNS_DIR = os.path.join(REPO_ROOT, "experiments", "runs")


def get_adapter(name: str, args):
    if name == "pmoa_tts":
        from ..benchmarks.pmoa_tts.adapter import ANCHOR, PmoaTtsAdapter
        return PmoaTtsAdapter(
            framing=args.framing,
            anchor=None if args.no_anchor else ANCHOR,
            split=args.split,
            matcher=args.matcher,
            threshold=args.threshold,
        )
    if name == "biographical":
        from ..benchmarks.biographical.adapter import BiographicalAdapter
        return BiographicalAdapter(min_facts=args.min_facts)
    if name == "bioevents":
        from ..benchmarks.bioevents.adapter import BioEventsAdapter
        return BioEventsAdapter(min_triggers=args.min_triggers)
    raise SystemExit(f"no adapter named {name!r} yet "
                     f"(built so far: pmoa_tts, biographical, bioevents)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--data-root", help="local copy of the benchmark corpus; never "
                                        "downloaded or committed by this harness")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--repeats", type=int, default=1,
                    help="extraction samples at temperature 0.2, so a single run is a "
                         "draw, not a score. Repeats are scored separately and reported "
                         "with their spread")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-id")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--keep-sandbox", action="store_true")
    ap.add_argument("--gate-off", action="store_true",
                    help="pass build_site.py --ignore-scope: the scope verdict is recorded "
                         "but not enforced. Required for any general-biography corpus, "
                         "whose population the gate refuses (0/5 for literature, art, "
                         "sport, music and politics -- see docs/scope-gate-boundary.md). "
                         "Reported as its own condition, never merged with a gate-on run")
    # biographical options
    ap.add_argument("--min-facts", type=int, default=1,
                    help="skip people with fewer than this many scorable gold facts; each "
                         "person costs one extraction either way")
    # bioevents options
    ap.add_argument("--min-triggers", type=int, default=1,
                    help="skip documents with fewer than this many annotated triggers")
    # pmoa_tts options
    ap.add_argument("--framing", default="minimal", choices=("none", "minimal", "biographical"))
    ap.add_argument("--no-anchor", action="store_true")
    ap.add_argument("--split", default="case_study_100",
                    help="which released annotation to score against")
    ap.add_argument("--matcher", default="embedding", choices=("embedding", "lev"))
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--ceiling", action="store_true",
                    help="score the two released LLM annotators against each other and "
                         "stop. No model call, no text fetch -- this is the reference "
                         "band biograph's score should be read against, since the "
                         "clinician set behind the published numbers is not distributed")
    ap.add_argument("--ceiling-n", type=int, default=200)
    args = ap.parse_args(argv)

    adapter = get_adapter(args.benchmark, args)

    if args.ceiling:
        if not hasattr(adapter, "agreement_ceiling"):
            raise SystemExit(f"{adapter.name} has no agreement ceiling to compute")
        if not args.data_root:
            raise SystemExit("--ceiling needs --data-root")
        report = adapter.agreement_ceiling(args.data_root, n=args.ceiling_n,
                                           matcher=args.matcher, threshold=args.threshold)
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    if not args.data_root:
        raise SystemExit("--data-root is required: the corpora are not vendored here. "
                         f"{adapter.name} licence: {adapter.license}")
    if not os.path.isdir(args.data_root):
        raise SystemExit(f"--data-root not found: {args.data_root}")

    docs = list(adapter.load(args.data_root, limit=args.limit))
    if not docs:
        raise SystemExit(f"no documents loaded from {args.data_root} -- check the Layout "
                         f"in experiments/benchmarks/{adapter.name}/adapter.py against "
                         f"the actual file names")
    print(f"{adapter.name}: {len(docs)} documents")
    print(f"  licence: {adapter.license}")
    print(f"  metric:  {adapter.metric}")

    if args.dry_run:
        d = docs[0]
        print(f"\n--- dry run: first document ({d.doc_id}) ---")
        print(f"slug:      {d.slug}")
        print(f"name:      {d.name}")
        print(f"transform: {', '.join(d.transform) or '(none)'}")
        print(f"gold:      {len(d.gold)} events"
              + (f", {d.meta['gold_rows_unparsed']} unparsed rows"
                 if d.meta.get("gold_rows_unparsed") else ""))
        print(f"text:      {len(d.text):,} chars\n")
        print(d.text[:1200] + ("..." if len(d.text) > 1200 else ""))
        print("\n(no model was called)")
        return 0

    run_id = args.run_id or f"{adapter.name}_{time.strftime('%Y%m%dT%H%M%S')}"
    out_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(out_dir, exist_ok=True)
    cfg = ModelConfig.from_env()
    sb = sandbox.make(run_id)
    if sb.dirty:
        print(f"  WARNING: uncommitted changes in the extraction core: "
              f"{', '.join(sb.dirty)} -- the run cannot be cited to commit {sb.commit[:12]}")
    print(f"  core:    {sb.commit[:12]}, sandboxed at {os.path.relpath(sb.root, REPO_ROOT)}")
    print(f"  model:   {cfg.model} @ {cfg.base_url}")

    runner = Runner(sb, cfg, adapter.name, verbose=True,
                    cache_dir=None if args.no_cache else os.path.join(out_dir, "cache"),
                    ignore_scope=args.gate_off)

    reports = []
    for rep in range(args.repeats):
        if args.repeats > 1:
            print(f"\n-- repeat {rep + 1}/{args.repeats} --")
        pairs, extractions = [], {}
        for doc in docs:
            runner.cleanup_subject(doc.slug)
            ex = runner.extract(doc, repeat=rep)
            ex = runner.check_grounding(ex)
            extractions[doc.doc_id] = ex
            pairs.append((doc, adapter.project(doc, ex)))
        report = adapter.score(pairs, extractions=extractions)
        grounded = [e.grounding.quote_rate for e in extractions.values()
                    if e.grounding and e.grounding.quote_rate is not None]
        if grounded:
            report.scores["grounding_quote_rate"] = sum(grounded) / len(grounded)
        reports.append(report.as_dict())
        print("\n" + json.dumps(report.as_dict(), indent=2))

    divergences = sb.verify()
    result = {
        "run_id": run_id,
        "finished": dt.datetime.now().isoformat(timespec="seconds"),
        "adapter": {"name": adapter.name, "citation": adapter.citation,
                    "license": adapter.license, "metric": adapter.metric},
        "core": sb.manifest(),
        "extraction_core_divergences": divergences,
        "model": {"model": cfg.model, "base_url": cfg.base_url},
        "n_documents": len(docs),
        "repeats": [r for r in reports],
    }
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nwrote {os.path.relpath(os.path.join(out_dir, 'report.json'), REPO_ROOT)}")

    if not args.keep_sandbox:
        sandbox.discard(sb)
    if divergences:
        print("\nEXTRACTION CORE DIVERGED DURING THE RUN:", file=sys.stderr)
        for d in divergences:
            print(f"  {d}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
