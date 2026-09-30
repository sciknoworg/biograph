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
import hashlib
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


def rules_fingerprint(build_site_path):
    """sha256 of the prompt's own text: RULES + SCOPE_DEFINITION, sliced out of the source.

    The commit is a poor identifier for a prompt -- it changes when anything in the repository
    changes, so it splits one condition into two whenever an unrelated file is touched, and the
    summary then reports two blocks describing identical runs. This hashes the two string
    literals that actually reach the model, so runs group by the prompt they used.
    """
    try:
        src = io.open(build_site_path, encoding="utf-8").read()
    except OSError:
        return None
    parts = []
    for name in ("RULES", "SCOPE_DEFINITION"):
        marker = name + ' = """'
        i = src.find(marker)
        if i == -1:
            return None
        j = src.find('"""', i + len(marker))
        parts.append(src[i:j])
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()[:10]


def load_manifest() -> dict:
    if os.path.isfile(MANIFEST):
        with io.open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {"study": "run-to-run variability of one extraction model",
            "documents": {k: v["citation"] for k, v in DOCUMENTS.items()},
            "runs": []}


def save_manifest(m: dict) -> None:
    """Merge into whatever is on disk, rather than overwriting it.

    Two invocations can run at once -- one per document, or one per temperature -- and each
    holds the manifest it loaded at startup. A plain overwrite means the last writer erases
    every run the other recorded since, and those measurements exist nowhere else: the run
    folders hold the extraction, but wall time, exit code and grounding live only here.

    So re-read, merge by (document, run), and write. Not atomic against a simultaneous write
    to the millisecond, but runs are minutes apart, which is the actual exposure.
    """
    merged = {}
    if os.path.isfile(MANIFEST):
        try:
            with io.open(MANIFEST, encoding="utf-8") as f:
                for r in json.load(f).get("runs", []):
                    merged[(r.get("document"), r.get("run"))] = r
        except (OSError, ValueError):
            pass
    for r in m.get("runs", []):
        merged[(r.get("document"), r.get("run"))] = r
    out = dict(m)
    out["runs"] = [merged[k] for k in sorted(merged, key=lambda k: (str(k[0]), k[1] or 0))]
    tmp = MANIFEST + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST)
    m["runs"] = out["runs"]


def next_index(manifest: dict, doc_key: str, outdir: str) -> int:
    """Continue numbering per document, across conditions.

    Run numbers are unique per document and nothing else -- which condition a run belongs to
    lives in manifest.json's `temperature`, never in the folder name. That is the same rule the
    model mapping follows, and for the same reason: a folder name is not a record.

    Folders on disk count as used, not just manifest entries. Two invocations on the SAME
    document -- e.g. one per temperature -- would otherwise both compute the same next number
    and write into the same folder, and the merge in save_manifest() would keep only one of
    them. A folder is claimed by mkdir before its run starts, so the claim is what makes
    concurrent numbering safe.
    """
    used = {r["run"] for r in manifest["runs"] if r["document"] == doc_key}
    # Numbering spans models as well as temperatures: every condition over one document draws
    # from the same sequence, and the manifest says which condition each number belongs to.
    if os.path.isdir(outdir):
        for name in os.listdir(outdir):
            if name.startswith("run_"):
                try:
                    used.add(int(name[4:]))
                except ValueError:
                    pass
    return max(used, default=0) + 1


def claim_run(manifest: dict, doc_key: str, outdir: str):
    """(index, destination) with the destination created, so no other process can take it."""
    while True:
        idx = next_index(manifest, doc_key, outdir)
        dest = os.path.join(outdir, "run_%02d" % idx)
        try:
            os.mkdir(dest)
            return idx, dest
        except FileExistsError:
            continue


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
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL"),
                    help="extraction model, exactly as the provider names it. Defaults to "
                         "BIOGRAPH_MODEL. Recorded per run in the manifest -- which is the "
                         "whole point: the 2026-09-04 comparison is uncitable because nothing "
                         "on disk says which model produced which output")
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"),
                    help="OpenAI-compatible endpoint, e.g. https://openrouter.ai/api/v1 or a "
                         "KISSKI URL. Defaults to BIOGRAPH_BASE_URL")
    ap.add_argument("--api-key-env", default="BIOGRAPH_API_KEY",
                    help="NAME of the environment variable holding the key for this provider "
                         "(default BIOGRAPH_API_KEY) -- e.g. OPENROUTER_API_KEY. The name, "
                         "never the key: a key on a command line lands in shell history and in "
                         "every log line that echoes the command")
    ap.add_argument("--temperature", type=float, default=0.2,
                    help="passed to build_site.py --temperature and recorded per run. The "
                         "manifest is the only record of which condition a run belongs to; "
                         "the folder name deliberately does not encode it")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args(argv)

    keys = args.document or sorted(DOCUMENTS)
    model = args.model
    base_url = args.base_url
    api_key = os.environ.get(args.api_key_env)

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
        first = next_index(manifest, k, os.path.join(HERE, k))
        print("  %-12s %d already recorded -> will add runs %d-%d"
              % (k, have, first, first + args.runs - 1))
    if args.dry_run:
        print("\n(dry run -- no model called)")
        return 0
    if not (model and base_url and api_key):
        raise SystemExit("need --model, --base-url and a key in %s (or set BIOGRAPH_MODEL / "
                         "BIOGRAPH_BASE_URL / BIOGRAPH_API_KEY)" % args.api_key_env)

    # The pid is in the name because two invocations are meant to run at once -- one per
    # document, or one per temperature. A seconds-resolution timestamp alone collides when
    # both start in the same second, and then the first to finish discards the sandbox the
    # other is still extracting into.
    sb = sandbox.make("variability_%s_%d" % (time.strftime("%Y%m%dT%H%M%S"), os.getpid()))
    prompt_sha = rules_fingerprint(sb.build_site)
    print("prompt   : %s" % (prompt_sha or "(could not fingerprint)"))
    print("\nsandbox %s (commit %s)" % (sb.root, sb.commit[:12]))
    if sb.dirty:
        print("  WARNING: uncommitted changes in core files: %s" % ", ".join(sb.dirty))

    try:
        for k in keys:
            spec = DOCUMENTS[k]
            outdir = os.path.join(HERE, k)
            os.makedirs(outdir, exist_ok=True)
            for _ in range(args.runs):
                idx, dest = claim_run(manifest, k, outdir)
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
                counts = {}
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
                    "api_key_env": args.api_key_env,
                    "temperature": args.temperature,
                    "strict_scope": False,
                    "commit": sb.commit,
                    "rules_sha": prompt_sha,
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
