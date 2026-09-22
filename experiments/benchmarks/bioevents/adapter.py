"""Benchmark 2: Guidelines and a Corpus for Extracting Biographical Events
(ISA 2022, arXiv:2206.03547; repo marcostranisci/biographicalEvents).

Label space: ISO-TimeML event classes -- EVENT, STATE, ASP-EVENT, REP-EVENT -- over
annotated *trigger tokens*, plus writer-centric SemAF roles (writer-ARG0, writer-ARGx,
ARGx-LOC, ARGx-ORG, ARGM-TIME).

This is the most structurally mismatched of the five, and the mismatches are the finding
rather than an obstacle to it.

TYPE IS NOT MEASURABLE, IN EITHER DIRECTION. All 22 biograph event types collapse onto
TimeML's single EVENT class, and TimeML's four classes have no counterpart in biograph's
vocabulary. So this adapter never compares a type to a type. Scoring is *trigger-anchored*:
a gold trigger token is recalled if some extracted event is anchored at it. Gold triggers
are then bucketed by their TimeML class to report recall per class, but the match itself is
type-agnostic. Inventing a correspondence to get a type-accuracy number would be the one
genuinely dishonest thing available here.

ANCHORING, AND WHY IT NEEDS TWO TIERS. biograph produces no token offsets. What it does
produce, for every event, is a verbatim `sources[].quote` (grounding-checked at 99.5%
across the corpus) and a short `label`. Locating the quote in the document gives a
character span. But a span alone is not enough: Turing's "Born" and "Died" events cite the
*same* quote -- "Alan Turing OBE FRS (23 June 1912 - 7 June 1954)" -- so span containment
alone would let either event answer for either trigger. So:

    label+quote   the trigger token appears in the event's label AND falls inside one of
                  its quote spans. The strong anchor.
    quote         the trigger falls inside a quote span, with no label support. Weak, and
                  counted separately so the reader can see how much of recall rests on it.

Matching is one-to-one: a gold trigger is answered by at most one event, and an event
answers at most one trigger. Without that, one sentence-length quote would claim every
trigger in its sentence.

STATE IS AN UNREACHABLE CEILING, BY DESIGN. "An event is a dateable occurrence, not a fact
or a description" (schema/README.md). A TimeML STATE is precisely a fact or a description,
so biograph drops them deliberately. STATE recall is therefore reported as a *measured*
number -- it should be near zero -- and excluded from the macro average, because averaging
in a class the schema refuses to represent would measure an ontological choice as though it
were an error rate.

PRECISION IS SCOPED TO ANNOTATED TEXT. The corpus annotates some sentences; biograph
extracts from the whole document. An extracted event anchored outside any annotated
sentence has no gold that could confirm or deny it, so counting it as a false positive
would punish the extractor for reading text the annotators did not label. Those are
reported separately as `unscorable_span` and excluded from precision.

Nothing is downloaded. The licence is not stated in the paper, so load() reads a local copy
via --data-root and sniffs the format rather than assuming one.
"""
from __future__ import annotations

import io
import json
import os
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from ...harness.interface import BenchmarkDoc, Extraction, Prediction, ScoreReport

#: TimeML event classes as this corpus uses them.
CLASSES = ("EVENT", "STATE", "ASP-EVENT", "REP-EVENT")

#: Excluded from the macro average. See the module docstring: the schema refuses to
#: represent a static condition, so this is an ontological decision, not an error rate.
UNREACHABLE = ("STATE",)

#: SemAF roles this adapter can fill from relations.json and events.json.
ROLES = ("ARGx-LOC", "ARGx-ORG", "ARGM-TIME")

#: relation type -> the role its target fills. Straight from harness/coverage.py's
#: BIOEVENTS cells, so the two cannot drift apart.
RELATION_ROLE = {
    "born_in": "ARGx-LOC", "died_in": "ARGx-LOC", "lived_in": "ARGx-LOC",
    "visited": "ARGx-LOC", "relocated_to": "ARGx-LOC",
    "worked_at": "ARGx-ORG", "employed_by": "ARGx-ORG", "member_of": "ARGx-ORG",
    "founded": "ARGx-ORG", "studied_at": "ARGx-ORG",
}

