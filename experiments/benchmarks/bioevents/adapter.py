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

TWO RELEASE FORMATS, AND THE REAL ONE IS NOT THE OBVIOUS ONE. This adapter was first
written against token-per-row CoNLL/IOB, which is what a TimeML trigger-labelling corpus
is normally shipped as. The actual release is not that. It is a single CSV, one SENTENCE
per row, with the annotated SPAN TEXT sitting in each class and role column:

    author,sent_id,text,ARGx-LOC,STATE,TIME,WRITER-ARG0,REP-EVENT,EVENT,ARGx-ORG,...
    Q1064470,11,"...he dropped out of...",,,,he,,drop,,...

So a cell holds `drop`, not `B-EVENT`. Both readers are kept: _read_span_csv for the
published shape, _read_conll/_read_json for the IOB shape, in case a later release or
another corpus arrives in it. The CoNLL path is now the fallback, not the assumption.

Span offsets are recovered by locating each cell's text inside its own sentence, which
works for 4,679 of 4,682 annotations (99.9%); the three that do not are dropped and
counted in `meta`, never silently matched to something nearby.

THE SUBJECT'S NAME IS APPENDED TO EVERY SENTENCE. Each `text` ends with the subject in
parentheses -- "...Dominican Liberation Party.  (Juan Temistocles Montas)" -- in 1,486 of
1,488 rows, and no author carries two different names. That is an annotation artifact, not
part of the sentence, so it is stripped before offsets are computed (repeating it after
every sentence would be a strange thing to hand an extractor) and used as the document's
name instead of the bare Wikidata QID. Disclosed in `transform` as "subject_suffix_stripped".

SCALE, AND WHAT IT MEANS FOR THE PAIRING. 1,488 sentences across 757 distinct subjects --
roughly two sentences per person. Grouping by author therefore gives 757 very short
pseudo-documents, not 757 biographies, and each one still costs a full extraction call.
--min-triggers is the lever: it drops documents carrying fewer than N annotated triggers,
trading coverage for budget.

Nothing is downloaded. load() reads a local copy via --data-root and sniffs the format
rather than assuming one; see experiments/corpora/bioevents/README.md for provenance.
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
    # "author" is this corpus's own name for the column, and it means the person the
    # biography is ABOUT -- the corpus is drawn from biographies of writers -- not whoever
    # wrote or annotated the sentence. Worth stating, because reading it the other way
    # would group every sentence under its annotator and produce one enormous document.
    "document": ("document", "doc", "doc_id", "file", "person", "subject", "title",
                 "author"),
    "sentence": ("sentence", "sent", "sentence_id", "sent_id"),
}

#: Span-CSV columns -> the label recorded in gold. The class columns keep their own names;
#: TIME is renamed to ARGM-TIME because that is what score() and ROLES call it, and the two
#: WRITER roles are recorded verbatim. They are outside ROLES, so score() ignores them --
#: kept anyway because dropping an annotation at read time makes it unrecoverable, while an
#: unscored one can be looked at.
SPAN_CSV_COLUMNS = {
    "EVENT": "EVENT", "STATE": "STATE", "ASP-EVENT": "ASP-EVENT", "REP-EVENT": "REP-EVENT",
    "ARGx-LOC": "ARGx-LOC", "ARGx-ORG": "ARGx-ORG", "TIME": "ARGM-TIME",
    "WRITER-ARG0": "WRITER-ARG0", "WRITER-ARGx": "WRITER-ARGx",
}

#: Each released sentence ends with its subject in parentheses. Bounded length and no
#: nesting, so a stray parenthetical clause at the end of a real sentence is unlikely to
#: match -- and if one does, it is removed from the text rather than mistaken for an
#: annotation, which costs nothing that is scored.
SUBJECT_SUFFIX = re.compile(r"\s*\(([^()]{2,80})\)\s*$")


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


