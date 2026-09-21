"""Benchmark 3: PMOA-TTS (arXiv 2505.20323) and the relative-timeline framework it
evaluates (arXiv 2504.12350).

Built first, deliberately. Its metric matches events by embedding distance and never
compares categories, so this adapter exercises the whole input/output path -- slug
rules, scope gate, output discovery, date handling, scoring -- with no taxonomy mapping
to debug at the same time. Anything that breaks here is plumbing.

It is also the hardest generalization test of the five: same mechanism, entirely
different subject matter. Two things in the pipeline resist that, and both are handled
here in the open rather than worked around quietly.

1. THE SCOPE GATE. SCOPE_DEFINITION is in the prompt on every call, with or without
   --strict-scope (build_site.py builds it into the system message unconditionally). It
   asks for "biographical or historical retrospective essays that follow a specific
   person's life intertwined with a specific technology's development". A clinical case
   report is a single-person life narrative, but it is not that, and a `fits: false`
   verdict means nothing is written at all.

   This adapter does not try to defeat the gate. It offers three framings, records which
   one was used in `BenchmarkDoc.transform`, and the runner captures the scope verdict
   for every document via --scope-out so that scope-gate attrition is a reported number
   in every results table:

       none         the case report as published. The honest baseline, and the one that
                    measures what the pipeline does with out-of-genre input.
       minimal      one header line naming the genre: a case history of one patient.
       biographical a header framing the report as a medical biography of the patient.

   Running all three is the experiment. If attrition is 100% at `none` and low at
   `biographical`, the finding is that the gate, not the extractor, is what does not
   generalize -- which is a result about the architecture and belongs in the paper.

2. THE ISO DATE REQUIREMENT. Every event needs a date: "however imprecise ... never
   undated" (schema/README.md), stored as ISO sort_start/sort_end. Case reports carry
   relative times only ("three days later"), and PMOA-TTS timestamps them in hours from
   presentation. With no absolute date anywhere in the text, a faithful extractor should
   produce no events at all -- the rules forbid inventing one.

   So the input adapter can prepend an anchor line stating the presentation date, which
   makes the relative expressions resolvable without adding any clinical content, and
   the output adapter converts the resulting ISO dates back to hours from that anchor.
   The anchor is disclosed in `transform`, and `--no-anchor` runs without it. The
   difference between the two is a measurement of how much of the pipeline's difficulty
   here is the date requirement rather than the extraction itself.

   What the anchor cannot repair: biograph's finest precision is one day, PMOA-TTS's is
   one hour. Events the pipeline places on the same day are tied. score.py counts those
   ties separately so a concordance depressed by the schema's resolution floor is not
   reported as an ordering error.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Iterable

from ...harness import coverage
from ...harness.interface import (BenchmarkDoc, Extraction, Prediction, ScoreReport)
from . import score as scoring

#: Arbitrary and disclosed. Only offsets from it are ever scored, so its value cannot
#: affect a result -- but it has to be early enough that a long "70 years ago" history
#: still lands on a four-digit year, which schema/date.schema.json requires.
ANCHOR = dt.date(2000, 1, 1)

FRAMINGS = {
    "none": "",
    "minimal": (
        "[Clinical case history of a single patient, reported in the order events "
        "occurred.]\n\n"
    ),
    "biographical": (
        "[A medical biography of one patient: the course of a single person's life and "
        "illness, followed chronologically from before presentation through treatment "
        "and outcome, as reported by their clinicians.]\n\n"
    ),
}


def anchor_line(anchor: dt.date = ANCHOR) -> str:
    return (f"[Reference date for this case: the patient presented on "
            f"{anchor.strftime('%d %B %Y')}. Relative expressions in the text "
            f"(\"three days later\", \"two years earlier\") are dated from it.]\n\n")


def slugify(doc_id: str, prefix: str = "pmoa") -> str:
    """build_site.py exits unless the slug matches ^[a-z][a-z0-9_]*$."""
    body = re.sub(r"[^a-z0-9]+", "_", str(doc_id).lower()).strip("_") or "doc"
    return f"{prefix}_{body}"


# --------------------------------------------------------------------- loading
#
# What the release actually contains, confirmed against the files rather than the paper:
#
#   * NO document text, in any split. The fields are pmc_id, case_report_id,
#     textual_timeseries, demographics, diagnoses, death_info. The case report itself has
#     to be fetched from PubMed Central by case_report_id -- see pmc.py, which reproduces
#     the authors' own ==== Body / ==== Ref boundary.
#
#   * NO human reference timelines. `case_study_100` is manually reviewed for
#     SINGLE-CASE VALIDITY, not for timeline correctness; its textual_timeseries is
#     LLaMA 3.3 output like every other split. The clinician-curated set behind the
#     published 0.80 recall / 0.95 concordance is in neither the HuggingFace release nor
#     the GitHub repository, which ships only the evaluation code and expects the caller
#     to point it at their own manual directory.
#
# So scoring against this corpus measures AGREEMENT WITH A PUBLISHED LLM ANNOTATION, not
# accuracy against human gold, and it is not directly comparable to the published
# numbers. That is why `agreement_ceiling()` exists: the two released annotators, LLaMA
# 3.3 and DeepSeek-R1, cover the same 24,746 cases, so scoring one against the other with
# this same metric gives the band a competent system lands in. biograph's number is
# reported against that band, not against a baseline measured on data nobody can obtain.

SPLITS = {
    "case_study_100": "case_study_100.parquet",       # 88 manually validated single-case
    "l33_25k": "case_study_25k_L33.parquet",          # 24,746, LLaMA 3.3
    "dsr1_25k": "case_study_25k_DSR1.parquet",        # the same 24,746, DeepSeek-R1
}


def read_split(data_root: str, split: str):
    import pandas as pd
    fn = SPLITS.get(split, split)
    path = os.path.join(data_root, fn)
    if not os.path.isfile(path):
        raise SystemExit(
            f"{path} not found. Download the split from HuggingFace first, e.g.\n"
            f"  curl -sL -o {path} \\\n"
            f"    https://huggingface.co/datasets/snoroozi/pmoa-tts/resolve/main/"
            f"data/{os.path.splitext(fn)[0]}-00000-of-00001.parquet")
    return pd.read_parquet(path)


def timeline_of(row) -> list[tuple[str, float]]:
    """textual_timeseries -> the (event, hours) pairs score.py works in."""
    return [(str(e["event"]).strip(), float(e["time"]))
            for e in list(row["textual_timeseries"])
            if str(e.get("event", "")).strip()]


#: Gold rows that are patient ATTRIBUTES rather than occurrences: "53 years old",
#: "male", "Caucasian". They head most timelines at time 0. biograph will never emit
#: them -- schema/README.md: "an event is a dateable occurrence, not a fact or a
#: description" -- so they are an unreachable share of recall that is a property of the
#: two schemas disagreeing, not of extraction quality.
#:
#: The headline metric stays the benchmark's own, computed over ALL gold events. This
#: partition is reported beside it, labelled, so the paper can say how much of the gap
#: is definitional. It is never substituted for the headline number.
_ATTRIBUTE_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)?[\s-]*(?:year|month|week|day)s?(?:[\s-]*old)?"
    r"|male|female|man|woman|boy|girl"
    r"|caucasian|asian|african[\s-]american|hispanic|white|black"
    r"|not specified|unknown)\s*$", re.I)


def is_attribute(event_text: str) -> bool:
    return bool(_ATTRIBUTE_RE.match(event_text))


def partition_gold(gold: list[tuple[str, float]]):
    """(occurrences, attributes) -- the scoreable subset and the definitional floor."""
    attrs = [g for g in gold if is_attribute(g[0])]
    return [g for g in gold if not is_attribute(g[0])], attrs


# --------------------------------------------------------------------- adapter

class PmoaTtsAdapter:
    name = "pmoa_tts"
    citation = "arXiv:2505.20323 (corpus); arXiv:2504.12350 (framework)"
    license = ("CC BY-NC-SA 4.0 -- the dataset card's own metadata and the "
               "jcweiss2/pmoa_tts README agree; the paper's 'CC BY 4.0' is the outlier. "
               "NON-COMMERCIAL and SHARE-ALIKE: not redistributed here, and derived "
               "artifacts published with the paper would inherit the terms. Case report "
               "text comes separately from PMC Open Access, under each article's own "
               "licence.")
    label_space = ("<untyped>",)
    metric = ("event recall at cosine distance < 0.1 (S-PubMedBert-MS-MARCO), "
              "temporal concordance (c-index), AULTC")
    #: As published: O1-preview event recall 0.80, concordance 0.95; Llama-3.3-70B
    #: median c-index 0.96 -- measured against a clinician-curated reference set that is
    #: in NEITHER the HuggingFace release nor the GitHub repository. It is carried here
    #: for citation, and it is NOT the bar a run against this corpus clears: see
    #: agreement_ceiling() for the reference band that can actually be reproduced.
    published_baseline = {"event_recall": 0.80, "concordance": 0.95}
    published_baseline_note = ("measured against an undistributed clinician reference; "
                               "not reproducible from the release, not directly "
                               "comparable to a run scored against the LLM annotations")

    def __init__(self, framing: str = "minimal", anchor: dt.date | None = ANCHOR,
                 split: str = "case_study_100", matcher: str = "embedding",
                 threshold: float | None = None, include_description: bool = False,
                 max_chars: int = 180_000):
        if framing not in FRAMINGS:
            raise ValueError(f"framing must be one of {sorted(FRAMINGS)}")
        self.framing = framing
        self.anchor = anchor
        self.split = split
        self.matcher = matcher
        self.threshold = threshold
        self.include_description = include_description
        self.max_chars = max_chars
        #: filled by load(), reported by score(): documents lost before extraction.
        self.load_attrition: dict[str, int] = {"no_oa_text": 0, "no_gold_events": 0}

    # ------------------------------------------------------------ input adapter

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        from .pmc import PmcFetcher, PmcFetchError

        frame = read_split(data_root, self.split)
        fetcher = PmcFetcher(cache_dir=os.path.join(data_root, "pmc_cache"))
        yielded = 0
        for _, row in frame.iterrows():
            if limit is not None and yielded >= limit:
                return
            pmcid = str(row["case_report_id"])
            gold = timeline_of(row)
            if not gold:
                self.load_attrition["no_gold_events"] += 1
                continue
            try:
                text = fetcher.body_text(pmcid)
            except PmcFetchError:
                text = ""
            if not text:
                # Not in the OA subset, or no body passages. Counted, never replaced by
                # the abstract: a timeline scored against a document the annotators did
                # not see is not a measurement.
                self.load_attrition["no_oa_text"] += 1
                continue

            transform = [f"framing={self.framing}", f"reference_split={self.split}",
                         "text=PMC BioC body passages (== get_pmoa_body.sh boundary)"]
            body = FRAMINGS[self.framing]
            if self.anchor:
                body += anchor_line(self.anchor)
                transform.append(f"anchor={self.anchor.isoformat()}")
            body += text
            if len(body) > self.max_chars:
                # build_site.py truncates at --max-chars anyway; doing it here means the
                # text the grounding check compares against is the text that was sent.
                body = body[:self.max_chars]
                transform.append(f"truncated={self.max_chars}")

            yielded += 1
            yield BenchmarkDoc(
                doc_id=pmcid, slug=slugify(pmcid), name=f"Patient {pmcid}",
                text=body, gold=gold, transform=tuple(transform),
                meta={"n_gold_events": len(gold), "body_chars": len(text),
                      "demographics": dict(row["demographics"]) if row.get(
                          "demographics") is not None else {}},
            )

    # ------------------------------------------------------------ output adapter

    def _event_text(self, event: dict[str, Any]) -> str:
        label = (event.get("label") or "").strip()
        if self.include_description and (event.get("description") or "").strip():
            return f"{label}. {event['description'].strip()}"
        return label

    def _hours(self, date: dict[str, Any]) -> float | None:
        """Midpoint of the fuzzy date's interval, in hours from the anchor.

        The midpoint, not sort_start: a `range` or `decade` precision date asserts only
        that the event falls somewhere inside its bounds, and taking the earliest bound
        would systematically bias every imprecise event toward the past. The interval's
        width is reported separately via `lossy` so a prediction that commits to a decade
        is not mistaken for one that commits to a day."""
        if not self.anchor:
            return None
        try:
            lo = dt.date.fromisoformat(date["sort_start"])
            hi = dt.date.fromisoformat(date["sort_end"])
        except (KeyError, TypeError, ValueError):
            return None
        mid = lo + (hi - lo) / 2
        return (mid - self.anchor).total_seconds() / 3600.0

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        items: list[tuple[str, float]] = []
        unmapped: list[tuple[str, str, str, str]] = []
        lossy: list[tuple[str, str, str, str]] = []

        for event in extraction.events_sorted():
            text = self._event_text(event)
            hours = self._hours(event.get("date") or {})
            if not text:
                unmapped.append(("event", event.get("id", "?"),
                                 event.get("event_type", "?"), "no label to match on"))
                continue
            if hours is None:
                unmapped.append(("event", event.get("id", "?"),
                                 event.get("event_type", "?"),
                                 "no anchor, or unparseable date: no hours offset"))
                continue
            precision = (event.get("date") or {}).get("precision", "?")
            if precision not in ("day",):
                lossy.append(("event", event.get("id", "?"), event.get("event_type", "?"),
                              f"date precision {precision}: midpoint of a "
                              f"{(event['date'].get('sort_end') or '')[:4]}-bounded "
                              f"interval stands in for an hour-resolution timestamp"))
            items.append((text, hours))

        for rel in extraction.relations:
            unmapped.append(("relation", rel.get("id", "?"), rel.get("type", "?"),
                             "PMOA-TTS is (event, time) tuples; relations have no "
                             "counterpart in its label space"))

        return Prediction(doc_id=doc.doc_id, items=tuple(items),
                          unmapped=tuple(unmapped), lossy=tuple(lossy),
                          meta={"n_events": len(extraction.events),
                                "transform": doc.transform})

    # ------------------------------------------------------------ scorer

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]],
              extractions: dict[str, Extraction] | None = None) -> ScoreReport:
        extractions = extractions or {}
        per_doc: list[scoring.DocScore] = []
        attrition = {"out_of_scope": 0, "empty_extraction": 0,
                     "no_gold_timeline": 0, "did_not_validate": 0}
        # Documents lost before extraction ever ran, carried from load(). Reporting only
        # post-extraction attrition would quietly shrink the denominator.
        attrition.update(self.load_attrition)
        unmapped_total = lossy_total = 0
        per_doc_occ: list[scoring.DocScore] = []
        attribute_gold = total_gold = 0

        pairs = list(pairs)
        for doc, pred in pairs:
            ex = extractions.get(doc.doc_id)
            if ex is not None and not ex.in_scope:
                attrition["out_of_scope"] += 1
            if ex is not None and ex.exit_code != 0 and not ex.empty:
                attrition["did_not_validate"] += 1
            if not doc.gold:
                attrition["no_gold_timeline"] += 1
                continue
            if not pred.items:
                attrition["empty_extraction"] += 1
            unmapped_total += len(pred.unmapped)
            lossy_total += len(pred.lossy)
            per_doc.append(scoring.score_document(
                doc.doc_id, doc.gold, pred.items,
                matcher=self.matcher, threshold=self.threshold))
            # Same metric, restricted to gold rows that are occurrences rather than
            # patient attributes. Reported beside the headline number, never instead.
            occurrences, attributes = partition_gold(list(doc.gold))
            attribute_gold += len(attributes)
            total_gold += len(doc.gold)
            if occurrences:
                per_doc_occ.append(scoring.score_document(
                    doc.doc_id, occurrences, pred.items,
                    matcher=self.matcher, threshold=self.threshold))

        def _median(vals):
            vals = sorted(v for v in vals if v is not None)
            if not vals:
                return None
            k = len(vals) // 2
            return vals[k] if len(vals) % 2 else (vals[k - 1] + vals[k]) / 2

        scores = {}
        for key, getter in (("event_recall", lambda d: d.event_recall),
                            ("concordance", lambda d: d.concordance),
                            ("aultc", lambda d: d.aultc),
                            ("median_abs_error_hours", lambda d: d.median_abs_error_hours)):
            m = _median([getter(d) for d in per_doc])
            if m is not None:
                scores[key] = m
        ties = sum(d.tied_predictions for d in per_doc)
        comparable = sum(d.comparable_pairs for d in per_doc)
        if comparable:
            scores["tied_pair_rate"] = ties / comparable

        # Diagnostic, clearly separated by the `diagnostic_` prefix: the same metric over
        # the gold rows that are occurrences rather than patient attributes.
        occ_recall = _median([d.event_recall for d in per_doc_occ])
        if occ_recall is not None:
            scores["diagnostic_recall_occurrences_only"] = occ_recall
        if total_gold:
            scores["diagnostic_attribute_share_of_gold"] = attribute_gold / total_gold

        notes = [
            f"matcher={self.matcher}, threshold="
            f"{self.threshold if self.threshold is not None else scoring.MATCHERS[self.matcher][1]}"
            " (the benchmark's own setting)",
            f"framing={self.framing}, anchor="
            f"{self.anchor.isoformat() if self.anchor else 'none'}",
            f"{scores.get('tied_pair_rate', 0):.1%} of comparable pairs are tied in the "
            f"prediction because biograph dates resolve to one day and PMOA-TTS "
            f"timestamps to one hour; ties score 0.5",
            f"{unmapped_total} extracted items had no expression in this label space "
            f"({lossy_total} more were projected with a named loss)",
            f"{attribute_gold}/{total_gold} gold rows are patient attributes "
            f"('53 years old', 'male') rather than dateable occurrences. biograph cannot "
            f"emit those by definition; event_recall is the benchmark's own metric over "
            f"all gold, diagnostic_recall_occurrences_only is the same metric over the "
            f"rest. The first is the number to report.",
            "published_baseline is NOT the bar this run clears: "
            + self.published_baseline_note + ". Use --ceiling for a reproducible band.",
        ]
        return ScoreReport(
            benchmark=self.name, metric=self.metric, scores=scores,
            published_baseline=dict(self.published_baseline), attrition=attrition,
            n_docs=len(per_doc), notes=notes,
            per_label={"<untyped>": {"n_documents": float(len(per_doc))}},
        )

    # ------------------------------------------------------------ reference band

    @staticmethod
    def agreement_ceiling(data_root: str, n: int = 200, matcher: str = "embedding",
                          threshold: float | None = None, seed: int = 0) -> ScoreReport:
        """Score DeepSeek-R1's released timelines against LLaMA 3.3's, same metric.

        No model is called and no text is fetched: both annotations are in the release,
        paired over the same 24,746 cases. This is the number that makes biograph's
        interpretable. The published 0.80/0.95 were measured against a clinician set that
        is not distributed, so it cannot be reproduced here and should not be quoted as
        though it were the bar this run cleared; two competent LLM annotators scored
        against each other can be, and is the honest reference band."""
        import random

        l33 = read_split(data_root, "l33_25k").set_index("case_report_id")
        dsr1 = read_split(data_root, "dsr1_25k").set_index("case_report_id")
        shared = sorted(set(l33.index) & set(dsr1.index))
        random.Random(seed).shuffle(shared)
        shared = shared[:n]

        per_doc = [
            scoring.score_document(cid, timeline_of(l33.loc[cid]),
                                   timeline_of(dsr1.loc[cid]),
                                   matcher=matcher, threshold=threshold)
            for cid in shared
        ]

        def _median(vals):
            vals = sorted(v for v in vals if v is not None)
            if not vals:
                return None
            k = len(vals) // 2
            return vals[k] if len(vals) % 2 else (vals[k - 1] + vals[k]) / 2

        scores = {}
        for key, get in (("event_recall", lambda d: d.event_recall),
                         ("concordance", lambda d: d.concordance),
                         ("aultc", lambda d: d.aultc),
                         ("median_abs_error_hours", lambda d: d.median_abs_error_hours)):
            m = _median([get(d) for d in per_doc])
            if m is not None:
                scores[key] = m
        return ScoreReport(
            benchmark="pmoa_tts/agreement_ceiling", metric=PmoaTtsAdapter.metric,
            scores=scores, n_docs=len(per_doc),
            notes=[
                "DeepSeek-R1 timelines scored against LLaMA 3.3 timelines, both from the "
                "released corpus, over the cases they share.",
                "This is an inter-annotator band, not a gold-standard accuracy. It is "
                "reported because the clinician reference behind the published "
                "0.80 recall / 0.95 concordance is not distributed in either the "
                "HuggingFace release or the GitHub repository.",
                f"matcher={matcher}, n={len(per_doc)}, seed={seed}",
            ],
        )

    # ------------------------------------------------------------ matrix column

    def coverage(self) -> dict[str, tuple[str, str]]:
        _, table, _ = coverage.build()
        col = coverage.PMOA_TTS["column"]
        return {row["type"]: row[col] for row in table}
