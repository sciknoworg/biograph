"""Benchmark 4: WikiBio (Stranisci et al., ACL 2023; repo marcostranisci/WikiBio).

Twenty complete English Wikipedia biographies of African and African-American writers born
1928-1945, with every event associated with the biography's target person annotated on its
trigger token. 75,088 tokens, 401,332 characters, median document 17,192 characters.

WHY THIS ONE. It is B2's task at the right document length. Same first author, same
annotation philosophy, same trigger-anchored event recall -- but 17,192 characters per
document against BiographicalEvents' 147, and 3,282 gold event spans against 1,589. That
gives a controlled comparison available nowhere else in the suite: the same extractor, on
the same kind of annotation, at two document lengths differing by about 100x. If recall is
much higher here, the sentence-fragment limitation that caveats every B1 and B2 number
stops being an assertion and becomes a measurement.

It also removes the other confound. B2 lost 46% of its corpus to the date requirement,
because the schema cannot represent an undated event. This gold does not ask for dates at
all, so what is measured is purely whether the extractor noticed the life episode.

THE COST. `EVENT` is untyped -- no birth, employment or publication distinction -- so all 22
biograph event types collapse onto one class and type accuracy is unmeasurable in either
direction, exactly as in B2. Scoring is therefore trigger-anchored and type-agnostic.

THE _id COLUMN IS NOT THE SUBJECT'S QID. Every one of the twenty files carries the prefix
`Q560307`, which is Donald Woods -- the subject of file 8091 alone. It is an
annotation-project identifier that was baked into all of them, so it identifies nothing.
The subject is recovered from the first ENTITY span instead, which gives `Ada Aharoni`,
`Lewis Nkosi`, `Ngugi wa Thiong'o` and so on correctly.

TOKENS ARE DETOKENISED, NOT SPACE-JOINED. The release is one row per token, and joining
them with spaces produces `anti - apartheid`, `( 15 December 1933 )` and `activist .` --
prose no biography ever contained, handed to a model asked to read a biography. Spacing is
reconstructed and every gold offset is computed against the text actually produced, so an
annotation always lands on the token it names. Disclosed as `detokenised`.

Nothing is downloaded. load() reads a local copy via --data-root; see
experiments/corpora/wikibio/README.md for provenance and the licence position.
"""
from __future__ import annotations

import csv
import io
import os
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from ...harness.interface import BenchmarkDoc, Extraction, Prediction, ScoreReport

#: The gold class this adapter scores. EVENT-GR (light and grammatical verbs) and
#: EVENT-MOD (modality) are read and counted but not scored: the paper's own corpus figure
#: of 3,290 event mentions is the EVENT column alone, and the other two annotate how an
#: event is expressed rather than that one occurred.
SCORED_LABEL = "EVENT"
CONTEXT_LABELS = ("EVENT-GR", "EVENT-MOD")
SUBJECT_LABEL = "ENTITY"

#: No space before these, and none after an opening bracket or quote.
_NO_SPACE_BEFORE = set(",.;:!?)]}%’”'\"")
_NO_SPACE_AFTER = set("([{$#‘“")
#: A hyphen or slash between two word characters joins them: `anti - apartheid`.
_JOINERS = {"-", "–", "—", "/"}

STOP = {"the", "a", "an", "of", "in", "at", "to", "and", "for", "on", "with", "by", "as",
        "is", "was", "were", "be", "been", "his", "her", "their", "he", "she", "they"}


def _fold(value: Any) -> str:
    flat = "".join(c for c in unicodedata.normalize("NFKD", str(value))
                   if not unicodedata.combining(c))
    return " ".join(flat.casefold().split())


def _content_tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _fold(value)) if t and t not in STOP}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if not s or not s[0].isalpha():
        s = "wb_" + s
    return s[:60] or "wb_doc"


