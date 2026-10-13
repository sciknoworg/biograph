"""Run one benchmark end to end.

    python -m experiments.harness.cli --benchmark wikibio --data-root <dir> --dry-run
    python -m experiments.harness.cli --benchmark biographical --data-root <dir> --limit 25
    python -m experiments.harness.cli --benchmark wikilife --data-root <dir> --repeats 3

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

# Windows' console codepage (cp1252) cannot encode most of what these corpora contain, and
# a print() that raises takes the run with it. A dry run on WikiLifeTrajectory died on the
# l-stroke in "Bielanska"; the biographies here are Polish, Chinese, Arabic and Kikuyu.
# build_site.py guards its own streams the same way -- the harness had not.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = sandbox.REPO_ROOT
RUNS_DIR = os.path.join(REPO_ROOT, "experiments", "runs")


def get_adapter(name: str, args):
    if name == "biographical":
        from ..benchmarks.biographical.adapter import BiographicalAdapter
        return BiographicalAdapter(min_facts=args.min_facts, order=args.b1_order)
    if name == "grounding":
        from ..benchmarks.grounding.adapter import GroundingAdapter
        return GroundingAdapter()
    if name == "wikibio":
        from ..benchmarks.wikibio.adapter import WikiBioAdapter
        return WikiBioAdapter(min_events=args.min_events)
    if name == "eventkg":
        from ..benchmarks.eventkg.adapter import EventKgAdapter
        return EventKgAdapter(min_facts=args.min_facts, cutoff=args.ekg_cutoff,
                              order=args.ekg_order)
    if name == "wikilife":
        from ..benchmarks.wikilife.adapter import WikiLifeAdapter
        return WikiLifeAdapter()
    if name == "bioevents":
        from ..benchmarks.bioevents.adapter import BioEventsAdapter
        return BioEventsAdapter(min_triggers=args.min_triggers, order=args.order)
    raise SystemExit(f"no adapter named {name!r} yet "
                     f"(built so far: biographical, bioevents, wikilife, wikibio, "
                     f"eventkg, grounding)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--data-root", help="local copy of the benchmark corpus; never "
                                        "downloaded or committed by this harness")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", action="append", metavar="DOC_ID",
                    help="extract only these documents, by the benchmark's own doc_id. "
                         "Repeatable. Applied after load() and before --limit, so the "
                         "document order and every gold figure stay as the adapter built "
                         "them. Scores from a filtered run are over the filtered set only "
                         "and must never be merged with a full run's")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="seconds a single extraction may take before the harness kills "
                         "it and records timed_out. The default suits short benchmark "
                         "documents; a full-length biography needs more. A timeout costs "
                         "one document, not the run")
    ap.add_argument("--max-tokens", type=int,
                    help="reply budget per request. Unset leaves build_site.py's default "
                         "of 32,000, which every run so far used. A whole biography can "
                         "exceed it and fall into the continuation path; raising it is the "
                         "way to test whether that path is what empties a document")
    ap.add_argument("--repeats", type=int, default=1,
                    help="extraction samples at temperature 0.2, so a single run is a "
                         "draw, not a score. Repeats are scored separately and reported "
                         "with their spread")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-id")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--keep-sandbox", action="store_true")
    # "--gate-off" is kept as a deprecated alias so commands already written keep working.
    # The preferred spelling is --relax-inclusion: "gate" is wrong twice over here, since
    # gating means mixture-of-experts routing -- which the extraction model actually does,
    # and which this project separately discusses -- and since a gate names a mechanism
    # where "criterion" names the standard being applied.
    ap.add_argument("--relax-inclusion", "--gate-off", dest="relax_inclusion",
                    action="store_true",
                    help="record the inclusion verdict without enforcing it (passes "
                         "build_site.py --ignore-scope). Required for any general-biography "
                         "corpus, whose population the criteria exclude (0/5 for "
                         "literature, art, sport, music and politics -- see "
                         "docs/scope-gate-boundary.md). Reported as its own condition, "
                         "never merged with a run where the criteria were enforced")
    # biographical options
    ap.add_argument("--min-facts", type=int, default=1,
                    help="skip people with fewer than this many scorable gold facts; each "
                         "person costs one extraction either way")
    # bioevents options
    ap.add_argument("--min-triggers", type=int, default=1,
                    help="skip documents with fewer than this many annotated triggers")
    ap.add_argument("--b1-order", default="balanced", choices=("balanced", "id"),
                    help="biographical document order. 'balanced' round-robins across the "
                         "scored labels, so every prefix gives even per-label support for "
                         "the macro F1; 'id' is a proportional sample by page id")
    ap.add_argument("--order", default="extractable", choices=("extractable", "richness"),
                    help="document order, which decides what --limit buys. Both put "
                         "documents that can yield an event first. 'extractable' then "
                         "orders by id, giving a prefix representative of that "
                         "subcorpus; 'richness' then orders by gold EVENT count, "
                         "reaching a given number of EVENTs in roughly half the calls "
                         "but giving a prefix twice as dense as the corpus, whose "
                         "recall is not a corpus estimate and must be reported as such")
    # eventkg options
    ap.add_argument("--ekg-order", default="richness", choices=("richness", "file"),
                    help="eventkg document order. 'richness' puts the people with the "
                         "most scored gold facts first, so a run stopped early has "
                         "finished the documents carrying the most measurement -- but a "
                         "prefix of it is NOT a sample, and its recall must be reported "
                         "as covering the most-documented people. 'file' is the release's "
                         "own arbitrary order, which a prefix approximates a sample of")
    ap.add_argument("--ekg-cutoff", default="2019-05-21",
                    help="eventkg: the revision cutoff the abstracts were fetched at. "
                         "Recorded in the report; must match what fetch_abstracts.py used")
    ap.add_argument("--min-events", type=int, default=1,
                    help="wikibio: skip biographies with fewer than this many gold "
                         "event triggers")
    args = ap.parse_args(argv)

    adapter = get_adapter(args.benchmark, args)

    if hasattr(adapter, "audit"):
        # Benchmark 5 audits graphs that already exist. No corpus to point at, no model to
        # call, and no sandbox: --check-grounding writes nothing, and subjects/ is what is
        # being measured rather than somewhere to put output.
        out_dir = os.path.join(RUNS_DIR, args.run_id or
                               f"{adapter.name}_{time.strftime('%Y%m%dT%H%M%S')}")
        os.makedirs(out_dir, exist_ok=True)
        report = adapter.audit(limit=args.limit)
        with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report.as_dict(), f, ensure_ascii=False, indent=2)
        print("\n" + json.dumps(report.scores, indent=2))
        for note in report.notes:
            print("  - " + note)
        print(f"\nreport -> {os.path.relpath(out_dir, REPO_ROOT)}/report.json")
        return 0

    if not args.data_root:
        raise SystemExit("--data-root is required: the corpora are not vendored here. "
                         f"{adapter.name} licence: {adapter.license}")
    if not os.path.isdir(args.data_root):
        raise SystemExit(f"--data-root not found: {args.data_root}")

    docs = list(adapter.load(args.data_root, limit=None if args.only else args.limit))
    if args.only:
        wanted = list(args.only)
        docs = [d for d in docs if d.doc_id in set(wanted)]
        found = {d.doc_id for d in docs}
        missing = [w for w in wanted if w not in found]
        if missing:
            raise SystemExit("--only named %d document(s) this adapter did not load: %s"
                             % (len(missing), ", ".join(repr(m) for m in missing)))
        if args.limit:
            docs = docs[:args.limit]
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
                    ignore_scope=args.relax_inclusion, timeout=args.timeout,
                    max_tokens=args.max_tokens)

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
        # Endpoint conditions, recorded beside the scores. 9.4% of 1,585 extractions
        # across this project saw the model's stream go silent for over six minutes --
        # a standing property of the endpoint, not an occasional glitch. A recall figure
        # should be readable next to the conditions that produced it, and until now this
        # could only be recovered by grepping stdout out of the cache.
        stalled = [e.stalled_requests for e in extractions.values()]
        report.scores["documents_with_a_stalled_request"] = float(
            sum(1 for n in stalled if n))
        report.scores["stalled_requests_total"] = float(sum(stalled))
        timed = sum(1 for e in extractions.values() if e.timed_out)
        if timed:
            report.scores["documents_timed_out"] = float(timed)
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
        # What produced this run. Recovering B1's and B2's sampling after the fact meant
        # matching cached document ids against each ordering in turn -- the report said
        # only "400 documents", and 400 of 1,800 under `balanced` is a different sample
        # from 400 under `id`. Anything that changes which documents were chosen, or what
        # the model was allowed to produce, belongs here.
        "invocation": {
            "limit": args.limit,
            "only": args.only,
            "order": getattr(args, "order", None),
            "b1_order": getattr(args, "b1_order", None),
            "min_facts": getattr(args, "min_facts", None),
            "min_triggers": getattr(args, "min_triggers", None),
            "min_events": getattr(args, "min_events", None),
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
            "relax_inclusion": args.relax_inclusion,
            "repeats": args.repeats,
            "argv": sys.argv[1:],
        },
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
