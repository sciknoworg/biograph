#!/usr/bin/env python3
"""Run one extraction model N times over the same document, and record what varies.

Why this exists. The 2026-09-04 model comparison in ../README.md compared six models on
these same two documents and is now uncitable per-model, because nothing on disk says which
model produced which suffix. This script exists so that cannot happen again: every run writes
its model, provider, git commit, extraction-core SHA-256, timestamp, wall time, exit code,
output counts and grounding numbers into manifest.json before the next run starts.

What it measures. Extraction samples at temperature 0.2, so one run is a draw and not a
score. Repeating the same model on the same document gives the spread -- how much of the
difference between two extractions is the model and how much is sampling. Counts alone are
the weakest thing to compare (../README.md says so itself: "size is not quality"), so each
run also records whether it validated and what fraction of its quotes were verbatim.

Isolation. Runs happen in a hash-verified throwaway sandbox, never in the repository.
build_site.py derives its root from its own __file__, so a run in place would write into
subjects/ -- which is exactly the accident ../README.md records, where 170 test entities
began hijacking the pipeline's name resolution. The sandbox's copy of the extraction core is
hashed before and re-verified after, and the manifest records those hashes, so a run states
which code produced it.

--keep-rejected is passed on every call. Without it, a scope refusal deletes the source PDF,
and these two PDFs are the project's own founding documents.

--strict-scope is deliberately NOT passed, matching how the 2026-09-04 runs were invoked, so
these runs stay comparable with those if that mapping is ever recovered.

Credentials come from the environment and are never put on a command line.

    python paper_evidence/variability/run_variability.py --runs 10
    python paper_evidence/variability/run_variability.py --runs 1 --document suntola
    python paper_evidence/variability/run_variability.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO_ROOT)

from experiments.harness import sandbox                      # noqa: E402
from experiments.harness.runner import parse_grounding       # noqa: E402

#: The two documents the 2026-09-04 comparison used. Same documents, so a future recovery of
#: that mapping makes the two studies comparable.
DOCUMENTS = {
    "suntola": {
        "pdf": os.path.join("data", "Puurunen2014 - Tuomo Suntola.pdf"),
        "name": "Tuomo Suntola",
        "citation": "Puurunen 2014, A Short History of Atomic Layer Deposition: "
                    "Tuomo Suntola's Atomic Layer Epitaxy (doi:10.1002/cvde.201402012)",
    },
    "aleskovskii": {
        "pdf": os.path.join("data", "Malygin2015 - V B Aleskovskii.pdf"),
        "name": "Valentin Aleskovskii",
        "citation": "Malygin 2015, From V. B. Aleskovskii's \"Framework\" Hypothesis "
                    "to the Method of Molecular Layering",
    },
}

DATA_FILES = ("entities", "events", "relations", "sources")
MANIFEST = os.path.join(HERE, "manifest.json")


def load_manifest() -> dict:
    if os.path.isfile(MANIFEST):
        with io.open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {"study": "run-to-run variability of one extraction model",
            "documents": {k: v["citation"] for k, v in DOCUMENTS.items()},
            "runs": []}


def save_manifest(m: dict) -> None:
    tmp = MANIFEST + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST)


def next_index(manifest: dict, doc_key: str) -> int:
    """Continue numbering per document, across conditions.

    Run numbers are unique per document and nothing else -- which condition a run belongs to
    lives in manifest.json's `temperature`, never in the folder name. That is the same rule the
    model mapping follows, and for the same reason: a folder name is not a record.
    """
    used = [r["run"] for r in manifest["runs"] if r["document"] == doc_key]
    return max(used, default=0) + 1


def find_doc_dir(sb, slug: str) -> str | None:
    for dirpath, _dirnames, filenames in os.walk(sb.subjects_dir):
        if os.path.basename(os.path.dirname(dirpath)) == slug and "events.json" in filenames:
            return dirpath
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=10,
                    help="runs to add per document (default 10)")
    ap.add_argument("--document", choices=sorted(DOCUMENTS), action="append",
                    help="limit to one document; repeatable. Default: both")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would run, call no model")
    ap.add_argument("--temperature", type=float, default=0.2,
                    help="passed to build_site.py --temperature and recorded per run. The "
                         "manifest is the only record of which condition a run belongs to; "
                         "the folder name deliberately does not encode it")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args(argv)

    keys = args.document or sorted(DOCUMENTS)
    model = os.environ.get("BIOGRAPH_MODEL")
    base_url = os.environ.get("BIOGRAPH_BASE_URL")
    api_key = os.environ.get("BIOGRAPH_API_KEY")

    for k in keys:
        pdf = os.path.join(REPO_ROOT, DOCUMENTS[k]["pdf"])
        if not os.path.isfile(pdf):
            raise SystemExit("source document missing: %s" % DOCUMENTS[k]["pdf"])

    manifest = load_manifest()
    print("model    : %s" % (model or "(BIOGRAPH_MODEL not set)"))
    print("provider : %s" % ((base_url or "").split("//")[-1].split("/")[0] or "(unset)"))
    print("documents: %s" % ", ".join(keys))
    print("runs each: %d" % args.runs)
    print("temp     : %g" % args.temperature)
    for k in keys:
        have = sum(1 for r in manifest["runs"] if r["document"] == k)
        print("  %-12s %d already recorded -> will add runs %d-%d"
              % (k, have, next_index(manifest, k),
                 next_index(manifest, k) + args.runs - 1))
    if args.dry_run:
        print("\n(dry run -- no model called)")
        return 0
    if not (model and base_url and api_key):
        raise SystemExit("set BIOGRAPH_MODEL, BIOGRAPH_BASE_URL and BIOGRAPH_API_KEY first")

    sb = sandbox.make("variability_" + time.strftime("%Y%m%dT%H%M%S"))
    print("\nsandbox %s (commit %s)" % (sb.root, sb.commit[:12]))
    if sb.dirty:
        print("  WARNING: uncommitted changes in core files: %s" % ", ".join(sb.dirty))

    try:
        for k in keys:
            spec = DOCUMENTS[k]
            outdir = os.path.join(HERE, k)
            os.makedirs(outdir, exist_ok=True)
            for _ in range(args.runs):
                idx = next_index(manifest, k)
                slug = "%s_var_%02d" % (k, idx)
                cmd = [sys.executable, sb.build_site, slug,
                       "--pdf", os.path.join(REPO_ROOT, spec["pdf"]),
                       "--name", spec["name"],
                       "--keep-rejected",              # never delete the source PDF
                       "--temperature", str(args.temperature),
                       "--model", model, "--base-url", base_url]
                env = dict(os.environ, BIOGRAPH_API_KEY=api_key)
                start = time.perf_counter()
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", env=env, cwd=sb.root,
                                      timeout=args.timeout)
                wall = time.perf_counter() - start

                ddir = find_doc_dir(sb, slug)
                counts, dest = {}, os.path.join(outdir, "run_%02d" % idx)
                if ddir:
                    if os.path.isdir(dest):
                        shutil.rmtree(dest)
                    shutil.copytree(ddir, dest)
                    sj = os.path.join(os.path.dirname(ddir), "subject.json")
                    if os.path.isfile(sj):
                        shutil.copyfile(sj, os.path.join(dest, "subject.json"))
                    for nm in DATA_FILES:
                        p = os.path.join(dest, nm + ".json")
                        try:
                            with io.open(p, encoding="utf-8") as f:
                                counts[nm] = len(json.load(f))
                        except (OSError, ValueError):
                            counts[nm] = None

                g = parse_grounding(proc.stdout)
                record = {
                    "run": idx,
                    "document": k,
                    "slug": slug,
                    # The whole point of this file: the mapping, written before the next run.
                    "model": model,
                    "base_url": base_url,
                    "temperature": args.temperature,
                    "strict_scope": False,
                    "commit": sb.commit,
                    "core_sha256": sb.hashes,
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "wall_seconds": round(wall, 1),
                    "exit_code": proc.returncode,
                    "validated": proc.returncode == 0,
                    "counts": counts,
                    "grounding": ({"quotes_verbatim": g.quotes_verbatim,
                                   "quotes_checked": g.quotes_checked,
                                   "entities_present": g.entities_present,
                                   "entities_checked": g.entities_checked} if g else None),
                    "output": os.path.relpath(dest, REPO_ROOT).replace(os.sep, "/")
                              if ddir else None,
                }
                manifest["runs"].append(record)
                save_manifest(manifest)          # after every run, not at the end

                q = ("%d/%d" % (g.quotes_verbatim, g.quotes_checked)) if g else "n/a"
                print("  %-16s run %02d  %4.0fs  exit %d  %s  quotes %s"
                      % (k, idx, wall, proc.returncode,
                         "ok " if ddir else "NO OUTPUT",
                         q))

                # Each run must be independent: load_subject_documents() merges every
                # document folder under a subject, so a leftover would union two draws.
                sdir = os.path.dirname(ddir) if ddir else None
                if sdir and os.path.isdir(sdir):
                    shutil.rmtree(sdir, ignore_errors=True)

        divergences = sb.verify()
        manifest["core_verified"] = not divergences
        manifest["divergences"] = divergences
        save_manifest(manifest)
        if divergences:
            print("\nEXTRACTION CORE DIVERGED FROM THE REPOSITORY:")
            for d in divergences:
                print("  " + d)
            return 2
        print("\nextraction core verified unchanged (%d files)" % len(sb.hashes))
    finally:
        sandbox.discard(sb)

    print("manifest -> %s" % os.path.relpath(MANIFEST, REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
