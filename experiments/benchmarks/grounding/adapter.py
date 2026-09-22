"""Benchmark 5: Grounding -- does the extractor cite text that is actually there?

Not an external dataset, and the only one of the five with no licence question and no
model call. The gold is the source document itself, and the check is a string search:
every `sources[].quote` must occur verbatim in the text the model read, and every entity
name must appear in it too.

WHY THIS IS WORTH A BENCHMARK SLOT. Benchmarks 1-4 ask whether the extracted graph agrees
with someone else's annotations. None of them asks whether it agrees with the *document*.
An extraction can score well on a relation benchmark while citing a quote nobody wrote,
and that failure is invisible to every other metric here. It is also the failure that
matters most for a corpus meant to be cited: a wrong relation is an error, a fabricated
quotation is a different kind of thing.

WHAT IT IS NOT. This measures the corpus biograph has already produced. It is an audit,
not a held-out evaluation -- there is no train/test split and nothing is predicted about
unseen data. Reported as such. The generalization claim rests on benchmarks 1 and 2; this
one rests on nothing but the corpus's own honesty, which is exactly what it is for.

THE CHECK IS NEVER REIMPLEMENTED HERE. build_site.py --check-grounding already does it,
including the details that make it fair: whitespace and hyphenation are flattened before
comparison because PDF extraction introduces both, an elided quote ("... [...] ...") is
split on the ellipsis and each fragment checked separately rather than being reported as
fabricated, and entity names are matched on their longest word so that "J. B. Goodenough"
in the document satisfies "John B. Goodenough" in the graph. Reimplementing any of that
here would produce a second, subtly different checker and a number that does not describe
the shipped tool. This adapter shells out and parses, like the rest of the harness.

REACH IS PART OF THE RESULT. `quote` is optional in the schema -- "only for pivotal
events, not every one" -- so the check cannot reach a citation that carries only a page
number. The share of citations that carry a quote is therefore reported alongside the
verbatim rate, because a 100% verbatim rate over 18% of citations is not the same claim as
one over 98%.

No sandbox. The other benchmarks need one because build_site.py writes into subjects/ as a
side effect of extraction; --check-grounding writes nothing at all, and the corpus under
subjects/ is the subject of this measurement rather than a place to put its output. The
core's SHA-256 and the git commit are still recorded, so the report still says exactly
which checker produced the numbers.
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import Any, Iterable

from ...harness import coverage as coverage_mod
from ...harness import sandbox
from ...harness.interface import (BenchmarkDoc, Extraction, GroundingReport, Prediction,
                                  ScoreReport)
from ...harness.runner import parse_grounding

REPO_ROOT = sandbox.REPO_ROOT
BUILD_SITE = os.path.join(REPO_ROOT, "scripts", "build_site.py")


def subject_dirs(subjects_root: str) -> list[tuple[str, str, str]]:
    """(domain, slug, path) for every subject, under the domain layout or flat."""
    out = []
    for path in sorted(glob.glob(os.path.join(subjects_root, "*", "*"))):
        if not os.path.isdir(path):
            continue
        parts = path.replace(os.sep, "/").split("/")
        if os.path.isfile(os.path.join(path, "subject.json")):
            out.append((parts[-2], parts[-1], path))
    return out


class GroundingAdapter:
    name = "grounding"
    citation = "no external corpus -- scripts/build_site.py --check-grounding over subjects/"
    license = "not an external dataset; nothing is downloaded and nothing is redistributed"
    label_space = ("<untyped>",)
    metric = ("verbatim quote rate and entity-name presence, as reported by "
              "build_site.py --check-grounding")
    published_baseline: dict[str, float] = {}
    published_baseline_note = (
        "there is no external baseline: no other system extracts this schema from these "
        "documents. The meaningful comparison is against 1.0, and against the reach figure "
        "reported beside it.")

    def __init__(self, subjects_root: str | None = None, timeout: int = 300):
        self.subjects_root = subjects_root or os.path.join(REPO_ROOT, "subjects")
        self.timeout = timeout

    # -------------------------------------------------------------- audit

    def audit(self, limit: int | None = None, verbose: bool = True) -> ScoreReport:
        """Run the shipped checker over every subject and aggregate. No model call."""
        targets = subject_dirs(self.subjects_root)
        if limit:
            targets = targets[:limit]
        if not targets:
            raise SystemExit("grounding: no subjects under %s" % self.subjects_root)

        reports: list[tuple[str, str, GroundingReport | None]] = []
        unparsed: list[str] = []
        for i, (domain, slug, _path) in enumerate(targets, 1):
            proc = subprocess.run(
                [sys.executable, BUILD_SITE, slug, "--check-grounding"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=REPO_ROOT, timeout=self.timeout)
            report = parse_grounding(proc.stdout)
            if report is None:
                # Exit code 1 means "issues found", which is a result. A missing summary
                # line means the checker could not run at all, which is not.
                unparsed.append("%s: %s" % (slug, (proc.stdout + proc.stderr).strip()[:120]))
            reports.append((domain, slug, report))
            if verbose:
                if report is None:
                    print("  [%d/%d] %-22s could not be checked" % (i, len(targets), slug))
                else:
                    print("  [%d/%d] %-22s %d/%d quotes, %d/%d names"
                          % (i, len(targets), slug, report.quotes_verbatim,
                             report.quotes_checked, report.entities_present,
                             report.entities_checked))
        return self._aggregate(reports, unparsed, diagnostic=self.diagnose(reports),
                               overwritten=self.overwritten_subjects())

    # -------------------------------------------------------------- diagnostic

    @staticmethod
    def _flat(s: str) -> str:
        return " ".join(str(s).split())

    @staticmethod
    def _nospace(s: str) -> str:
        return re.sub(r"\s+", "", str(s))

    #: "    event abel_war_office: misquoted (62% ...) -- '...'"
    ISSUE = re.compile(r"^\s+(event|relation|entity) (\S+?): (NOT IN SOURCE|misquoted|name not in source)")

    def overwritten_subjects(self) -> dict[str, list[str]]:
        """Subjects whose source text cannot verify, because a second document overwrote it.

        Source text is staged as data/<slug>.txt -- keyed by the *subject*, not the
        document -- so when a subject gains a second document the first one's text is
        replaced. Both documents' sources.json still point at that one path, so every quote
        from the losing document is checked against a paper it did not come from and can
        only ever be reported as absent.

        This is a provenance bug in the pipeline, not a property of the extractor, and the
        quotes it affects are unverifiable rather than wrong. They are excluded from the
        rates and counted separately, because scoring a quote against text that no longer
        exists measures the staging layout and nothing else.
        """
        out: dict[str, list[str]] = {}
        for _domain, slug, path in subject_dirs(self.subjects_root):
            owners: dict[str, set[str]] = defaultdict(set)
            for docdir in sorted(glob.glob(os.path.join(path, "*"))):
                spath = os.path.join(docdir, "sources.json")
                if not os.path.isfile(spath):
                    continue
                try:
                    srcs = json.load(io.open(spath, encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for s in srcs:
                    f = s.get("file") if isinstance(s, dict) else None
                    if f:
                        owners[f].add(os.path.basename(docdir))
            shared = sorted({d for f, ds in owners.items() if len(ds) > 1 for d in ds})
            if shared:
                out[slug] = shared
        return out

    def _subject_index(self, path: str):
        """(quotes by item id, source text) for one subject, as --check-grounding sees it."""
        quotes: dict[str, list[str]] = defaultdict(list)
        text = ""
        for docdir in sorted(glob.glob(os.path.join(path, "*"))):
            spath = os.path.join(docdir, "sources.json")
            if not os.path.isfile(spath):
                continue
            try:
                srcs = json.load(io.open(spath, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for s in srcs:
                f = s.get("file") if isinstance(s, dict) else None
                if not f:
                    continue
                local = os.path.join(REPO_ROOT, f.replace("\\", os.sep).replace("/", os.sep))
                if os.path.isfile(local):
                    try:
                        text += io.open(local, encoding="utf-8", errors="replace").read()
                    except OSError:
                        pass
            for kind in ("events.json", "relations.json"):
                ipath = os.path.join(docdir, kind)
                if not os.path.isfile(ipath):
                    continue
                try:
                    items = json.load(io.open(ipath, encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for item in items:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    for cite in item.get("sources") or []:
                        q = (cite or {}).get("quote") if isinstance(cite, dict) else None
                        if (q or "").strip():
                            quotes[str(item["id"])].append(q)
        return quotes, text

    def diagnose(self, reports) -> dict[str, int]:
        """Explain what the shipped checker's NOT IN SOURCE verdicts are actually made of.

        A DIAGNOSTIC, never a second verdict: it starts from --check-grounding's own issue
        lines and only asks what they contain. It exists because inspecting failures by
        hand showed "not in source" bundling three unlike things, and reporting their sum
        as a hallucination rate would be an overclaim.

        The model sometimes emits a quote with its whitespace destroyed --
        'developedbyEmilvonBehringandShibasaburoKitasatoin1890' -- which can match nothing,
        though its content is plainly in the document. Others differ only in case. Neither
        is an invented sentence, and both are separable: re-test the flagged quote with
        whitespace removed from both sides, then with case folded too.

        What survives both relaxations is the set worth reading: text that is not in the
        document in any form. Note the asymmetry -- this only ever *reduces* the
        fabrication count, so it cannot flatter the pipeline by accident.
        """
        by_slug = {slug: path for _d, slug, path in subject_dirs(self.subjects_root)}
        # A subject whose source text was overwritten cannot be diagnosed either: its
        # quotes are being compared with a document they never came from.
        overwritten = set(self.overwritten_subjects())
        flagged = ws_only = case_only = unexplained = unmatched = 0
        for _domain, slug, r in reports:
            if r is None or slug not in by_slug or slug in overwritten:
                continue
            ids = [m.group(2) for m in (self.ISSUE.match(ln) for ln in r.issues)
                   if m and m.group(3) == "NOT IN SOURCE"]
            if not ids:
                continue
            quotes, text = self._subject_index(by_slug[slug])
            if not text:
                continue
            nos_hay = self._nospace(text)
            fold_hay = nos_hay.casefold()
            for item_id in ids:
                flagged += 1
                cands = quotes.get(item_id) or []
                if not cands:
                    unmatched += 1
                    continue
                if any(self._nospace(q) in nos_hay for q in cands):
                    ws_only += 1
                elif any(self._nospace(q).casefold() in fold_hay for q in cands):
                    case_only += 1
                else:
                    unexplained += 1
        return {"flagged_not_in_source": flagged,
                "recovered_by_ignoring_whitespace": ws_only,
                "recovered_by_ignoring_case_too": case_only,
                "not_in_the_document_in_any_form": unexplained,
                "quote_not_found_for_the_flagged_id": unmatched}

    # -------------------------------------------------------------- Protocol

    def load(self, data_root: str | None = None, limit: int | None = None
             ) -> Iterable[BenchmarkDoc]:
        """One doc per subject. `text` is empty on purpose: nothing here is extracted.

        This benchmark audits graphs that already exist, so there is no input to send to a
        model. The method is implemented for uniformity with the other four adapters, and
        returns the audit targets rather than extraction inputs."""
        root = data_root or self.subjects_root
        for i, (domain, slug, path) in enumerate(subject_dirs(root)):
            if limit and i >= limit:
                return
            yield BenchmarkDoc(doc_id=slug, slug=slug, name=slug, text="", gold=None,
                               transform=("no_extraction",),
                               meta={"domain": domain, "path": path})

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        """Carry through the GroundingReport the runner already attached.

        Nothing is recomputed. Runner.check_grounding shells out to the same
        --check-grounding this benchmark uses, so benchmarks 1-4 can feed their own
        extractions to score() below and get figures on the same footing as the corpus
        audit."""
        if extraction.grounding is None:
            return Prediction(doc_id=doc.doc_id, items=(), meta={"grounding": None})
        return Prediction(doc_id=doc.doc_id, items=(extraction.grounding,),
                          meta={"grounding": True})

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]]) -> ScoreReport:
        reports = []
        unparsed = []
        for doc, pred in pairs:
            report = pred.items[0] if pred.items else None
            if report is None:
                unparsed.append(doc.doc_id)
            reports.append((doc.meta.get("domain", ""), doc.doc_id, report))
        return self._aggregate(reports, unparsed)

    # -------------------------------------------------------------- aggregate

    def _aggregate(self, reports, unparsed, diagnostic=None, overwritten=None) -> ScoreReport:
        overwritten = overwritten or {}
        qv = qc = ep = ec = 0
        fabricated = misquoted = 0
        skipped_overwritten = 0
        per_domain: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        imperfect: list[tuple[str, int, int]] = []
        for domain, slug, r in reports:
            if r is None:
                continue
            if slug in overwritten:
                # Its quotes are checked against a document they did not come from, so
                # they are unverifiable rather than wrong. Counted, never scored.
                skipped_overwritten += 1
                continue
            # "Off by one word" and "invented outright" are different findings, and the
            # summary line collapses them. check_grounding already separates the two by
            # 5-word shingle overlap -- below 50% is NOT IN SOURCE, above is `misquoted` --
            # so the distinction is tallied from its own issue lines rather than recomputed.
            fabricated += sum(1 for ln in r.issues if "NOT IN SOURCE" in ln)
            misquoted += sum(1 for ln in r.issues if "misquoted" in ln)
            qv += r.quotes_verbatim
            qc += r.quotes_checked
            ep += r.entities_present
            ec += r.entities_checked
            d = per_domain[domain]
            d[0] += r.quotes_verbatim
            d[1] += r.quotes_checked
            d[2] += r.entities_present
            d[3] += r.entities_checked
            if r.quotes_checked and r.quotes_verbatim < r.quotes_checked:
                imperfect.append((slug, r.quotes_checked - r.quotes_verbatim,
                                  r.quotes_checked))

        # How far the check can see: a citation with no quote is outside it entirely.
        quoted = total = 0
        for got, seen in coverage_mod.measure_quote_coverage(self.subjects_root).values():
            quoted += got
            total += seen

        scores = {
            # The headline for "does it invent quotations". A misquote is a different and
            # much milder finding, so the two are never added together here.
            "quote_fabrication_rate": round(fabricated / qc, 4) if qc else 0.0,
            "quote_misquotation_rate": round(misquoted / qc, 4) if qc else 0.0,
            "quote_verbatim_rate": round(qv / qc, 4) if qc else 0.0,
            "entity_name_present_rate": round(ep / ec, 4) if ec else 0.0,
            "quotes_checked": qc,
            "quotes_fabricated": fabricated,
            "quotes_misquoted": misquoted,
            "entities_checked": ec,
            "citation_reach": round(quoted / total, 4) if total else 0.0,
            "subjects_with_an_unverified_quote": len(imperfect),
        }
        per_label = {}
        for domain, (a, b, c, d) in sorted(per_domain.items()):
            per_label[domain] = {
                "quote_verbatim_rate": round(a / b, 4) if b else 0.0,
                "entity_name_present_rate": round(c / d, 4) if d else 0.0,
                "quotes_checked": b, "support": b,
            }

        notes = [
            "An audit of the corpus that exists, not a held-out evaluation: there is no "
            "split and nothing is predicted about unseen data.",
            "The check is build_site.py --check-grounding, shelled out and parsed. It is "
            "not reimplemented here, so these numbers describe the shipped tool.",
            "Citation reach is %.1f%% (%d of %d citations carry a quote). `quote` is "
            "optional in the schema -- 'only for pivotal events, not every one' -- so a "
            "citation with only a page number is outside this check entirely."
            % (100 * quoted / total if total else 0.0, quoted, total),
            "--check-grounding concatenates every source file belonging to a subject "
            "before searching, so a quote from one document is checked against that "
            "subject's whole corpus. That is the shipped behaviour and is reused as-is.",
            "Fabrication and misquotation are reported apart, because collapsing them is "
            "misleading in both directions. %d quote(s) share under half their 5-word "
            "shingles with the source and are the real finding; %d are mostly present but "
            "not verbatim, which over PDF-extracted text is usually a curly quotation "
            "mark, a ligature or a line-break hyphen rather than an invented sentence. "
            "Read quote_fabrication_rate, not quote_verbatim_rate, as the hallucination "
            "number." % (fabricated, misquoted),
        ]
        if overwritten:
            docs = sum(len(v) for v in overwritten.values())
            notes.append(
                "%d subject(s) covering %d document(s) are excluded from every rate above: "
                "source text is staged as data/<slug>.txt, keyed by subject rather than "
                "document, so a subject's second document overwrote the first one's text. "
                "Both still point at that one path, so the losing document's quotes are "
                "checked against a paper they did not come from. That is a staging bug, "
                "not an extraction failure, and its quotes are unverifiable rather than "
                "wrong: %s." % (len(overwritten), docs,
                                ", ".join(sorted(overwritten)[:6])))
        if diagnostic:
            d = dict(diagnostic)
            scores.update({"diagnostic_" + k: v for k, v in d.items()})
            recovered = (d["recovered_by_ignoring_whitespace"]
                         + d["recovered_by_ignoring_case_too"])
            if d["flagged_not_in_source"]:
                notes.append(
                    "Diagnostic, not a second verdict: of the %d quotes the checker calls "
                    "NOT IN SOURCE, %d match once whitespace is ignored and %d more once "
                    "case is too -- the model emitting a quote with its spacing destroyed, "
                    "not an invented sentence. %d are absent in any form, which is %.2f%% "
                    "of all %d checked quotes and is the number to read as fabrication."
                    % (d["flagged_not_in_source"],
                       d["recovered_by_ignoring_whitespace"],
                       d["recovered_by_ignoring_case_too"],
                       d["not_in_the_document_in_any_form"],
                       100 * d["not_in_the_document_in_any_form"] / qc if qc else 0.0, qc))
                scores["quote_absent_in_any_form_rate"] = (
                    round(d["not_in_the_document_in_any_form"] / qc, 4) if qc else 0.0)
        if imperfect:
            worst = sorted(imperfect, key=lambda x: -x[1])[:5]
            notes.append("subjects with unverified quotes: " + ", ".join(
                "%s (%d/%d)" % (s, bad, seen) for s, bad, seen in worst))
        if unparsed:
            notes.append("%d subject(s) produced no summary line and are excluded from "
                         "every rate above: %s" % (len(unparsed), "; ".join(unparsed[:3])))

        core = {rel: sandbox.sha256(os.path.join(REPO_ROOT, rel.replace("/", os.sep)))
                for rel in sandbox.CORE_FILES
                if os.path.isfile(os.path.join(REPO_ROOT, rel.replace("/", os.sep)))}
        return ScoreReport(
            benchmark=self.name, metric=self.metric, scores=scores,
            published_baseline={},
            not_applicable={
                "precision": "There is no negative class. A quote is in the document or "
                             "it is not; nothing is predicted that gold could contradict.",
                "citations without a quote": "Outside the check by construction. Counted "
                                             "in citation_reach rather than scored.",
            },
            per_label=per_label,
            attrition={"subjects": len(reports), "unparsed": len(unparsed),
                       "subjects_excluded_source_overwritten": skipped_overwritten},
            n_docs=len(reports),
            notes=notes + ["commit %s; core sha256 recorded in the run report"
                           % sandbox.git_commit()[:12]])

    # -------------------------------------------------------------- coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        """B5's column is measured from the corpus, not declared."""
        cells = {}
        for row, (quoted, total) in coverage_mod.measure_quote_coverage(
                self.subjects_root).items():
            rate = quoted / total if total else 0.0
            cell = "untyped" if rate >= coverage_mod.GROUNDING["quote_threshold"] else "partial"
            cells[row] = (cell, "%d/%d citations carry a quote (%.0f%%)"
                          % (quoted, total, 100 * rate))
        return cells


ADAPTER = GroundingAdapter()
