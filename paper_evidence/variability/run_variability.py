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
import re
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
#: Ten documents: a short and a long one in each of the five domains with the most
#: subjects. The length contrast is the axis worth paying for -- WikiBio showed output
#: volume is least stable on the longest documents, and this measures that directly with a
#: repeat design instead of inferring it.
#:
#: The long end is capped near 88,000 characters, which is the longest document this
#: project has DEMONSTRATED fits a 64,000-token reply (Charles de Gaulle, 88,469, in
#: benchmark 3). The corpus holds documents to 200,000, and they were deliberately not
#: chosen: at twice a proven length, a failure costs the whole run and tells you nothing
#: about variability.
#:
#: Sources are `text` where the corpus holds extracted text, which is all but two. Suntola
#: and Aleskovskii exist only as PDFs -- they are the project's two founding documents,
#: hand-extracted before the automated path existed -- so they carry `pdf` instead, and
#: are selectable with --document but are NOT in the default set, which would otherwise
#: give materials science three documents.
DOCUMENTS = {
    # physics
    "dalembert": {"text": "data/dalembert.txt", "name": "Jean d'Alembert",
                  "domain": "physics", "length": "short"},
    "helmert":   {"text": "data/helmert.txt", "name": "Friedrich Robert Helmert",
                  "domain": "physics", "length": "long"},
    # life sciences and medicine
    "pacini":    {"text": "data/pacini.txt", "name": "Filippo Pacini",
                  "domain": "life_sciences_and_medicine", "length": "short"},
    "g_borelli": {"text": "data/g_borelli.txt", "name": "Giovanni Alfonso Borelli",
                  "domain": "life_sciences_and_medicine", "length": "long"},
    # chemistry
    "vigneaud":  {"text": "data/vigneaud.txt", "name": "Vincent du Vigneaud",
                  "domain": "chemistry", "length": "short"},
    "djerassi":  {"text": "data/djerassi.txt", "name": "Carl Djerassi",
                  "domain": "chemistry", "length": "long"},
    # materials science
    "ito_2":     {"text": "data/ito_2.txt", "name": "Ito",
                  "domain": "materials_science", "length": "short"},
    "hooke":     {"text": "data/hooke.txt", "name": "Robert Hooke",
                  "domain": "materials_science", "length": "long"},
    # mathematics and computation
    "bellman":   {"text": "data/bellman.txt", "name": "Richard Bellman",
                  "domain": "mathematics_and_computation", "length": "short"},
    "galton":    {"text": "data/galton.txt", "name": "Francis Galton",
                  "domain": "mathematics_and_computation", "length": "long"},

    # Not in the default set; --document suntola selects it.
    "suntola": {
        "pdf": "data/Puurunen2014 - Tuomo Suntola.pdf",
        "name": "Tuomo Suntola",
        "domain": "materials_science", "length": "medium",
        "citation": "Puurunen 2014, A Short History of Atomic Layer Deposition: "
                    "Tuomo Suntola's Atomic Layer Epitaxy (doi:10.1002/cvde.201402012)",
    },
    "aleskovskii": {
        "pdf": "data/Malygin2015 - V B Aleskovskii.pdf",
        "name": "Valentin Aleskovskii",
        "domain": "materials_science", "length": "medium",
        "citation": "Malygin 2015, From V. B. Aleskovskii's \"Framework\" Hypothesis "
                    "to the Method of Molecular Layering",
    },
}

#: The ten run by default. The two founding PDFs are excluded so that every domain
#: contributes exactly two documents and the design stays balanced.
DEFAULT_DOCUMENTS = [k for k, v in DOCUMENTS.items() if "text" in v]


def source_of(spec):
    """(flag, path) for a document -- build_site takes --text or --pdf, not both."""
    return ("--text", spec["text"]) if "text" in spec else ("--pdf", spec["pdf"])

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


LOCK = MANIFEST + ".lock"


def _acquire_lock(timeout=120.0):
    """Exclusive lock around the read-merge-write, by creating a file nobody else can.

    Merging alone is not enough once several invocations run at once: A reads, B reads, A
    writes, B writes, and B's copy -- which never saw A's run -- wins. One lost entry costs the
    wall time, exit code and grounding for that draw, which exist nowhere else. With one model
    per process the write frequency multiplies and a narrow race stops being negligible.

    O_CREAT|O_EXCL is atomic on Windows and POSIX alike. A lock older than the timeout is
    treated as abandoned by a killed process and broken, because a study that stops recording
    because something was Ctrl-C'd an hour ago is worse than a torn write.
    """
    start = time.time()
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCK) > timeout:
                    os.remove(LOCK)
                    continue
            except OSError:
                pass
            if time.time() - start > timeout:
                return          # give up and write anyway: losing the run is worse
            time.sleep(0.2)