#: Words that carry no anchoring signal in an event label.
STOP = {"the", "a", "an", "of", "in", "at", "to", "and", "for", "on", "with", "his",
        "her", "their", "by", "from", "as", "is", "was", "were", "be", "been"}

COLUMN_ALIASES = {
    "token": ("token", "word", "form", "text", "surface"),
    "label": ("label", "tag", "class", "event", "annotation", "bio"),
    "document": ("document", "doc", "doc_id", "file", "person", "subject", "title"),
    "sentence": ("sentence", "sent", "sentence_id", "sent_id"),
}


def _fold(s: Any) -> str:
    flat = "".join(c for c in unicodedata.normalize("NFKD", str(s))
                   if not unicodedata.combining(c))
    return " ".join(flat.casefold().split())


def _content_tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _fold(s)) if t and t not in STOP}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if not s or not s[0].isalpha():
        s = "b2_" + s
    return s[:60]


def parse_tag(tag: str) -> tuple[str | None, str | None]:
    """An IOB tag -> (bare label, prefix). 'B-EVENT' -> ('EVENT', 'B')."""
    tag = (tag or "").strip()
    if not tag or tag == "O":
        return None, None
    m = re.match(r"^([BILUES])-(.+)$", tag)
    if m:
        return m.group(2).strip(), m.group(1)
    return tag, None


# ------------------------------------------------------------------ input side


def _resolve_columns(header, required=("token", "label")):
    present = {str(h).strip().lower(): h for h in header}
    resolved = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in present:
                resolved[field] = present[a]
                break
    missing = [f for f in required if f not in resolved]
    if missing:
        raise SystemExit(
            "BiographicalEvents: could not find column(s) %s in this file.\n"
            "  header seen: %s\n"
            "  Add the real name to COLUMN_ALIASES in %s -- this adapter refuses to guess, "
            "because a mis-read column yields a plausible wrong table."
            % (", ".join(missing), list(present.values()), __file__))
    return resolved


def _read_conll(path: str):
    """Blank-line-separated sentences of whitespace/tab-separated columns.

    The token column is assumed first and the tag column last, which is the CoNLL
    convention; anything between is passed over. A header line naming columns is used if
    one is present."""
    sentences, current = [], []
    header = None
    with io.open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.startswith(("# ", "-DOCSTART-")):
                if current:
                    sentences.append(current)
                    current = []
                continue
            parts = re.split(r"\t| {2,}| ", line.strip())
            parts = [p for p in parts if p != ""]
            if header is None and len(parts) >= 2 and _fold(parts[0]) in COLUMN_ALIASES["token"]:
                header = parts
                continue
            if len(parts) >= 2:
                current.append((parts[0], parts[-1]))
    if current:
        sentences.append(current)
    return sentences


def _read_json(path: str):
    """Records carrying tokens[] and labels[] (or a `tokens` list of {token,label})."""
    with io.open(path, encoding="utf-8") as f:
        if path.lower().endswith(".jsonl"):
            records = [json.loads(ln) for ln in f if ln.strip()]
        else:
            loaded = json.load(f)
            records = loaded if isinstance(loaded, list) else [loaded]
    out = []
    for r in records:
        toks, labs = r.get("tokens"), r.get("labels") or r.get("tags")
        if isinstance(toks, list) and toks and isinstance(toks[0], dict):
            cols = _resolve_columns(toks[0].keys())
            pairs = [(str(t.get(cols["token"], "")), str(t.get(cols["label"], "O")))
                     for t in toks]
        elif isinstance(toks, list) and isinstance(labs, list):
            pairs = [(str(a), str(b)) for a, b in zip(toks, labs)]
        else:
            continue
        out.append((r.get("document") or r.get("doc_id") or r.get("person")
                    or os.path.basename(path), pairs))
    return out


