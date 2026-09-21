"""A disposable copy of the extraction core, hash-verified against the repository.

Why a copy at all. build_site.py computes ROOT from its own __file__, so `subjects/`,
`data/` and `dist/` are always siblings of `scripts/`. There is no flag or environment
variable to redirect them. Running benchmarks in the repository itself would therefore
write thousands of fake subjects into `subjects/` -- and the project treats everything
under `subjects/` as a real person: paper_evidence/README.md records exactly that
accident, where 170 test-run entities leaked into the pipeline's name resolution and
"Tuomo Suntola" started resolving to `suntola_test_g`. The benchmark harness must not
be able to repeat it.

So each run gets its own tree:

    experiments/.sandbox/<run_id>/
        scripts/build_site.py     byte-identical copy, sha256 asserted
        schema/*.schema.json      byte-identical copies, sha256 asserted
        frontend/                 template + geojson, needed by build()
        data/                     staged source text (build_site.py writes it here)
        subjects/benchmark/       extraction output
        dist/                     rendered HTML nobody looks at

Why hashes. "We did not modify the extraction core" is a claim the paper makes, and a
copy is exactly where that claim could quietly stop being true. manifest.json records
the git commit and the sha256 of every copied file, and verify() re-checks them against
the repository after the run. A divergence is an error, not a warning.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SANDBOX_ROOT = os.path.join(REPO_ROOT, "experiments", ".sandbox")

#: Everything the extraction core needs, and nothing else. Copied verbatim.
#: build_site.py imports only the standard library plus openai/httpx/jsonschema, so
#: there is no package layout to reproduce.
CORE_FILES = (
    "scripts/build_site.py",
    "schema/date.schema.json",
    "schema/entity.schema.json",
    "schema/event.schema.json",
    "schema/relation.schema.json",
    "schema/source.schema.json",
    "frontend/template.html",
    "frontend/world-countries.geo.json",
)

#: --domain value for every benchmark run. Keeps output under
#: subjects/benchmark_<adapter>/ so it is obvious on sight that nothing here is a
#: person, even if a sandbox is ever copied somewhere it should not be.
DOMAIN_PREFIX = "benchmark"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def git_dirty_core() -> list[str]:
    """Which CORE_FILES have uncommitted changes -- the paper cites a commit, so a
    dirty core file means the cited commit is not what ran."""
    try:
        out = subprocess.run(["git", "-C", REPO_ROOT, "status", "--porcelain", "--"]
                             + list(CORE_FILES), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip()]


@dataclass
class Sandbox:
    run_id: str
    root: str
    commit: str
    hashes: dict[str, str] = field(default_factory=dict)
    dirty: list[str] = field(default_factory=list)

    @property
    def build_site(self) -> str:
        return os.path.join(self.root, "scripts", "build_site.py")

    @property
    def subjects_dir(self) -> str:
        return os.path.join(self.root, "subjects")

    def verify(self) -> list[str]:
        """Re-check every copied file against the repository. Returns divergences."""
        bad = []
        for rel in CORE_FILES:
            src = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
            dst = os.path.join(self.root, rel.replace("/", os.sep))
            if not os.path.isfile(dst):
                bad.append(f"{rel}: missing from sandbox")
            elif sha256(dst) != self.hashes.get(rel):
                bad.append(f"{rel}: sandbox copy changed since it was made")
            elif os.path.isfile(src) and sha256(src) != self.hashes.get(rel):
                bad.append(f"{rel}: repository copy changed during the run")
        return bad

    def manifest(self) -> dict:
        return {
            "run_id": self.run_id, "commit": self.commit,
            "core_files_uncommitted": self.dirty, "sha256": self.hashes,
            "extraction_core_modified": False,
        }


def make(run_id: str | None = None) -> Sandbox:
    run_id = run_id or time.strftime("%Y%m%dT%H%M%S")
    root = os.path.join(SANDBOX_ROOT, run_id)
    hashes = {}
    for rel in CORE_FILES:
        src = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            raise FileNotFoundError(f"extraction core file missing from the repository: {rel}")
        dst = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        hashes[rel] = sha256(dst)
        if hashes[rel] != sha256(src):
            raise RuntimeError(f"copy of {rel} does not match the original")
    for sub in ("data", "subjects", "dist"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    sb = Sandbox(run_id=run_id, root=root, commit=git_commit(), hashes=hashes,
                 dirty=git_dirty_core())
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(sb.manifest(), f, indent=2)
    return sb


def discard(sb: Sandbox) -> None:
    shutil.rmtree(sb.root, ignore_errors=True)
