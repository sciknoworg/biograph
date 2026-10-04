"""Benchmark 1: Biographical (Plum et al., SIGIR 2022) -- sentence-level relation extraction.

Label space: birthdate, birthplace, deathdate, deathplace, occupation, ofParent,
educatedAt, hasChild, sibling, other.

This is the benchmark that carries the generalization claim. PMOA-TTS asks whether the
pipeline survives a different *genre*; this one asks whether it survives a different
*population* -- Wikipedia biographies of writers, politicians, athletes and artists,
rather than scientists and engineers. Same mechanism, same prompt, same schema.

Four things about the pairing are awkward, and all four are handled in the open here
rather than smoothed over.

1. THE SCOPE GATE REFUSES THIS POPULATION. Measured, not assumed: eight Wikipedia
   biographies of named people, identical in source, format and length and varying only
   the subject's field, split 0/5 for literature, art, sport, music and politics against
   2/2 for aviation and nursing/statistics, with computing as a passing control
   (experiments/docs/scope-gate-boundary.md). Every refusal cited the technology clause.
   A refused document produces no graph, so run gate-on and every number here is 0.00 for
   reasons that have nothing to do with extraction.

   So this adapter is meant to be run in BOTH conditions and reported as two rows:
   gate-on measures the admission policy, gate-off (Runner(ignore_scope=True)) measures
   the extractor. They are never averaged together.

2. SENTENCE-LEVEL GOLD AGAINST A DOCUMENT-LEVEL EXTRACTOR. Biographical annotates single
   sentences. biograph reads a document about one person and builds a graph; a lone
   sentence has no biographical arc, and one extraction per sentence would also cost a
   model call per row. So the input adapter GROUPS BY PERSON: every sentence about one
   subject becomes one pseudo-document, extracted once, and that person's whole gold set
   is scored against the result. This is disclosed in BenchmarkDoc.transform as
   "grouped_by_person" and is the single most consequential choice in this file -- it
   makes the task easier than the published one in one way (more context per decision)
   and harder in another (the model must attribute each fact to the right person among
   everyone the sentences mention).

3. THE TWO DATED LABELS ARE NOT RELATIONS IN BIOGRAPH AT ALL. birthdate and deathdate
   live in events.json as event_type birth/death carrying a FuzzyDate, so they are read
   from there. birthplace/deathplace have two possible sources -- the born_in/died_in
   relation, and the birth/death event's own `location` field -- and this adapter takes
   their UNION, because a gold sentence states the fact once and either route finding it
   is a hit.

4. occupation HAS NO TYPED HOME. entity.subtype is free text ('researcher' for 71% of
   corpus person entities) and entity.summary is prose. Neither is a controlled slot, so
   occupation is reported not_applicable and excluded from every macro-average. Scoring
   it 0 would understate the pipeline for a label it was never asked to produce.

No published baseline is recorded here. The paper's numbers are measured on the released
splits under a setting this adapter does not reproduce (sentence-level, grouped here),
and quoting them as a bar cleared would repeat exactly the mistake PMOA-TTS's release
invites -- see experiments/benchmarks/pmoa_tts/README.md. Fill published_baseline in only
after the licence is resolved, the release is in hand, and the setting is confirmed to
match.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from ...harness import vocab
from ...harness.interface import BenchmarkDoc, Extraction, Prediction, ScoreReport

LABELS = ("birthdate", "birthplace", "deathdate", "deathplace", "occupation",
          "ofParent", "educatedAt", "hasChild", "sibling", "other")

#: Scored labels: everything the schema can express. `other` is the benchmark's catch-all
#: and is not a target to predict; `occupation` has no typed home (see module docstring).
SCORED = ("birthdate", "birthplace", "deathdate", "deathplace",
          "educatedAt", "ofParent", "hasChild", "sibling")

FAMILY = ("ofParent", "hasChild", "sibling")

#: Column names seen for the same field across distributions of this dataset. load() sniffs
#: the header rather than assuming one, because the release is not in hand (licence
#: unresolved) and a silently mis-read column would produce a plausible, wrong table.
COLUMN_ALIASES = {
    "sentence": ("sentence", "text", "sent", "sentence_text"),
    "relation": ("relation", "label", "property", "rel", "relation_type"),
    # The human verdict, where the release carries one beside the automatic label.
    "annotation": ("annotation", "gold", "human", "adjudicated"),
    # The grouping key. A page id identifies one person; a subject string does not.
    "page": ("wp_id", "page_id", "page", "doc_id", "article_id"),
    # Present only in a release that ships the arguments as columns rather than as
    # <e1>/<e2> markers inside the sentence. The published one does not.
    "subject": ("subject", "person", "subj", "entity", "head", "person_name"),
    "object": ("object", "obj", "value", "tail", "target"),
}

#: Without these nothing can be read at all. `annotation` and `page` are not required --
#: an older release may carry neither -- but their absence changes what is being scored,
#: so load() says so rather than quietly falling back.
REQUIRED_COLUMNS = ("sentence", "relation")


def _fold(s: Any) -> str:
    """Casefold, strip accents, collapse whitespace and drop trailing punctuation."""
    flat = "".join(c for c in unicodedata.normalize("NFKD", str(s))
                   if not unicodedata.combining(c))
    return " ".join(flat.casefold().replace(".", " ").split())


def slugify(name: str) -> str:
    """A slug build_site.py will accept: ^[a-z][a-z0-9_]*$."""
    s = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if not s or not s[0].isalpha():
        s = "b1_" + s
    return s[:60]


#: The released label names, mapped onto this adapter's label space. Stated rather than
#: guessed: a silent mismatch would score every place and kinship fact as a miss while the
#: run looked healthy, since an unmapped gold label simply never matches a prediction.
RELEASE_LABELS = {
    # The published English release's own names.
    "bplace_name": "birthplace", "dplace_name": "deathplace",
    "parent": "ofParent", "child": "hasChild", "Other": "other",
    # Identity entries, so a release already using this adapter's label space passes
    # through rather than being dropped as unmapped. Without them a file whose column
    # already said "birthplace" lost every place and kinship fact silently, because an
    # unmapped gold label is simply never matched and the run still looks healthy.
    **{lab: lab for lab in LABELS},
}

#: The two argument markers the release embeds in each sentence.
MARKER = re.compile(r"<(e[12])>(.*?)</\1>", re.S)


def _as_id(value) -> str:
    """A model-emitted entity reference, as a string that is safe to use as a dict key.

    The schema says events[].location and relations[].source/target are entity IDS --
    strings. A model does not always agree: one document in the first real run emitted
    location as a {"name": ..., "id": ...} object, and `names.get(ev.get("location"))`
    raised TypeError: unhashable type: 'dict'. That killed the run outright, 82 documents
    in, after every one of those extractions had already been paid for.

    An adapter reads untrusted model output and must not crash on it. A reference that is
    not a string is returned as "", which resolves to no entity -- the item is then simply
    unmapped, which is the correct outcome for a reference that does not name anything.
    An id nested inside such an object is taken when it is there, since that loses nothing.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        inner = value.get("id") or value.get("entity_id")
        return inner if isinstance(inner, str) else ""
    return ""