def detokenise(tokens: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Join tokens into prose, returning the text and each token's (start, end).

    The offsets are the point. A gold annotation names a token, and it has to land on that
    token in the text the model actually read -- so spacing is decided and the position
    recorded in the same pass rather than reconstructed afterwards.
    """
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for i, token in enumerate(tokens):
        if i == 0:
            sep = ""
        elif token and token[0] in _NO_SPACE_BEFORE:
            sep = ""
        elif parts and parts[-1] and parts[-1][-1] in _NO_SPACE_AFTER:
            sep = ""
        elif token in _JOINERS or (parts and parts[-1] in _JOINERS):
            # Only when it really joins two words; a dash between dates keeps its spaces.
            prev = parts[-1] if parts else ""
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            # Letters only, not digits: `anti - apartheid` is one word, but the dash in
            # `(15 December 1933 - 19 August 2001)` separates two dates and keeps its
            # spaces. Joining on alnum collapsed that to `1933-19`.
            joins = (token in _JOINERS and prev[-1:].isalpha() and nxt[:1].isalpha()) or \
                    (prev in _JOINERS and token[:1].isalpha()
                     and len(parts) > 1 and parts[-2][-1:].isalpha())
            sep = "" if joins else " "
        else:
            sep = " "
        if sep:
            parts.append(sep)
            cursor += len(sep)
        start = cursor
        parts.append(token)
        cursor += len(token)
        spans.append((start, cursor))
    return "".join(parts), spans


def _read_tokens(path: str) -> list[dict]:
    with io.open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return []
    missing = [c for c in ("label", "id", "token") if c not in rows[0]]
    if missing:
        raise SystemExit(
            "WikiBio: %s is missing column(s) %s.\n  header seen: %s\n"
            "  This adapter refuses to guess, because a mis-read column yields a "
            "plausible wrong table." % (path, ", ".join(missing), list(rows[0])))
    return rows


class WikiBioAdapter:
    name = "wikibio"
    citation = ("Stranisci, Damiano, Mensa, Patti, Radicioni and Caselli, 'WikiBio: a "
                "Semantic Resource for the Intersectional Analysis of Biographical "
                "Events', ACL 2023, pp. 12370-12384; repo marcostranisci/WikiBio")
    license = ("UNRESOLVED for the data. The ACL paper is CC BY 4.0, which does not cover "
               "a separately released annotation set, and the repository states no licence "
               "and has no LICENSE file. Wikipedia-derived, so CC BY-SA 4.0 upstream. Not "
               "redistributed here: nothing is fetched by this adapter, which reads a local "
               "copy via --data-root, and experiments/corpora/wikibio/ carries the "
               "provenance note.")
    label_space = (SCORED_LABEL,)
    metric = ("trigger-anchored recall of target-person events over complete biographies; "
              "type is never compared, because the gold EVENT class is untyped")
    published_baseline: dict[str, float] = {}
    published_baseline_note = (
        "empty, and the reason is a split mismatch rather than an absent number. The paper "
        "reports DistilBERT event detection at about 0.859 F1, but over the 1,691 "
        "event-bearing TARGET SENTENCES, divided 564/563/564 -- a sentence-level split of a "
        "document-level corpus. Target-entity detection is separately reported at about "
        "0.808 F1 over a document split of 5 train / 5 dev / 10 test biographies. This "
        "pipeline receives a whole 17,000-character biography and is scored over every gold "
        "event in it, so neither figure is the bar it clears or misses.")

    #: Recorded for context only, deliberately outside published_baseline.
    reference_event_f1_sentence_split = 0.859
    reference_entity_f1_document_split = 0.808

    def __init__(self, max_chars: int = 180_000, min_events: int = 1):
        self.max_chars = max_chars
        self.min_events = min_events
        self.load_attrition: dict[str, int] = {"truncated_docs": 0, "unlocatable_spans": 0}

    # -------------------------------------------------------------- load

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        paths = []
        for dirpath, _d, filenames in os.walk(data_root):
            for fn in sorted(filenames):
                if fn.lower().endswith(".csv"):
                    paths.append(os.path.join(dirpath, fn))
        if not paths:
            raise SystemExit(
                "WikiBio: no .csv under %s. The release is one token CSV per biography; "
                "see experiments/corpora/wikibio/README.md." % data_root)

        made = 0
        for path in paths:
            rows = _read_tokens(path)
            if not rows:
                continue
            text, spans = detokenise([r["token"] for r in rows])
            dropped = max(0, len(text) - self.max_chars)
            if dropped:
                self.load_attrition["truncated_docs"] += 1
                text = text[:self.max_chars]

            # Multi-token spans share one annotation id, and the id is the only thing that
            # groups them: `Donald`, `James`, `Woods`, `CBE` are four rows of one ENTITY.
            by_ann: dict[str, dict] = {}
            order: list[str] = []
            for i, r in enumerate(rows):
                label, ann = (r.get("label") or "").strip(), (r.get("id") or "").strip()
                if not label or not ann:
                    continue
                start, end = spans[i]
                if ann not in by_ann:
                    by_ann[ann] = {"label": label, "start": start, "end": end,
                                   "sentence": r.get("sentence")}
                    order.append(ann)
                else:
                    by_ann[ann]["end"] = end

            triggers, contexts, subject_mentions = [], [], []
            for ann in order:
                a = by_ann[ann]
                if a["end"] > len(text):
                    # Only reachable when truncation cut a span in half.
                    self.load_attrition["unlocatable_spans"] += 1
                    continue
                rec = {"id": ann, "label": a["label"], "start": a["start"],
                       "end": a["end"], "surface": text[a["start"]:a["end"]]}
                if a["label"] == SCORED_LABEL:
                    triggers.append(rec)
                elif a["label"] in CONTEXT_LABELS:
                    contexts.append(rec)
                elif a["label"] == SUBJECT_LABEL:
                    subject_mentions.append(rec)

            if len(triggers) < self.min_events:
                continue
            # The _id column is a constant across all twenty files and names nothing. The
            # first ENTITY span is the subject: `Ada Aharoni`, `Lewis Nkosi`, and so on.
            name = subject_mentions[0]["surface"] if subject_mentions else \
                os.path.splitext(os.path.basename(path))[0]
            yield BenchmarkDoc(
                doc_id=os.path.splitext(os.path.basename(path))[0],
                slug=slugify(name), name=name, text=text,
                gold={"triggers": triggers, "context_events": contexts,
                      "subject_mentions": subject_mentions},
                transform=("detokenised", "whole_biography"),
                meta={"n_triggers": len(triggers), "n_context_events": len(contexts),
                      "n_subject_mentions": len(subject_mentions),
                      "chars": len(text), "chars_dropped": dropped,
                      "subject": name})
            made += 1
            if limit and made >= limit:
                return

    # -------------------------------------------------------------- project

    @staticmethod
    def _as_id(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            inner = value.get("id") or value.get("entity_id")
            return inner if isinstance(inner, str) else ""
        return ""

    @staticmethod
    def _spans_of(text: str, quote: str) -> list[tuple[int, int]]:
        """Where a verbatim quote sits in the document. Empty if it does not."""
        if not quote:
            return []
        out, start = [], text.find(quote)
        while start != -1:
            out.append((start, start + len(quote)))
            start = text.find(quote, start + 1)
        return out

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        items, unmapped, lossy = [], [], []
        for ev in extraction.events:
            if not isinstance(ev, dict):
                continue
            spans = []
            for src in (ev.get("sources") or []):
                if isinstance(src, dict):
                    spans.extend(self._spans_of(doc.text, src.get("quote") or ""))
            eid, etype = str(ev.get("id") or ""), str(ev.get("event_type"))
            if not spans:
                unmapped.append(("event", eid, etype,
                                 "no quote locatable in the document, so the event cannot "
                                 "be anchored to a trigger"))
                continue
            # Every type collapses onto the single gold class, so the type is recorded as
            # lost rather than compared: the gold has nothing to compare it against.
            lossy.append(("event", eid, etype,
                          "gold EVENT is untyped; all 22 types collapse onto it"))
            items.append({"id": eid, "type": etype, "spans": spans,
                          "label_tokens": _content_tokens(ev.get("label") or "")})
        return Prediction(doc_id=doc.doc_id, items=tuple(items),
                          unmapped=tuple(unmapped), lossy=tuple(lossy),
                          meta={"n_events": len(items)})

    # -------------------------------------------------------------- score

    @staticmethod
    def _inside(start: int, end: int, spans) -> bool:
        return any(s <= start and end <= e for s, e in spans)

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]],
              extractions: dict[str, Extraction] | None = None) -> ScoreReport:
        pairs = list(pairs)
        extractions = extractions or {}
        recalled = tier_strong = tier_weak = 0
        gold_total = 0
        matched_events = 0
        total_events = 0
        per_doc = {}

        for doc, pred in pairs:
            gold = (doc.gold or {}).get("triggers", [])
            events = list(pred.items)
            total_events += len(events)
            used: set[int] = set()
            hit = 0
            for trig in gold:
                gold_total += 1
                token = _fold(trig["surface"])
                best = None
                # Two tiers, as in bioevents and for the same reason: a quote is a whole
                # sentence and a trigger is one word in it, so span containment alone lets
                # any event in that sentence answer for any trigger in it. The strong tier
                # additionally requires the trigger to appear in the event's own label.
                for tier, want_label in (("label+quote", True), ("quote", False)):
                    for idx, e in enumerate(events):
                        if idx in used or not self._inside(trig["start"], trig["end"],
                                                           e["spans"]):
                            continue
                        has_label = bool(_content_tokens(token) & e["label_tokens"])
                        if want_label and not has_label:
                            continue
                        best = (idx, tier)
                        break
                    if best:
                        break
                if best:
                    used.add(best[0])
                    recalled += 1
                    hit += 1
                    matched_events += 1
                    if best[1] == "label+quote":
                        tier_strong += 1
                    else:
                        tier_weak += 1
            per_doc[doc.doc_id] = {"gold": len(gold), "recalled": hit,
                                   "events": len(events), "subject": doc.meta.get("subject")}

        recall = recalled / gold_total if gold_total else 0.0
        precision = matched_events / total_events if total_events else 0.0

        attrition = {"documents": len(pairs), "gold_triggers": gold_total,
                     "extracted_events": total_events,
                     "events_matching_no_trigger": total_events - matched_events,
                     "empty_extraction": 0, "out_of_scope": 0, "did_not_validate": 0}
        for ex in extractions.values():
            if not getattr(ex, "events", ()):
                attrition["empty_extraction"] += 1
            if (getattr(ex, "scope", None) or {}).get("fits") is False:
                attrition["out_of_scope"] += 1
            if getattr(ex, "exit_code", 0):
                attrition["did_not_validate"] += 1

        notes = [
            "Type is never compared. The gold EVENT class is untyped, so all 22 biograph "
            "event types collapse onto it and matching is trigger-anchored; every event is "
            "recorded in `lossy` for that reason.",
            "%d of %d matches rest on the weak anchor -- the trigger falls inside a quoted "
            "span with no support from the event's own label -- and the rest had both."
            % (tier_weak, recalled),
            "Precision here is NOT comparable to a sentence-level figure. The annotation "
            "covers events associated with the biography's TARGET PERSON; an event about "
            "anyone else in the document is correct extraction with no gold to match, and "
            "%d extracted events matched no trigger." % (total_events - matched_events),
            "The gold carries no dates, so nothing here tests the schema's requirement that "
            "every event have one. That is deliberate: BiographicalEvents lost 46%% of its "
            "corpus to that requirement, and removing the confound is why this benchmark "
            "is worth running beside it.",
            self.published_baseline_note,
        ]

        return ScoreReport(
            benchmark=self.name, metric=self.metric,
            scores={"trigger_recall": round(recall, 4),
                    "trigger_precision_vs_target_events": round(precision, 4),
                    "gold_recalled": recalled, "gold_triggers": gold_total,
                    "anchored_by_label_and_quote": tier_strong,
                    "anchored_by_quote_only": tier_weak},
            published_baseline=dict(self.published_baseline),
            not_applicable={
                "event_type": "The gold EVENT class is untyped -- the corpus annotates "
                              "that an event occurred, not which kind -- so no type can be "
                              "compared in either direction.",
                "dates": "The gold annotates no dates, so the schema's date requirement is "
                         "neither tested nor penalised here.",
                "EVENT-GR / EVENT-MOD": "Light verbs and modality annotate how an event is "
                                        "expressed rather than that one occurred. Read and "
                                        "counted, not scored.",
            },
            per_label={SCORED_LABEL: {"recall": round(recall, 4), "support": gold_total,
                                      "recalled": recalled}},
            attrition=attrition, n_docs=len(pairs), notes=notes)

    # -------------------------------------------------------------- coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        cells = {}
        for kind in ("birth", "death", "education", "employment_start", "employment_end",
                     "role_change", "invention", "patent_filed", "patent_granted",
                     "publication", "product_launch", "public_demonstration", "conference",
                     "visit", "meeting", "relocation", "award", "company_founded",
                     "company_sold", "company_renamed", "retirement", "other"):
            cells["event:%s" % kind] = (
                "partial",
                "scored as the single untyped gold EVENT class; the type itself has no "
                "counterpart and is recorded as lost")
        return cells


ADAPTER = WikiBioAdapter()