def _read_span_csv(path: str):
    """The published shape: one sentence per row, annotated span TEXT in each column.

    Returns {doc_id: {"name": str, "sentences": [(order, text, [(label, surface), ...])]}}.
    Nothing is located here -- offsets depend on how sentences are laid out into one
    document, so finding the spans is _build_doc_from_spans()'s job.
    """
    import csv

    with io.open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {}
    header = list(rows[0].keys())
    cols = _resolve_columns(header, required=("token", "document"))
    present = {str(h).strip(): h for h in header}
    labelled = {present[c]: lab for c, lab in SPAN_CSV_COLUMNS.items() if c in present}
    if not labelled:
        raise SystemExit(
            "BiographicalEvents: %s has no annotation columns.\n"
            "  header seen: %s\n"
            "  expected some of: %s\n"
            "  This adapter refuses to guess, because a mis-read column yields a "
            "plausible wrong table." % (path, header, ", ".join(sorted(SPAN_CSV_COLUMNS))))

    order_col = cols.get("sentence")
    out: dict[str, dict] = defaultdict(lambda: {"name": None, "sentences": []})
    for i, r in enumerate(rows):
        doc_id = str(r.get(cols["document"]) or "").strip()
        text = str(r.get(cols["token"]) or "").strip()
        if not doc_id or not text:
            continue
        m = SUBJECT_SUFFIX.search(text)
        if m:
            text = text[:m.start()].rstrip()
            out[doc_id]["name"] = out[doc_id]["name"] or m.group(1).strip()
        anns = [(lab, str(r.get(col) or "").strip())
                for col, lab in labelled.items() if str(r.get(col) or "").strip()]
        try:
            order = int(str(r.get(order_col)).strip()) if order_col else i
        except (TypeError, ValueError):
            order = i
        out[doc_id]["sentences"].append((order, text, anns))
    return out