def _strip_markers(sentence: str) -> str:
    """The sentence as prose, with the annotation markup removed.

    What reaches the model has to be a sentence, not XML: the markers are an artifact of
    how the corpus encodes which two spans a relation holds between, and feeding them in
    would both distort the text and leak which pair the benchmark is asking about.
    """
    return MARKER.sub(lambda m: m.group(2), sentence).strip()


def _arguments(row: dict) -> tuple[str, str] | None:
    """(subject, object) for one row, from markers if present, else from columns.

    The published release does not put the entities in columns -- they are <e1>/<e2> spans
    inside the sentence -- and which one is the SUBJECT is given by P1. It is 'e1' in 2,473
    of 2,900 rows and 'e2' in 427, so assuming e1 is always the subject would invert one
    row in seven: a Wikipedia sentence can introduce the date before the person. Every such
    row would then be scored as a wrong answer the extractor never gave.

    The column form is kept as a fallback, for a release that ships subject and object as
    their own fields. Markers win where both are present, since they carry the pairing.
    """
    spans = {m.group(1): m.group(2).strip() for m in MARKER.finditer(row.get("sentence") or "")}
    first, second = (row.get("P1") or "").strip(), (row.get("P2") or "").strip()
    if first in spans and second in spans:
        return spans[first], spans[second]
    if len(spans) == 2 and not (first or second):
        # Markers but no P1/P2 column: the e1/e2 order is all there is to go on.
        return spans.get("e1", ""), spans.get("e2", "")
    subject = (row.get("subject") or "").strip()
    obj = (row.get("object") or "").strip()
    if subject:
        return subject, obj
    return None