def _release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def save_manifest(m: dict) -> None:
    """Merge into whatever is on disk, rather than overwriting it, under a lock.

    Several invocations can run at once -- one per document, per temperature, or per model --
    and each holds the manifest it loaded at startup. A plain overwrite means the last writer
    erases every run the others recorded since, and those measurements exist nowhere else: the
    run folders hold the extraction, but wall time, exit code and grounding live only here.

    So take the lock, re-read, merge by (document, run), write, release.
    """
    _acquire_lock()
    try:
        _save_manifest_locked(m)
    finally:
        _release_lock()


def _save_manifest_locked(m: dict) -> None:
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


def model_slug(model: str) -> str:
    """A model name as a directory component. `anthropic/claude-fable-5.1` has a slash."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (model or "unknown_model")).strip("_")


def run_dir(model: str, temperature: float, doc_key: str) -> str:
    """Where one condition's runs live: <model>/t<temp>/<document>/.

    The manifest remains the record -- it always did, and a folder name is not one. But a
    study that will be repeated with other models needs its results separable by eye as
    well as by query, and nesting the model and temperature makes `ls` answer the question
    that otherwise needs a script.
    """
    return os.path.join(HERE, "runs", model_slug(model),
                        "t%g" % temperature, doc_key)


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
    ap.add_argument("--max-tokens", type=int, default=64_000,
                    help="reply budget per request. build_site.py's own default is 32,000, "
                         "under which a long document's reply was truncated and arrived as "
                         "an empty graph reporting success; the long documents here are "
                         "~88,000 characters and need the larger budget")
    ap.add_argument("--temperature", type=float, action="append", default=None,
                    help="passed to build_site.py --temperature and recorded per run. The "
                         "manifest is the only record of which condition a run belongs to; "
                         "the folder name deliberately does not encode it")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args(argv)

    keys = args.document or list(DEFAULT_DOCUMENTS)
    # --temperature is repeatable. The default pair is 0.0 and 0.2: greedy decoding against
    # the setting the pipeline actually ships with, so the comparison answers a question
    # about this system rather than about a temperature sweep.
    #
    # 0.0 is NOT determinism here. The served model is a mixture-of-experts whose routing
    # depends on request batching, so greedy decoding still varies between runs -- which is
    # the point of running it five times rather than once.
    #
    # Each temperature is its own condition; summarise.py keys on it and never pools them.
    temps = sorted(set(args.temperature if args.temperature else [0.0, 0.2]))
    # --api-key-env takes the NAME of a variable. Someone passing the key itself would
    # otherwise see it echoed back in the "not set" error -- printed to the terminal and
    # already in the shell history -- turning a typo into a leak. Refuse without ever
    # repeating the value.
    name = args.api_key_env or ""
    looks_like_a_key = (len(name) > 64 or any(c in name for c in "-.:/")
                        or name != name.upper())
    if looks_like_a_key:
        raise SystemExit(
            "--api-key-env takes the NAME of an environment variable holding the key, not "
            "the key itself. Set the variable first, then pass its name, e.g.: "
            "--api-key-env OPENROUTER_API_KEY" + chr(10) +
            "The value passed looks like a credential and has NOT been echoed here. If it "
            "was a real key, treat it as compromised -- it is in your shell history.")

    model = args.model
    base_url = args.base_url
    api_key = os.environ.get(args.api_key_env)

    for k in keys:
        _flag, rel = source_of(DOCUMENTS[k])
        if not os.path.isfile(os.path.join(REPO_ROOT, rel)):
            raise SystemExit("source document missing: %s" % rel)

    manifest = load_manifest()
    print("model    : %s" % (model or "(BIOGRAPH_MODEL not set)"))
    print("provider : %s" % ((base_url or "").split("//")[-1].split("/")[0] or "(unset)"))
    print("documents: %s" % ", ".join(keys))
    print("runs each: %d per temperature" % args.runs)
    print("temps    : %s" % ", ".join("%g" % t for t in temps))
    print("budget   : --max-tokens %d" % args.max_tokens)
    print("total    : %d runs (%d documents x %d temperatures x %d runs)"
          % (len(keys) * len(temps) * args.runs, len(keys), len(temps), args.runs))
    for k in keys:
        spec = DOCUMENTS[k]
        _flag, rel = source_of(spec)
        size = os.path.getsize(os.path.join(REPO_ROOT, rel))
        have = sum(1 for r in manifest["runs"] if r["document"] == k)
        print("  %-12s %-28s %-6s %7d chars  (%d already recorded)"
              % (k, spec.get("domain", "?"), spec.get("length", "?"), size, have))
    if args.dry_run:
        print("\n(dry run -- no model called)")
        return 0
    if not (model and base_url and api_key):
        missing = [n for n, v in (("--model", model), ("--base-url", base_url),
                                  ("a key in $" + args.api_key_env, api_key)) if not v]
        raise SystemExit("missing: " + ", ".join(missing))

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
        for temperature in temps:
          for k in keys:
              spec = DOCUMENTS[k]
              source_flag, source_rel = source_of(spec)
              outdir = run_dir(model, temperature, k)
              os.makedirs(outdir, exist_ok=True)
              consecutive_timeouts = 0
              for _ in range(args.runs):
                  idx, dest = claim_run(manifest, k, outdir)
                  slug = "%s_var_%02d" % (k, idx)
                  cmd = [sys.executable, sb.build_site, slug,
                         source_flag, os.path.join(REPO_ROOT, source_rel),
                         "--name", spec["name"],
                         "--keep-rejected",              # never delete the source PDF
                         "--temperature", str(temperature),
                       "--max-tokens", str(args.max_tokens),
                         "--model", model, "--base-url", base_url]
                  env = dict(os.environ, BIOGRAPH_API_KEY=api_key)
                  # A model too slow to finish inside --timeout is a RESULT about that model,
                  # not a reason to abandon the other four. qwen3.8-27b hit 2400s on its first
                  # draw and the unhandled TimeoutExpired killed the whole study, losing the
                  # claimed run folder and leaving its sandbox behind.
                  start = time.perf_counter()
                  timed_out = False
                  try:
                      proc = subprocess.run(cmd, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", env=env,
                                            cwd=sb.root, timeout=args.timeout)
                  except subprocess.TimeoutExpired as exc:
                      # Keep what the child printed before it was killed. TimeoutExpired carries
                      # it, and discarding it threw away the only evidence of WHY a run timed
                      # out -- whether the model was streaming steadily and simply had more to
                      # say, or produced nothing at all for the whole timeout. Those are
                      # different failures and the log is the only thing that tells them apart.
                      timed_out = True
                      partial = exc.stdout or exc.output or ""
                      if isinstance(partial, bytes):
                          partial = partial.decode("utf-8", "replace")
                      err = exc.stderr or b""
                      if isinstance(err, bytes):
                          err = err.decode("utf-8", "replace")
                      proc = subprocess.CompletedProcess(
                          cmd, -1, partial,
                          (err + "\n" if err else "") + "timed out after %ds" % args.timeout)
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
                      "temperature": temperature,
                    "max_tokens": args.max_tokens,
                    "domain": spec.get("domain"),
                    "length_class": spec.get("length"),
                      "strict_scope": False,
                      "commit": sb.commit,
                      "rules_sha": prompt_sha,
                      "core_sha256": sb.hashes,
                      "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "wall_seconds": round(wall, 1),
                      "exit_code": proc.returncode,
                      "timed_out": timed_out,
                      # An empty extraction satisfies every schema constraint trivially: zero
                      # events have zero missing dates. mistral-medium-3.5-128b returned [] for
                      # all four files twice and was recorded as validated, which is true and
                      # useless. Schema validity is not evidence that anything was extracted.
                      "empty": not any(counts.get(k) for k in DATA_FILES),
                      "validated": (proc.returncode == 0 and not timed_out
                                    and any(counts.get(k) for k in DATA_FILES)),
                      "counts": counts,
                      "grounding": ({"quotes_verbatim": g.quotes_verbatim,
                                     "quotes_checked": g.quotes_checked,
                                     "entities_present": g.entities_present,
                                     "entities_checked": g.entities_checked} if g else None),
                      "output": os.path.relpath(dest, REPO_ROOT).replace(os.sep, "/")
                                if ddir else None,
                  }
                  # The driver discards stdout, which is fine for a run that worked and fatal
                  # for one that did not: the scope verdict, the JSON-retry notes and the
                  # validation errors are all in there, and the sandbox is about to be deleted.
                  if not any(counts.get(x) for x in DATA_FILES) or proc.returncode != 0:
                      try:
                          with io.open(os.path.join(dest, "_stdout.log"), "w",
                                       encoding="utf-8") as fh:
                              fh.write((proc.stdout or "") + (proc.stderr or ""))
                      except OSError:
                          pass

                  manifest["runs"].append(record)
                  save_manifest(manifest)          # after every run, not at the end

                  q = ("%d/%d" % (g.quotes_verbatim, g.quotes_checked)) if g else "n/a"
                  print("  %-16s run %02d  %4.0fs  exit %-3d %s  quotes %s"
                        % ("%s t%g" % (k, temperature), idx, wall, proc.returncode,
                           "TIMED OUT" if timed_out else ("EMPTY" if not any(counts.get(x) for x in DATA_FILES) else ("ok " if ddir else "NO OUTPUT")),
                           q))

                  # Each run must be independent: load_subject_documents() merges every
                  # document folder under a subject, so a leftover would union two draws.
                  sdir = os.path.dirname(ddir) if ddir else None
                  if sdir and os.path.isdir(sdir):
                      shutil.rmtree(sdir, ignore_errors=True)

                  # Two timeouts in a row is a model that cannot do this within --timeout.
                  # Spending the remaining draws to learn it again wastes hours of budget.
                  if timed_out:
                      consecutive_timeouts += 1
                      if consecutive_timeouts >= 2:
                          print("  %s: two consecutive timeouts at %ds -- stopping this "
                                "document. Raise --timeout to give it longer."
                                % (model, args.timeout))
                          break
                  else:
                      consecutive_timeouts = 0

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