class BioEventsAdapter:
    name = "bioevents"
    citation = "arXiv:2206.03547 (ISA 2022); repo marcostranisci/biographicalEvents"
    license = ("Paper CC-BY-NC-4.0 (ELRA), per the proceedings footer on the PDF itself -- "
               "NOT the CC BY 4.0 the ACL Anthology's generic banner implies, and the NC "
               "matters. The corpus declares no licence of its own and is published openly "
               "in the authors' repository; it is Wikipedia-derived, so CC BY-SA upstream. "
               "Not redistributed here -- nothing is fetched by this adapter, which reads a "
               "local copy via --data-root, and experiments/corpora/bioevents/ carries the "
               "provenance note.")
    label_space = CLASSES + ROLES
    metric = ("trigger-anchored recall per TimeML class, with pooled precision over "
              "annotated spans; type is never compared")
    published_baseline: dict[str, float] = {}
    published_baseline_note = (
        "empty because THE PAPER REPORTS NO SYSTEM PERFORMANCE. This was previously "
        "described here as 'token-level sequence labelling by a model trained on this "
        "corpus'. That is wrong: it is a guidelines-and-resource paper, and its five "
        "tables are inter-annotator agreement, corpus counts, the most frequent "
        "events/states, a PropBank argument distribution and recurring link structures. "
        "It trains nothing and evaluates nothing. There is no published number to beat, "
        "and claiming to have beaten one would be inventing an opponent. "
        "The only quantitative anchor is the HUMAN AGREEMENT CEILING in Table 1 "
        "(see IAA below), which is what two trained annotators following these guidelines "
        "achieve against each other -- a ceiling, never a baseline.")

    #: Table 1, averaged over the six annotator pairings. Recorded for context only, and
    #: deliberately kept out of published_baseline so nothing can print it as a score this
    #: pipeline was measured against. STATE being the LOWEST agreement in the table (0.67,
    #: against 0.83 for EVENT) is worth noticing: the class this schema refuses to
    #: represent is also the class human annotators agree on least.
    inter_annotator_agreement = {
        "EVENT": 0.83, "STATE": 0.67, "writer-ARG0": 0.91, "writer-ARGx": 0.90,
        "ARGx-LOC": 0.75, "ARGx-ORG": 0.81, "ARGM-TIME": 0.91,
    }

    def __init__(self, min_triggers: int = 1, max_chars: int = 12000):
        self.min_triggers = min_triggers
        self.max_chars = max_chars

    # -------------------------------------------------------------- load

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        paths = []
        for dirpath, _d, filenames in os.walk(data_root):
            for fn in sorted(filenames):
                if fn.lower().endswith((".csv", ".conll", ".conllu", ".tsv", ".txt",
                                        ".json", ".jsonl", ".iob")):
                    paths.append(os.path.join(dirpath, fn))
        if not paths:
            raise SystemExit("BiographicalEvents: no annotation files under %s" % data_root)

        # The published release is the span CSV; CoNLL/IOB is the fallback. Both are read
        # into the same gold shape, so everything downstream is unaware of which arrived.
        span_docs: dict[str, dict] = {}
        by_doc: dict[str, list] = defaultdict(list)
        for path in paths:
            if path.lower().endswith(".csv"):
                for doc_id, rec in _read_span_csv(path).items():
                    if doc_id in span_docs:
                        span_docs[doc_id]["sentences"] += rec["sentences"]
                        span_docs[doc_id]["name"] = span_docs[doc_id]["name"] or rec["name"]
                    else:
                        span_docs[doc_id] = rec
            elif path.lower().endswith((".json", ".jsonl")):
                for doc_id, pairs in _read_json(path):
                    by_doc[str(doc_id)].append(pairs)
            else:
                doc_id = os.path.splitext(os.path.basename(path))[0]
                for sent in _read_conll(path):
                    by_doc[doc_id].append(sent)

        made = 0
        for doc_id, rec in sorted(span_docs.items()):
            doc = self._build_doc_from_spans(doc_id, rec)
            if doc is None:
                continue
            yield doc
            made += 1
            if limit and made >= limit:
                return
        for doc_id, sentences in sorted(by_doc.items()):
            doc = self._build_doc(doc_id, sentences)
            if doc is None:
                continue
            yield doc
            made += 1
            if limit and made >= limit:
                return

    def _build_doc_from_spans(self, doc_id: str, rec: dict) -> BenchmarkDoc | None:
        """Lay the released sentences out into one document and locate every annotation.

        Each cell holds the annotated text, so a span is found by searching its own
        sentence and shifting by where that sentence landed. Searching the whole document
        instead would let a word from sentence 1 answer for an annotation on sentence 9.
        An annotation whose text is not in its sentence is dropped and counted, never
        matched to the nearest thing that looks like it."""
        parts, triggers, roles, annotated = [], [], [], []
        cursor = 0
        unlocatable = 0
        for _order, text, anns in sorted(rec["sentences"], key=lambda s: s[0]):
            if not text:
                continue
            sent_start = cursor
            parts.append(text)
            cursor += len(text)
            annotated.append((sent_start, cursor))
            parts.append(" ")
            cursor += 1

            for label, surface in anns:
                at = text.find(surface)
                if at == -1:
                    unlocatable += 1
                    continue
                record = {"start": sent_start + at, "end": sent_start + at + len(surface),
                          "surface": surface, "label": label}
                (triggers if label in CLASSES else roles).append(record)

            if cursor > self.max_chars:
                break

        if len(triggers) < self.min_triggers:
            return None
        text = "".join(parts)[:self.max_chars]
        triggers = [t for t in triggers if t["end"] <= len(text)]
        roles = [r for r in roles if r["end"] <= len(text)]
        annotated = [(a, min(b, len(text))) for a, b in annotated if a < len(text)]
        name = rec.get("name") or str(doc_id)
        return BenchmarkDoc(
            doc_id=str(doc_id), slug=slugify(doc_id), name=name, text=text,
            gold={"triggers": triggers, "roles": roles, "annotated_spans": annotated},
            transform=("sentences_concatenated", "subject_suffix_stripped"),
            meta={"n_triggers": len(triggers), "n_roles": len(roles),
                  "unlocatable_annotations": unlocatable, "subject_name": name})

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

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]],
              extractions: dict[str, Extraction] | None = None) -> ScoreReport:
        pairs = list(pairs)
        extractions = extractions or {}
        # Why a document contributed nothing is not recoverable from its recall. Over the
        # first real run of this benchmark, 25 of 25 documents were refused by the gate
        # (recorded, not enforced, because --gate-off) and 11 of 25 produced no events at
        # all -- so most of the missing recall is documents the extractor returned empty,
        # not triggers it looked at and missed. Those are different findings and the
        # report has to be able to tell them apart.
        attrition = {"out_of_scope": 0, "empty_extraction": 0, "did_not_validate": 0}
        for ex in extractions.values():
            scope = getattr(ex, "scope", None) or {}
            if scope.get("fits") is False:
                attrition["out_of_scope"] += 1
            if not getattr(ex, "events", ()):
                attrition["empty_extraction"] += 1
            if getattr(ex, "exit_code", 0):
                attrition["did_not_validate"] += 1
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
            "only bucketed by class afterwards to report recall per class.",]
        if extractions:
            notes.append(
                "Read recall with attrition beside it: %d of %d documents produced no "
                "events at all, so that share of the missing recall is documents the "
                "extractor returned empty rather than triggers it examined and missed. "
                "%d were refused by the scope gate (recorded, not enforced). The released "
                "documents are short -- this corpus is ~2 sentences per subject -- and a "
                "document-level extractor on a sentence fragment is a different setting "
                "from the one the published baseline measures."
                % (attrition["empty_extraction"], len(pairs), attrition["out_of_scope"]))
        notes += [
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
            attrition=dict(attrition, documents=len(pairs),
                           unscorable_span=unscorable_span,
                           scorable_events=scorable_events),
            n_docs=len(pairs), notes=notes)

    # -------------------------------------------------------------- coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        from ...harness.coverage import BIOEVENTS
        return dict(BIOEVENTS["cells"])


ADAPTER = BioEventsAdapter()