# ------------------------------------------------------------------ input side


def _resolve_columns(header: Iterable[str]) -> dict[str, str]:
    """Map our four field names onto this file's actual column names, or explain."""
    present = {h.strip().lower(): h for h in header}
    resolved = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in present:
                resolved[field] = present[a]
                break
    missing = [f for f in REQUIRED_COLUMNS if f not in resolved]
    if missing:
        raise SystemExit(
            "Biographical: could not find column(s) %s in this file.\n"
            "  header seen: %s\n"
            "  Add the real name to COLUMN_ALIASES in %s -- this adapter deliberately "
            "refuses to guess, because a mis-read column yields a plausible wrong table."
            % (", ".join(missing), list(present.values()), __file__))
    return resolved


def _rows(data_root: str):
    """Every annotation row, from whichever files the release ships."""
    paths = []
    for dirpath, _dirnames, filenames in os.walk(data_root):
        for fn in sorted(filenames):
            if fn.lower().endswith((".csv", ".tsv", ".json", ".jsonl")):
                paths.append(os.path.join(dirpath, fn))
    if not paths:
        raise SystemExit("Biographical: no .csv/.tsv/.json/.jsonl under %s" % data_root)

    for path in paths:
        low = path.lower()
        if low.endswith((".json", ".jsonl")):
            with io.open(path, encoding="utf-8") as f:
                if low.endswith(".jsonl"):
                    records = [json.loads(ln) for ln in f if ln.strip()]
                else:
                    loaded = json.load(f)
                    records = loaded if isinstance(loaded, list) else [loaded]
            if not records:
                continue
            cols = _resolve_columns(records[0].keys())
            for r in records:
                # The row entire, plus the normalised names. P1/P2 say which marker is the
                # subject and are not fields this adapter renames, so a projection down to
                # four known keys would drop them and silently invert one row in seven.
                out = dict(r)
                out.update({k: r.get(v) for k, v in cols.items()})
                yield out
        else:
            with io.open(path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f, delimiter="\t" if low.endswith(".tsv") else ",")
                if not reader.fieldnames:
                    continue
                cols = _resolve_columns(reader.fieldnames)
                for r in reader:
                    out = dict(r)
                    out.update({k: r.get(v) for k, v in cols.items()})
                    yield out