class BioEventsAdapter:
    name = "bioevents"
    citation = "arXiv:2206.03547 (ISA 2022); repo marcostranisci/biographicalEvents"
    license = ("UNRESOLVED -- not stated in the paper and not declared in the repository. "
               "Resolve before downloading; nothing is fetched here, which reads a local "
               "copy via --data-root.")
    label_space = CLASSES + ROLES
    metric = ("trigger-anchored recall per TimeML class, with pooled precision over "
              "annotated spans; type is never compared")
    published_baseline: dict[str, float] = {}
    published_baseline_note = (
        "deliberately empty. The paper's figures are token-level sequence labelling by a "
        "model trained on this corpus; this adapter anchors a zero-shot document-level "
        "extractor's events to the same triggers. The two are not the same task and must "
        "not be printed side by side as though one cleared the other.")

    def __init__(self, min_triggers: int = 1, max_chars: int = 12000):
        self.min_triggers = min_triggers
        self.max_chars = max_chars

    # -------------------------------------------------------------- load

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        paths = []
        for dirpath, _d, filenames in os.walk(data_root):
            for fn in sorted(filenames):
                if fn.lower().endswith((".conll", ".conllu", ".tsv", ".txt",
                                        ".json", ".jsonl", ".iob")):
                    paths.append(os.path.join(dirpath, fn))
        if not paths:
            raise SystemExit("BiographicalEvents: no annotation files under %s" % data_root)

        by_doc: dict[str, list] = defaultdict(list)
        for path in paths:
            if path.lower().endswith((".json", ".jsonl")):
                for doc_id, pairs in _read_json(path):
                    by_doc[str(doc_id)].append(pairs)
            else:
                doc_id = os.path.splitext(os.path.basename(path))[0]
                for sent in _read_conll(path):
                    by_doc[doc_id].append(sent)

        made = 0
        for doc_id, sentences in sorted(by_doc.items()):
            doc = self._build_doc(doc_id, sentences)
            if doc is None:
                continue
            yield doc
            made += 1
            if limit and made >= limit:
                return

    def _build_doc(self, doc_id: str, sentences: list) -> BenchmarkDoc | None:
        """Lay the sentences out into one text and record where every annotation landed.

        Offsets must be into the text this harness actually sends, not into the original
        file, so they are computed here while the text is being assembled. Anything scored
        later compares positions in the same string the model read."""
        parts, triggers, roles, annotated = [], [], [], []
        cursor = 0
        for sent in sentences:
            if not sent:
                continue
            sent_start = cursor
            spans = []
            for token, tag in sent:
                start = cursor
                parts.append(token)
                cursor += len(token)
                spans.append((start, cursor, token, tag))
                parts.append(" ")
                cursor += 1
            sent_end = cursor - 1
            annotated.append((sent_start, sent_end))

            # Merge IOB runs into one annotation per span.
            i = 0
            while i < len(spans):
                start, end, token, tag = spans[i]
                label, prefix = parse_tag(tag)
                if not label:
                    i += 1
                    continue
                j = i + 1
                while j < len(spans):
                    nlabel, nprefix = parse_tag(spans[j][3])
                    if nlabel != label or nprefix == "B":
                        break
                    end = spans[j][1]
                    j += 1
                surface = " ".join(s[2] for s in spans[i:j])
                record = {"start": start, "end": end, "surface": surface, "label": label}
                (triggers if label in CLASSES else roles).append(record)
                i = j

            if cursor > self.max_chars:
                break

        if len([t for t in triggers]) < self.min_triggers:
            return None
        text = "".join(parts)[:self.max_chars]
        triggers = [t for t in triggers if t["end"] <= len(text)]
        roles = [r for r in roles if r["end"] <= len(text)]
        annotated = [(a, min(b, len(text))) for a, b in annotated if a < len(text)]
        return BenchmarkDoc(
            doc_id=str(doc_id), slug=slugify(doc_id), name=str(doc_id).replace("_", " "),
            text=text,
            gold={"triggers": triggers, "roles": roles, "annotated_spans": annotated},
            transform=("sentences_concatenated",),
            meta={"n_triggers": len(triggers), "n_roles": len(roles)})

    # -------------------------------------------------------------- project

    @staticmethod
    def _spans_of(text: str, quote: str) -> list[tuple[int, int]]:
        """Where this verbatim quote sits in the document text. Empty if it does not."""
        if not quote:
            return []
        out, start = [], text.find(quote)
        while start != -1:
            out.append((start, start + len(quote)))
            start = text.find(quote, start + 1)
        return out

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        names = {e["id"]: e.get("name", "") for e in extraction.entities
                 if isinstance(e, dict) and e.get("id")}
        items, unmapped, lossy = [], [], []

        for ev in extraction.events:
            spans = []
            for src in ev.get("sources", []) or []:
                spans.extend(self._spans_of(doc.text, src.get("quote") or ""))
            items.append(("trigger", {
                "event_id": ev.get("id"),
                "biograph_type": ev.get("event_type"),
                "label_tokens": _content_tokens(ev.get("label") or ""),
                "spans": spans,
            }))
            # Every biograph type collapses onto one TimeML class, so the type itself is
            # information this label space cannot carry. Recorded once per event.
            lossy.append(("event", str(ev.get("id", "")), "EVENT",
                          "biograph type %r collapses onto TimeML EVENT; the corpus has "
                          "no slot for it" % ev.get("event_type")))
            date = ev.get("date") or {}
            if date.get("display"):
                for s, e in self._spans_of(doc.text, date["display"]):
                    items.append(("ARGM-TIME", {"start": s, "end": e,
                                                "surface": date["display"]}))
            loc = names.get(ev.get("location") or "")
            if loc:
                for s, e in self._spans_of(doc.text, loc):
                    items.append(("ARGx-LOC", {"start": s, "end": e, "surface": loc}))

        for rel in extraction.relations:
            role = RELATION_ROLE.get(rel.get("type"))
            target = names.get(rel.get("target") or "")
            if not role:
                unmapped.append(("relation", str(rel.get("id", "")), str(rel.get("type")),
                                 "the SemAF role inventory is writer-centric; a relation "
                                 "between two third parties has no role to fill"))
                continue
            if not target:
                unmapped.append(("relation", str(rel.get("id", "")), str(rel.get("type")),
                                 "target id has no entity in entities[]"))
                continue
            for s, e in self._spans_of(doc.text, target):
                items.append((role, {"start": s, "end": e, "surface": target}))

        return Prediction(doc_id=doc.doc_id, items=tuple(items),
                          unmapped=tuple(unmapped), lossy=tuple(lossy),
                          meta={"n_events": len(extraction.events)})

    # -------------------------------------------------------------- score

    @staticmethod
    def _inside(point_start: int, point_end: int, spans) -> bool:
        return any(s <= point_start and point_end <= e for s, e in spans)

    @staticmethod
    def _overlaps(a_start: int, a_end: int, spans) -> bool:
        return any(a_start < e and s < a_end for s, e in spans)

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]]) -> ScoreReport:
        pairs = list(pairs)
        recalled = defaultdict(int)
        gold_total = defaultdict(int)
        tier_counts = defaultdict(int)
        matched_events = 0
        scorable_events = 0
        unscorable_span = 0
        role_tp = defaultdict(int)
        role_fn = defaultdict(int)
        role_fp = defaultdict(int)

        for doc, pred in pairs:
            gold = doc.gold or {}
            triggers = gold.get("triggers", [])
            annotated = gold.get("annotated_spans", [])
            events = [v for k, v in pred.items if k == "trigger"]

            for e in events:
                if e["spans"] and self._overlaps(min(s for s, _ in e["spans"]),
                                                 max(x for _, x in e["spans"]), annotated):
                    scorable_events += 1
                else:
                    # No annotated sentence covers this event, so no gold could confirm or
                    # deny it. Counting it against precision would penalise the extractor
                    # for reading text the annotators did not label.
                    unscorable_span += 1

            used_events: set[int] = set()
            for trig in triggers:
                gold_total[trig["label"]] += 1
                token = _fold(trig["surface"])
                best = None
                for tier, want_label in (("label+quote", True), ("quote", False)):
                    for idx, e in enumerate(events):
                        if idx in used_events:
                            continue
                        if not self._inside(trig["start"], trig["end"], e["spans"]):
                            continue
                        has_label = bool(_content_tokens(token) & e["label_tokens"])
                        if want_label and not has_label:
                            continue
                        best = (idx, tier)
                        break
                    if best:
                        break
                if best:
                    used_events.add(best[0])
                    recalled[trig["label"]] += 1
                    tier_counts[best[1]] += 1
                    matched_events += 1

            # roles: a hit is an overlapping predicted span carrying the same role label
            gold_roles = defaultdict(list)
            for r in gold.get("roles", []):
                if r["label"] in ROLES:
                    gold_roles[r["label"]].append(r)
            for role in ROLES:
                predicted = [v for k, v in pred.items if k == role]
                used_pred: set[int] = set()
                for g in gold_roles.get(role, []):
                    hit = None
                    for i, p in enumerate(predicted):
                        if i in used_pred:
                            continue
                        if self._overlaps(g["start"], g["end"], [(p["start"], p["end"])]):
                            hit = i
                            break
                    if hit is None:
                        role_fn[role] += 1
                    else:
                        used_pred.add(hit)
                        role_tp[role] += 1
                for i, p in enumerate(predicted):
                    if i not in used_pred and self._overlaps(p["start"], p["end"], annotated):
                        role_fp[role] += 1

        per_label = {}
        for cls in CLASSES:
            total = gold_total[cls]
            r = recalled[cls] / total if total else 0.0
            per_label[cls] = {"recall": round(r, 4), "support": total,
                              "recalled": recalled[cls]}
        for role in ROLES:
            tp, fp, fn = role_tp[role], role_fp[role], role_fn[role]
            p = tp / (tp + fp) if (tp + fp) else 0.0
            r = tp / (tp + fn) if (tp + fn) else 0.0
            per_label[role] = {"precision": round(p, 4), "recall": round(r, 4),
                               "f1": round(2 * p * r / (p + r), 4) if (p + r) else 0.0,
                               "support": tp + fn}

        scored_classes = [c for c in CLASSES if c not in UNREACHABLE and gold_total[c]]
        precision = matched_events / scorable_events if scorable_events else 0.0
        total_gold = sum(gold_total[c] for c in scored_classes)
        total_hit = sum(recalled[c] for c in scored_classes)
        recall = total_hit / total_gold if total_gold else 0.0
        scores = {
            "trigger_precision": round(precision, 4),
            "trigger_recall": round(recall, 4),
            "trigger_f1": round(2 * precision * recall / (precision + recall), 4)
                          if (precision + recall) else 0.0,
            "macro_recall": round(sum(per_label[c]["recall"] for c in scored_classes)
                                  / len(scored_classes), 4) if scored_classes else 0.0,
            "anchored_by_label_and_quote": tier_counts["label+quote"],
            "anchored_by_quote_only": tier_counts["quote"],
        }

        notes = [
            "Type is never compared: all 22 biograph event types collapse onto TimeML's "
            "single EVENT class, so matching is trigger-anchored and gold triggers are "
            "only bucketed by class afterwards to report recall per class.",
            "%d of %d matches rest on the weak anchor (quote span with no label support); "
            "the rest had both." % (tier_counts["quote"], matched_events),
            "%d extracted events fell outside every annotated sentence and are excluded "
            "from precision (`unscorable_span`)." % unscorable_span,
            "published_baseline is " + self.published_baseline_note,
        ]
        if gold_total["STATE"]:
            notes.append(
                "STATE recall is %.3f over %d gold triggers, and is excluded from "
                "macro_recall. This is the schema's ontological choice measured, not an "
                "error rate: 'an event is a dateable occurrence, not a fact or a "
                "description'." % (per_label["STATE"]["recall"], gold_total["STATE"]))

        return ScoreReport(
            benchmark=self.name, metric=self.metric, scores=scores,
            published_baseline=dict(self.published_baseline),
            not_applicable={
                "STATE": "A TimeML STATE is a static condition, which biograph drops by "
                         "design (schema/README.md). Its recall is reported above as a "
                         "measured ceiling but excluded from macro_recall.",
                "writer-ARG0": "Writer-centric roles model the biography's author, a "
                               "perspective the schema does not represent at all.",
                "writer-ARGx": "As writer-ARG0.",
            },
            per_label=per_label,
            attrition={"documents": len(pairs), "unscorable_span": unscorable_span,
                       "scorable_events": scorable_events},
            n_docs=len(pairs), notes=notes)

    # -------------------------------------------------------------- coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        from ...harness.coverage import BIOEVENTS
        return dict(BIOEVENTS["cells"])


ADAPTER = BioEventsAdapter()