class BiographicalAdapter:
    name = "biographical"
    citation = "Plum et al., SIGIR 2022 -- 'Biographical: A Semi-Supervised Relation " \
               "Extraction Dataset'"
    license = ("CC BY-SA 4.0, as stated by the first author in correspondence (2026-10). "
               "Note that the HuggingFace card's licensing section is still an unfilled "
               "template, so the statement is the author's, not the repository's -- worth "
               "citing as such, and worth asking them to fill in. Wikipedia-derived, which "
               "is CC BY-SA 4.0 upstream too, so share-alike applies to derived artifacts. "
               "Not redistributed here; the adapter reads a local copy via --data-root and "
               "experiments/corpora/biographical/ carries the provenance note.")
    label_space = LABELS
    metric = "micro and macro P/R/F1 over the scored labels; dates by interval containment"
    published_baseline: dict[str, float] = {}
    published_baseline_note = (
        "empty, but NOT because the paper reports nothing and NOT because it evaluates on "
        "different data. It evaluates a BERT classifier on exactly this gold file, so the "
        "evaluation SET is shared. What differs is the TASK. Their model is handed a "
        "marked entity pair and chooses one of ten labels for it, including `other`: a "
        "10-way classification over a pair someone else found. This pipeline is handed raw "
        "text with no pair and must find the entities, decide which are related, and type "
        "the relation. Recall there is over pairs presented; recall here is over facts "
        "nobody pointed at. Printing the two side by side would read as a comparison "
        "between a weaker and a stronger system rather than between two different jobs.")

    #: Table 5 of the paper: BERT-base trained on each distant-supervision set and
    #: evaluated on this same gold file. Recorded for context, kept out of
    #: published_baseline so nothing renders it as a bar this run cleared or missed.
    #: Macro F1 by training set: normal 0.76, coref 0.78, skip 0.74, all 0.78.
    #: Per relation on the `normal` set, as (P, R, F1):
    reference_classifier = {
        "birthdate": (1.00, 0.99, 1.00), "birthplace": (0.85, 0.77, 0.81),
        "deathdate": (1.00, 0.95, 0.97), "deathplace": (0.73, 0.53, 0.62),
        "occupation": (1.00, 0.99, 1.00), "educatedAt": (0.98, 0.87, 0.92),
        "ofParent": (0.92, 0.54, 0.66), "hasChild": (0.96, 0.36, 0.42),
        "sibling": (0.92, 0.45, 0.57), "other": (0.38, 0.95, 0.54),
        "macro": (0.90, 0.73, 0.76),
    }

    #: Table 4 of the paper: the DISTANT SUPERVISION itself scored against the same gold,
    #: macro F1 0.83 (normal). This is the ceiling the classifier was trained toward, and
    #: it is the more honest reference of the two: a label the matching algorithm got wrong
    #: is a label the classifier was taught wrong.
    reference_matching_macro_f1 = 0.83

    #: How load() orders documents, which decides what --limit buys.
    #:
    #:   "balanced"  round-robin across the scored labels. 1,774 of the 1,800 scoreable
    #:               documents carry exactly ONE scored fact, so document count and fact
    #:               count are the same thing here and ordering cannot buy density the way
    #:               it can for bioevents. What it can buy is per-label support, which is
    #:               what this benchmark's macro F1 needs: gold is uneven, from birthdate
    #:               at 296 facts down to deathplace at 104, so a proportional prefix
    #:               starves the smallest label first. Round-robin maximises the weakest
    #:               label's support at every budget.
    #:   "id"        by page id. A proportional sample of the corpus, for when the
    #:               distribution across labels is itself what is being reported.
    ORDERS = ("balanced", "id")

    def __init__(self, min_facts: int = 1, max_chars: int = 12000,
                 order: str = "balanced"):
        #: People with very few annotated facts still cost a full extraction, so the floor
        #: is exposed rather than hardcoded -- raising it trades coverage for API budget.
        if order not in self.ORDERS:
            raise SystemExit("Biographical: --order must be one of %s, got %r"
                             % (", ".join(self.ORDERS), order))
        self.min_facts = min_facts
        self.max_chars = max_chars
        self.order = order

    # -------------------------------------------------------------- load

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        # Keyed by Wikipedia page id, not by the subject string. The subject strings are
        # surface forms, so grouping on them merges different people: the most frequent
        # are 'Lee', 'Adams' and 'Johnson'. A page id is one person by construction. 37 of
        # the 2,748 pages carry two name variants of that one person ('Thomas Wyatt' and
        # 'Wyatt'), and the longest is taken as the document name.
        by_page: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"sentences": [], "gold": [], "names": set(), "rows": 0,
                     "has_page": False, "had_markers": False})
        unusable = {"no_markers": 0, "unmapped_label": 0}

        for r in _rows(data_root):
            raw = (r.get("sentence") or "").strip()
            if not raw:
                continue
            args = _arguments(r)
            if args is None:
                unusable["no_markers"] += 1
                continue
            subject, obj = args
            # The page id where the release carries one, the subject string otherwise.
            # Falling back is worse and the meta records which was used: subject strings
            # are surface forms, so they merge different people called Lee or Adams.
            page = str(r.get("page") or "").strip() or subject
            if not page:
                continue
            rec = by_page[page]
            rec["has_page"] = bool(str(r.get("page") or "").strip())
            rec["had_markers"] = rec["had_markers"] or bool(MARKER.search(raw))
            rec["rows"] += 1
            rec["names"].add(subject)
            sentence = _strip_markers(raw)
            if sentence not in rec["sentences"]:
                rec["sentences"].append(sentence)

            # The HUMAN label, not the distant-supervision one. They disagree on 578 of
            # 2,900 rows, and the disagreement is not noise in both directions: annotators
            # reclassified heavily toward `other` (808 against 295). Scoring against the
            # automatic label would measure agreement with a known-noisy signal.
            gold_label = (r.get("annotation") or r.get("relation") or "").strip()
            if not gold_label:
                continue
            label = RELEASE_LABELS.get(gold_label)
            if label is None:
                unusable["unmapped_label"] += 1
                continue
            if obj and (label, obj) not in rec["gold"]:
                rec["gold"].append((label, obj))

        built = []
        for page, rec in sorted(by_page.items()):
            scored = [f for f in rec["gold"] if f[0] in SCORED]
            if len(scored) < self.min_facts:
                continue
            built.append((page, rec, scored))

        if self.order == "balanced":
            # Round-robin over the scored labels, each label's own documents kept in page
            # order so the result is deterministic. A document is placed by its FIRST
            # scored label; the 26 documents carrying two are therefore counted once, under
            # whichever label sorts first, rather than being emitted twice.
            buckets: dict[str, list] = defaultdict(list)
            for item in built:
                buckets[sorted(f[0] for f in item[2])[0]].append(item)
            ordered, labels = [], sorted(buckets)
            while any(buckets[lab] for lab in labels):
                for lab in labels:
                    if buckets[lab]:
                        ordered.append(buckets[lab].pop(0))
            built = ordered

        made = 0
        for position, (page, rec, scored) in enumerate(built):
            name = max(rec["names"], key=len) if rec["names"] else page
            text = " ".join(rec["sentences"])[:self.max_chars]
            yield BenchmarkDoc(
                doc_id=page,
                slug=slugify(name) or ("b1_%s" % page),
                name=name,
                text=text,
                gold=tuple(rec["gold"]),
                # Named for what actually happened, not for what usually happens: the
                # grouping key and whether markup was removed both change what the
                # numbers mean, and transform is where that is disclosed.
                transform=tuple(
                    ["grouped_by_wikipedia_page" if rec["has_page"]
                     else "grouped_by_subject_string"]
                    + (["argument_markers_stripped"] if rec["had_markers"] else [])),
                meta={"n_sentences": len(rec["sentences"]), "n_gold": len(rec["gold"]),
                      "n_scored_gold": len(scored), "n_rows": rec["rows"],
                      "name_variants": sorted(rec["names"]),
                      "grouped_by": "wikipedia_page" if rec["has_page"] else "subject_string",
                      "order": position, "ordering": self.order,
                      "scored_labels": sorted({f[0] for f in scored}),
                      "unusable_rows": dict(unusable)})
            made += 1
            if limit and made >= limit:
                return

    # -------------------------------------------------------------- project

    @staticmethod
    def _subject_id(doc: BenchmarkDoc, ex: Extraction) -> str | None:
        """Which entity is the person this document is about."""
        if ex.subject and ex.subject.get("id"):
            return ex.subject["id"]
        want = _fold(doc.name)
        for e in ex.entities:
            if e.get("entity_type") != "person":
                continue
            names = {_fold(e.get("name"))} | {_fold(a) for a in (e.get("aliases") or [])}
            if want in names:
                return e.get("id")
        return None

    @staticmethod
    def _names(ex: Extraction) -> dict[str, str]:
        return {e["id"]: e.get("name", "") for e in ex.entities if isinstance(e, dict)
                and e.get("id")}

    def _vital(self, ex: Extraction, subject_id: str | None, kind: str, names: dict):
        """(date, place name) from this person's birth or death event.

        `location` is an entity *id* per schema/event.schema.json, not a name, so it is
        resolved through entities[] before it can be compared with a gold place string."""
        for ev in ex.events:
            if ev.get("event_type") != kind:
                continue
            if subject_id and not self._is_subject_of(ev, subject_id):
                continue
            return ev.get("date"), names.get(_as_id(ev.get("location")))
        return None, None

    @staticmethod
    def _is_subject_of(ev: dict, subject_id: str) -> bool:
        """Whose birth or death this is -- the participant in the `subject` role, not
        merely anyone present.

        Accepting any participant reads a relative's death as the biographee's own: it
        gave Fritz Haber a death date of 1 May 1915, which is Clara Immerwahr's, because
        he appears in that event. `role` is free text in the schema, so a participant list
        with no roles at all falls back to bare participation rather than dropping the
        event."""
        parts = ev.get("participants") or []
        roled = [p for p in parts if (p.get("role") or "").strip()]
        if roled:
            return any(_as_id(p.get("entity_id")) == subject_id
                       and _fold(p.get("role")) == "subject" for p in roled)
        return any(_as_id(p.get("entity_id")) == subject_id for p in parts)

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        names = self._names(extraction)
        sid = self._subject_id(doc, extraction)
        items: list[tuple[str, Any]] = []
        unmapped: list[tuple[str, str, str, str]] = []
        lossy: list[tuple[str, str, str, str]] = []

        # --- dates and vital places, from events.json rather than relations
        for kind, date_label, place_label in (("birth", "birthdate", "birthplace"),
                                              ("death", "deathdate", "deathplace")):
            date, location = self._vital(extraction, sid, kind, names)
            if date:
                items.append((date_label, date))
                width = vocab.resolution_days(date)
                if width > 1:
                    lossy.append(("event", kind, date_label,
                                  "prediction commits to a %d-day interval" % width))
            if location:
                items.append((place_label, location))

        # --- relations
        for rel in extraction.relations:
            rtype = rel.get("type")
            src, tgt = _as_id(rel.get("source")), _as_id(rel.get("target"))
            target_name = names.get(tgt, "")
            if sid and src != sid and tgt != sid:
                continue                       # a fact about someone else in the document
            if not target_name:
                # A relation pointing at an id with no entity behind it cannot be compared
                # with a gold string. Emitting "" would silently manufacture a false
                # positive that matches nothing and inflates the denominator.
                unmapped.append(("relation", str(rel.get("id", "")), str(rtype),
                                 "target id %r has no entity in entities[]" % tgt))
                continue
            if rtype in ("born_in", "died_in"):
                items.append(("birthplace" if rtype == "born_in" else "deathplace",
                              target_name))
            elif rtype in ("studied_at", "educated_by"):
                items.append(("educatedAt", target_name))
                if rtype == "educated_by":
                    lossy.append(("relation", rel.get("id", ""), "educatedAt",
                                  "educated_by targets a person; educatedAt is "
                                  "institution-valued"))
            elif rtype == "family_of":
                # ofParent / hasChild / sibling all collapse onto this one type. The note
                # recovers the subtype for the minority of instances that carry one -- 35%
                # in the corpus -- so per-subtype figures are reported over that subset
                # only, and combined family recall over all of it.
                sub = self._family_subtype(rel, src == sid)
                items.append((sub or "family", target_name))
                lossy.append(("relation", rel.get("id", ""), sub or "family",
                              "family_of collapses ofParent/hasChild/sibling; subtype "
                              + ("recovered from note" if sub else "not recoverable")))
            else:
                unmapped.append(("relation", str(rel.get("id", "")), str(rtype),
                                 "no target label in Biographical; the `other` class"))

        for ev in extraction.events:
            if ev.get("event_type") not in ("birth", "death", "education"):
                unmapped.append(("event", str(ev.get("id", "")), str(ev.get("event_type")),
                                 "no target label in Biographical; the `other` class"))

        # birthplace/deathplace are the union of two routes -- the born_in/died_in relation
        # and the vital event's own `location` -- so one stated fact can arrive twice.
        # Two predictions of the same value cannot both be right, and the spare one would
        # score as a false positive against a gold set that states it once.
        deduped, seen = [], set()
        for label, value in items:
            key = (label, _fold(value.get("sort_start", "")) if isinstance(value, dict)
                   else _fold(value))
            if key in seen:
                continue
            seen.add(key)
            deduped.append((label, value))

        return Prediction(doc_id=doc.doc_id, items=tuple(deduped),
                          unmapped=tuple(unmapped), lossy=tuple(lossy),
                          meta={"subject_resolved": bool(sid),
                                "duplicate_routes": len(items) - len(deduped)})

    @staticmethod
    def _family_subtype(rel: dict, subject_is_source: bool) -> str | None:
        """ofParent / hasChild / sibling from the relation's free-text note, or None.

        Two shapes occur in the corpus, a bare kinship label ("Father", "youngest son")
        and a full sentence ("Jean Brachet was the younger son of Albert Brachet"), and
        both give direction. Direction is relative to the subject, so which end of the
        relation the subject sits on decides which label a kinship word produces."""
        note = _fold(rel.get("note") or "")
        if not note:
            return None
        parent_words = ("father", "mother", "parent")
        child_words = ("son", "daughter", "child")
        sib_words = ("brother", "sister", "sibling")
        if any(w in note for w in sib_words):
            return "sibling"
        if any(w in note for w in parent_words):
            # the note describes the TARGET's role: target is the subject's parent
            return "ofParent" if subject_is_source else "hasChild"
        if any(w in note for w in child_words):
            return "hasChild" if subject_is_source else "ofParent"
        return None

    # -------------------------------------------------------------- score

    @staticmethod
    def _hit(label: str, gold_value: str, predicted: Any) -> bool:
        if label in ("birthdate", "deathdate"):
            iso = _iso_day(gold_value)
            if not iso or not isinstance(predicted, dict):
                return False
            # Interval containment, not string equality: a year-precision prediction
            # against a day-precision gold is right to the precision the source offered.
            return vocab.contains(predicted, iso)
        return bool(predicted) and _fold(predicted) == _fold(gold_value)

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]],
              extractions: dict[str, Extraction] | None = None) -> ScoreReport:
        pairs = list(pairs)
        extractions = extractions or {}
        # Same reasoning as bioevents: a recall figure is unreadable without knowing how
        # many documents produced nothing. This adapter has never been run through the
        # CLI -- its corpus licence is unresolved -- so this is the attrition it will
        # report on the first real run, not a number anyone has seen yet.
        doc_attrition = {"out_of_scope": 0, "empty_extraction": 0, "did_not_validate": 0}
        for ex in extractions.values():
            scope = getattr(ex, "scope", None) or {}
            if scope.get("fits") is False:
                doc_attrition["out_of_scope"] += 1
            if not getattr(ex, "events", ()) and not getattr(ex, "relations", ()):
                doc_attrition["empty_extraction"] += 1
            if getattr(ex, "exit_code", 0):
                doc_attrition["did_not_validate"] += 1
        tp = defaultdict(int)
        fn = defaultdict(int)
        fp = defaultdict(int)
        widths: list[int] = []
        attrition = {"documents": len(pairs), "no_prediction": 0, "subject_unresolved": 0}
        family_noted = {"matched": 0, "total": 0}

        for doc, pred in pairs:
            if not pred.items:
                attrition["no_prediction"] += 1
            if not pred.meta.get("subject_resolved"):
                attrition["subject_unresolved"] += 1

            by_label: dict[str, list[Any]] = defaultdict(list)
            for label, value in pred.items:
                by_label[label].append(value)
                if label in ("birthdate", "deathdate") and isinstance(value, dict):
                    w = vocab.resolution_days(value)
                    if w > 0:
                        widths.append(w)

            used: set[tuple[str, int]] = set()
            gold_scored = [(r, o) for r, o in doc.gold if r in SCORED]
            for rel, obj in gold_scored:
                # A family gold label matches any recovered family prediction: the schema
                # cannot distinguish the three, so crediting only the exact subtype would
                # score the collapse twice -- once as a miss here, once as `lossy`.
                candidates = FAMILY if rel in FAMILY else (rel,)
                found = None
                for cand in candidates:
                    for i, value in enumerate(by_label.get(cand, [])):
                        if (cand, i) in used:
                            continue
                        if self._hit(rel, obj, value):
                            found = (cand, i)
                            break
                    if found:
                        break
                # `family` holds collapsed relations whose subtype the note did not give.
                if not found and rel in FAMILY:
                    for i, value in enumerate(by_label.get("family", [])):
                        if ("family", i) not in used and self._hit(rel, obj, value):
                            found = ("family", i)
                            break
                if rel in FAMILY:
                    family_noted["total"] += 1
                    if found and found[0] != "family":
                        family_noted["matched"] += 1
                if found:
                    used.add(found)
                    tp[rel] += 1
                else:
                    fn[rel] += 1

            for label, values in by_label.items():
                base = label if label in SCORED else ("ofParent" if label == "family" else label)
                if base not in SCORED:
                    continue
                unmatched = sum(1 for i in range(len(values)) if (label, i) not in used)
                fp[base] += unmatched

        per_label = {}
        for label in SCORED:
            p = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) else 0.0
            r = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) else 0.0
            f = 2 * p * r / (p + r) if (p + r) else 0.0
            per_label[label] = {"precision": round(p, 4), "recall": round(r, 4),
                                "f1": round(f, 4), "support": tp[label] + fn[label]}

        scorable = [l for l in SCORED if per_label[l]["support"]]
        micro_tp = sum(tp[l] for l in SCORED)
        micro_fp = sum(fp[l] for l in SCORED)
        micro_fn = sum(fn[l] for l in SCORED)
        mp = micro_tp / (micro_tp + micro_fp) if (micro_tp + micro_fp) else 0.0
        mr = micro_tp / (micro_tp + micro_fn) if (micro_tp + micro_fn) else 0.0
        scores = {
            "micro_precision": round(mp, 4),
            "micro_recall": round(mr, 4),
            "micro_f1": round(2 * mp * mr / (mp + mr), 4) if (mp + mr) else 0.0,
            "macro_f1": round(sum(per_label[l]["f1"] for l in scorable) / len(scorable), 4)
                        if scorable else 0.0,
        }
        if widths:
            widths.sort()
            scores["median_date_interval_days"] = widths[len(widths) // 2]

        notes = [
            "Sentences are grouped by person into one pseudo-document each "
            "(transform=grouped_by_person), so these figures are NOT comparable to the "
            "paper's sentence-level numbers.",
            "published_baseline is " + self.published_baseline_note,
            "family subtype was recovered from `note` for %d of %d gold family facts; the "
            "rest were credited via the collapsed class and appear in `lossy`."
            % (family_noted["matched"], family_noted["total"]),
        ]
        if widths:
            notes.append("median predicted date interval is %d days -- a containment rate "
                         "achieved by predicting a decade is not the same result as one "
                         "achieved by predicting a day." % scores["median_date_interval_days"])

        return ScoreReport(
            benchmark=self.name, metric=self.metric, scores=scores,
            published_baseline=dict(self.published_baseline),
            not_applicable={
                "occupation": "No typed home in the schema: entity.subtype is free text "
                              "and entity.summary is prose. Excluded from the macro "
                              "average rather than scored 0.",
                "other": "The benchmark's catch-all class, not a label to predict. "
                         "Extracted items with no target appear in Prediction.unmapped.",
            },
            per_label=per_label, attrition=dict(attrition, **doc_attrition),
            n_docs=len(pairs), notes=notes)

    # -------------------------------------------------------------- coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        from ...harness.coverage import BIOGRAPHICAL
        return dict(BIOGRAPHICAL["cells"])


_ISO = re.compile(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def _iso_day(value: str) -> str | None:
    """A gold date string -> the ISO day to test containment against.

    A year-only or month-only gold is widened to its first day, which is the point the
    prediction's interval is asked to contain."""
    m = _ISO.search(str(value))
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2) or "01", m.group(3) or "01"
    return "%s-%s-%s" % (y, mo, d)


ADAPTER = BiographicalAdapter()
