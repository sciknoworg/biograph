"""Benchmark 3: WikiLifeTrajectory (Zhang et al., ICWSM 2025; repo ZhangDataLab/COSMOS).

Gold is a `(person, time, location)` triplet judged to be part of a person's life
trajectory. This adapter uses the `regular` partition only: 274 manually annotated
positive facts over ten COMPLETE Wikipedia biographies. That partition is the reason this
benchmark is worth running at all -- it is the only external corpus here whose unit is a
whole biography rather than a sentence, and whose documents (median ~18k characters) are
within an order of magnitude of this project's own (median 35k).

WHAT IT CAN AND CANNOT MEASURE. Every one of the 274 gold facts is positive; the partition
contains no negatives. So RECALL is the only sound metric. An extracted fact absent from
gold may be a true fact the annotators did not mark -- their unit is the trajectory, not
the life -- so counting it as a false positive would punish the extractor for reading more
of the document than the annotation covers. Unmatched extractions are counted and reported
as `unmatched_predictions`, never as errors. The `representative` partition does carry
negatives, but its unit is a candidate triplet pre-generated from a sentence, which is the
classification task this pipeline does not perform; it is deliberately not loaded.

THE DOCUMENTS ARE REBUILT FROM THE RELEASE, NOT FETCHED. Each row carries the `paragraph`
its fact came from, and the 94 distinct paragraphs reassemble into ten documents of 7k-88k
characters. Fetching the live Wikipedia article instead would be closer to "the complete
page", but the annotation is from 2024 and an article edited since could silently drop gold
facts, turning drift into apparent recall failure. Rebuilding is reproducible and
guarantees every gold fact's evidence is present. The cost is that paragraphs containing no
trajectory fact are absent, so the input has fewer distractors than a real page -- which is
a further reason not to report precision from it. Disclosed as `rebuilt_from_paragraphs`.

THE GOLD PERSON IS OFTEN NOT THE SUBJECT. Charles de Gaulle's 57 facts name him 39 times
across four surface forms -- `de Gaulle`, `De Gaulle`, `Charles de Gaulle`, `he` -- and name
eighteen other people, Churchill and Eisenhower among them. A matcher keyed on the document
subject would miss a third of that document. Matching is therefore against any extracted
person, by the same longest-word rule build_site.py's own grounding check uses, with bare
pronouns resolved to the document subject.

TIME IS HETEROGENEOUS AND 27 FACTS ARE UNANCHORABLE. Of 274 gold times: 118 bare years, 63
full dates, 44 month-year, 13 year ranges, and 27 that carry no year at all -- `13 June`,
`six months`, `the following year`, `70 years old`, `five`. The last group cannot be placed
on a timeline by anyone, so it is reported as `unanchorable_time` and excluded from the
date-matched denominator rather than scored as a miss.

Nothing is downloaded. load() reads a local copy via --data-root; see
experiments/corpora/wikilife/README.md for provenance and the licence position.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from ...harness.interface import BenchmarkDoc, Extraction, Prediction, ScoreReport

#: Bare pronouns the annotators used where the subject was obvious from context.
PRONOUNS = {"he", "she", "they", "him", "her", "his", "hers", "their", "it"}

#: Words that carry no identifying signal in a person or place name.
STOP = {"the", "a", "an", "of", "in", "at", "to", "and", "for", "on", "with", "from",
        "by", "as", "former", "late", "near", "street", "city", "town", "university",
        "college", "school", "hospital", "department", "mr", "mrs", "dr", "general",
        "pastor", "minister", "president", "sir", "lord"}

MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

_YEAR_RANGE = re.compile(r"(\d{4})\s*[-–—]\s*(\d{4})")
_DMY = re.compile(r"(\d{1,2})\s+(" + _MONTH_ALT + r")\.?,?\s+(\d{4})", re.I)
_MDY = re.compile(r"(" + _MONTH_ALT + r")\.?\s+(\d{1,2}),?\s+(\d{4})", re.I)
_MY = re.compile(r"(" + _MONTH_ALT + r")\.?,?\s+(\d{4})", re.I)
_YEAR = re.compile(r"(\d{4})")

_LAST_DAY = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _fold(value: Any) -> str:
    """Casefold, strip accents, collapse whitespace."""
    flat = "".join(c for c in unicodedata.normalize("NFKD", str(value))
                   if not unicodedata.combining(c))
    return " ".join(flat.casefold().split())


def _tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _fold(value)) if t and t not in STOP}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if not s or not s[0].isalpha():
        s = "wlt_" + s
    return s[:60] or "wlt_doc"


def parse_time(value: Any) -> tuple[str, str] | None:
    """A gold time string -> the [start, end] ISO interval it denotes, or None.

    None means unanchorable, not unparseable: `six months` and `70 years old` are durations
    and ages, and `13 June` names a day in no particular year. Returning a guessed interval
    for those would manufacture agreement or disagreement out of nothing.
    """
    s = str(value or "").strip()
    if not s:
        return None
    m = _YEAR_RANGE.search(s)
    if m:
        return ("%s-01-01" % m.group(1), "%s-12-31" % m.group(2))
    m = _DMY.search(s)
    if m:
        day = "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        return (day, day)
    m = _MDY.search(s)
    if m:
        day = "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        return (day, day)
    m = _MY.search(s)
    if m:
        mo = MONTHS[m.group(1).lower()[:3]]
        return ("%s-%02d-01" % (m.group(2), mo),
                "%s-%02d-%02d" % (m.group(2), mo, _LAST_DAY[mo - 1]))
    m = _YEAR.search(s)
    if m:
        return ("%s-01-01" % m.group(1), "%s-12-31" % m.group(1))
    return None


def _overlaps(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Do two closed ISO intervals share any day?

    Overlap, not containment, because neither side is reliably the more precise one: gold
    is a bare year for 118 of 274 facts while the extraction may hold a day, and the
    reverse also occurs. Requiring containment in either fixed direction would score a
    correct answer as wrong whenever the precisions happened to fall the other way.
    """
    return a[0] <= b[1] and b[0] <= a[1]


def _name_match(gold: str, candidate: str) -> bool:
    """Is `candidate` the person or place `gold` names?

    Surface forms vary within one document -- `de Gaulle`, `De Gaulle`, `Charles de
    Gaulle` -- so the test is on the longest significant word, which is the same rule
    build_site.py's grounding check uses on entity names. For places the two sides also
    differ in granularity, `Warsaw` against `Bielanska street in Warsaw`, so a containment
    of token sets counts as well.
    """
    g, c = _tokens(gold), _tokens(candidate)
    if not g or not c:
        return False
    if g <= c or c <= g:
        return True
    longest = max(g, key=len)
    return longest in c and len(longest) > 3


class WikiLifeAdapter:
    name = "wikilife"
    citation = ("Zhang, Li, Liu and Zhang, 'Paths of A Million People: Extracting Life "
                "Trajectories from Wikipedia', ICWSM 2025 (arXiv:2406.00032); repo "
                "ZhangDataLab/COSMOS")
    license = ("UNRESOLVED -- the repository states no licence and has no LICENSE file, so "
               "the paper's terms do not cover the annotations. Wikipedia-derived, so CC "
               "BY-SA 4.0 upstream. Not redistributed here: nothing is fetched by this "
               "adapter, which reads a local copy via --data-root, and "
               "experiments/corpora/wikilife/ carries the provenance note. Resolve with "
               "the authors before publishing any derived artifact.")
    label_space = ("life_trajectory",)
    metric = ("recall of gold (person, time, location) trajectory facts over complete "
              "biographies; precision is not measurable against an all-positive gold")
    published_baseline: dict[str, float] = {}
    published_baseline_note = (
        "empty. The paper reports about 82.1% trajectory recall for COSMOS on this same "
        "regular partition, and 85.95 F1 on the representative test, but neither is a bar "
        "this run clears or misses. COSMOS classifies candidate triplets that a generator "
        "has already produced from a sentence: the person, the time and the location are "
        "all handed to it, and it decides true or false. This pipeline receives a whole "
        "biography and must find the people, the dates and the places, and decide which "
        "belong together. Their recall is over candidates presented; this recall is over "
        "facts nobody pointed at.")

    #: Recorded for context only, deliberately outside published_baseline so no report can
    #: render it as a bar. See published_baseline_note for why it is not comparable.
    reference_cosmos_regular_recall = 0.821

    #: Only the `regular` partition is used. `representative` is the candidate-triplet
    #: classification set: its negatives exist to train and test a binary classifier over
    #: triplets someone else generated, which is not the task performed here.
    PARTITION = "regular"

    #: Relations that place a person somewhere. A trajectory fact needs a time too, which
    #: a relation never carries itself -- see project().
    PLACE_RELATIONS = ("born_in", "died_in", "lived_in", "visited", "relocated_to",
                       "studied_at", "worked_at", "employed_by")

    #: Matches build_site.py's own --max-chars default, so this adapter never truncates
    #: more aggressively than the extractor would. At 60,000 it did: Charles de Gaulle is
    #: 88,411 characters and lost 28,000 of them, which would have surfaced as the
    #: extractor failing to recall facts whose evidence this adapter had already removed.
    DEFAULT_MAX_CHARS = 180_000

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS):
        self.max_chars = max_chars
        self.load_attrition: dict[str, int] = {"unanchorable_time": 0, "truncated_docs": 0}

    # -------------------------------------------------------------- load

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        path = None
        for dirpath, _d, filenames in os.walk(data_root):
            for fn in filenames:
                if fn.lower() == "regular.pkl":
                    path = os.path.join(dirpath, fn)
        if not path:
            raise SystemExit(
                "WikiLifeTrajectory: no regular.pkl under %s.\n"
                "  Only the regular partition is used -- 274 manually annotated facts over "
                "ten complete biographies. See experiments/corpora/wikilife/README.md for "
                "how to obtain it." % data_root)
        try:
            import pandas as pd
        except ImportError:
            raise SystemExit("WikiLifeTrajectory: the release is a pandas pickle; "
                             "pip install pandas to read it.")
        frame = pd.read_pickle(path)

        docs: dict[str, dict] = defaultdict(
            lambda: {"paragraphs": [], "gold": [], "unanchorable": 0})
        for _i, row in frame.iterrows():
            title = str(row.get("sample_source") or "").strip()
            raw = list(row.get("raw_label") or [])
            if not title or len(raw) < 3:
                continue
            rec = docs[title]
            paragraph = str(row.get("paragraph") or "")
            # Paragraphs repeat across the rows of one biography -- 274 facts come from 94
            # distinct paragraphs -- and are kept in first-seen order, so the rebuilt
            # document reads in the order the release presents it.
            if paragraph and paragraph not in rec["paragraphs"]:
                rec["paragraphs"].append(paragraph)
            person, time_text, place = str(raw[0]), str(raw[1]), str(raw[2])
            interval = parse_time(time_text)
            if interval is None:
                rec["unanchorable"] += 1
            rec["gold"].append({"person": person, "time": time_text,
                                "location": place, "interval": interval})

        made = 0
        for title, rec in sorted(docs.items()):
            whole = "\n\n".join(rec["paragraphs"])
            text = whole[:self.max_chars]
            dropped = len(whole) - len(text)
            if dropped:
                self.load_attrition["truncated_docs"] += 1
            self.load_attrition["unanchorable_time"] += rec["unanchorable"]
            yield BenchmarkDoc(
                doc_id=title, slug=slugify(title), name=title, text=text,
                gold=tuple(rec["gold"]),
                transform=("rebuilt_from_paragraphs", "partition=regular"),
                meta={"n_gold": len(rec["gold"]), "n_paragraphs": len(rec["paragraphs"]),
                      "unanchorable_time": rec["unanchorable"], "chars": len(text),
                      # Never silent: a truncated document loses the evidence for gold
                      # facts, and that loss would otherwise read as the extractor
                      # missing them.
                      "chars_dropped": dropped})
            made += 1
            if limit and made >= limit:
                return

    # -------------------------------------------------------------- project

    @staticmethod
    def _as_id(value: Any) -> str:
        """An entity reference as a string safe to use as a dict key.

        The schema says these are ids. A model once emitted one as an object, the dict
        reached a lookup as a key, and the TypeError ended a 220-document run.
        """
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            inner = value.get("id") or value.get("entity_id")
            return inner if isinstance(inner, str) else ""
        return ""

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        names = {e["id"]: e.get("name", "") for e in extraction.entities
                 if isinstance(e, dict) and e.get("id")}
        kinds = {e["id"]: e.get("entity_type") for e in extraction.entities
                 if isinstance(e, dict) and e.get("id")}
        items, unmapped, lossy = [], [], []

        # A trajectory fact needs all three parts at once, and an event is where biograph
        # holds them together: the date on the event, the place in `location`, the people
        # in `participants`. Each missing part is recorded with which part was missing,
        # because "the extractor found nothing" and "the extractor found an undated event"
        # are different failures.
        for ev in extraction.events:
            if not isinstance(ev, dict):
                continue
            date = ev.get("date") or {}
            start, end = date.get("sort_start"), date.get("sort_end")
            place = names.get(self._as_id(ev.get("location")), "")
            people = [names.get(self._as_id(p.get("entity_id")), "")
                      for p in (ev.get("participants") or []) if isinstance(p, dict)]
            people = [p for p in people if p]
            eid, etype = str(ev.get("id") or ""), str(ev.get("event_type"))
            if not (start and end):
                unmapped.append(("event", eid, etype,
                                 "no sortable date; a trajectory fact needs a time"))
                continue
            if not place:
                unmapped.append(("event", eid, etype,
                                 "no location entity; a trajectory fact needs a place"))
                continue
            if not people:
                unmapped.append(("event", eid, etype,
                                 "no participant; a trajectory fact needs a person"))
                continue
            for person in people:
                items.append({"person": person, "place": place, "interval": (start, end),
                              "source": "event", "id": eid, "type": etype})

        # A place relation carries no date of its own. Where it names the event that
        # established it, that event's date completes the triple; where it does not, the
        # fact is real but untimed, which the schema permits and a trajectory does not.
        by_id = {ev.get("id"): ev for ev in extraction.events if isinstance(ev, dict)}
        for rel in extraction.relations:
            if not isinstance(rel, dict) or rel.get("type") not in self.PLACE_RELATIONS:
                continue
            person = names.get(self._as_id(rel.get("source")), "")
            target_id = self._as_id(rel.get("target"))
            place = names.get(target_id, "")
            rid, rtype = str(rel.get("id") or ""), str(rel.get("type"))
            if not (person and place):
                continue
            ev = by_id.get(rel.get("event_id")) or {}
            date = (ev.get("date") or {}) if isinstance(ev, dict) else {}
            start, end = date.get("sort_start"), date.get("sort_end")
            if not (start and end):
                unmapped.append(("relation", rid, rtype,
                                 "undated relation; the schema permits it, a trajectory "
                                 "fact does not"))
                continue
            if kinds.get(target_id) == "organization":
                lossy.append(("relation", rid, rtype,
                              "target is an organization, scored as the place it stands "
                              "for; the gold mixes both granularities"))
            items.append({"person": person, "place": place, "interval": (start, end),
                          "source": "relation", "id": rid, "type": rtype})

        return Prediction(doc_id=doc.doc_id, items=tuple(items),
                          unmapped=tuple(unmapped), lossy=tuple(lossy),
                          meta={"n_candidates": len(items)})

    # -------------------------------------------------------------- score

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]],
              extractions: dict[str, Extraction] | None = None) -> ScoreReport:
        pairs = list(pairs)
        extractions = extractions or {}

        recalled = 0
        scorable = 0
        unanchorable = 0
        partial = {"person_and_place": 0, "person_and_time": 0, "place_and_time": 0}
        matched_ids: set[tuple[str, str]] = set()
        total_predictions = 0
        per_doc: dict[str, dict[str, int]] = {}

        for doc, pred in pairs:
            gold = list(doc.gold or ())
            subject = doc.name
            items = list(pred.items)
            total_predictions += len(items)
            doc_hit = 0
            doc_scorable = 0

            for fact in gold:
                if fact.get("interval") is None:
                    # Not a miss: no system could place `six months` or `70 years old` on a
                    # timeline. Counted apart and kept out of the denominator.
                    unanchorable += 1
                    continue
                doc_scorable += 1
                want_person = fact["person"]
                if _fold(want_person) in PRONOUNS:
                    want_person = subject
                hit = None
                for idx, item in enumerate(items):
                    person_ok = _name_match(want_person, item["person"])
                    place_ok = _name_match(fact["location"], item["place"])
                    time_ok = _overlaps(fact["interval"], item["interval"])
                    if person_ok and place_ok and time_ok:
                        hit = idx
                        break
                    # Near misses, to say WHICH of the three parts the extractor got wrong.
                    if person_ok and place_ok:
                        partial["person_and_place"] += 1
                    elif person_ok and time_ok:
                        partial["person_and_time"] += 1
                    elif place_ok and time_ok:
                        partial["place_and_time"] += 1
                if hit is not None:
                    recalled += 1
                    doc_hit += 1
                    matched_ids.add((doc.doc_id, items[hit]["id"]))
            scorable += doc_scorable
            per_doc[doc.doc_id] = {"gold": len(gold), "scorable": doc_scorable,
                                   "recalled": doc_hit, "predictions": len(items)}

        recall = recalled / scorable if scorable else 0.0
        unmatched = total_predictions - len(matched_ids)

        attrition = {"documents": len(pairs), "gold_facts": scorable + unanchorable,
                     "scorable_gold_facts": scorable,
                     "unanchorable_time": unanchorable,
                     # Not false positives. See the note below and the module docstring.
                     "unmatched_predictions": unmatched,
                     "empty_extraction": 0, "out_of_scope": 0, "did_not_validate": 0}
        for ex in extractions.values():
            if not getattr(ex, "events", ()) and not getattr(ex, "relations", ()):
                attrition["empty_extraction"] += 1
            if (getattr(ex, "scope", None) or {}).get("fits") is False:
                attrition["out_of_scope"] += 1
            if getattr(ex, "exit_code", 0):
                attrition["did_not_validate"] += 1

        notes = [
            "Recall only. Every gold fact in this partition is positive -- there are no "
            "negatives -- so an extracted fact absent from gold may be a true fact the "
            "annotators did not mark, their unit being the trajectory rather than the "
            "life. %d such predictions are counted as unmatched_predictions and are NOT "
            "scored as false positives." % unmatched,
            "%d of %d gold facts carry a time no system can anchor -- `six months`, `13 "
            "June`, `70 years old` -- and are excluded from the denominator rather than "
            "counted as misses." % (unanchorable, scorable + unanchorable),
            "Documents are rebuilt from the paragraphs the release ships, not fetched from "
            "Wikipedia, so every gold fact's evidence is present and no article edited "
            "since the 2024 annotation can turn drift into apparent recall failure. The "
            "cost is that paragraphs holding no trajectory fact are absent, so the input "
            "carries fewer distractors than a real page -- a further reason precision is "
            "not reported.",
            "A trajectory fact needs a person, a time and a place at once. Near misses are "
            "reported per missing part: %d matched person and place but not time, %d "
            "person and time but not place, %d place and time but not person."
            % (partial["person_and_place"], partial["person_and_time"],
               partial["place_and_time"]),
            self.published_baseline_note,
        ]

        return ScoreReport(
            benchmark=self.name, metric=self.metric,
            scores={"trajectory_recall": round(recall, 4),
                    "gold_recalled": recalled,
                    "gold_scorable": scorable,
                    "predictions": total_predictions},
            published_baseline=dict(self.published_baseline),
            not_applicable={
                "precision": "The regular partition is all-positive, so precision cannot "
                             "be computed: an unmatched prediction is as likely to be a "
                             "true fact outside the annotation as an error.",
                "event_type": "Gold carries no event type -- its semantic label is "
                              "trajectory or not-trajectory -- so none of the 22 types "
                              "can be compared against anything.",
            },
            per_label={"life_trajectory": {"recall": round(recall, 4),
                                           "support": scorable,
                                           "recalled": recalled}},
            attrition=attrition, n_docs=len(pairs), notes=notes)

    # -------------------------------------------------------------- coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        """This benchmark's column of the vocabulary matrix.

        Its label is trajectory or not-trajectory, so no event or relation type maps onto
        a type. What decides participation is whether a type can carry a person, a time
        and a place at once: an event can, a place relation can only with a dated event
        beside it, and everything else cannot take part at all.
        """
        cells: dict[str, tuple[str, str]] = {}
        for kind in ("birth", "death", "education", "employment_start", "employment_end",
                     "relocation", "visit", "meeting", "conference", "public_demonstration",
                     "retirement", "role_change", "award", "invention", "patent_filed",
                     "patent_granted", "publication", "product_launch", "company_founded",
                     "company_sold", "company_renamed", "other"):
            cells["event:%s" % kind] = (
                "untyped",
                "participates when the event carries both a date and a location; the gold "
                "label is trajectory/not-trajectory, so the type itself is never compared")
        for rel in self.PLACE_RELATIONS:
            cells["relation:%s" % rel] = (
                "partial",
                "places a person somewhere but carries no time; contributes only when an "
                "event_id supplies a dated event")
        return cells


ADAPTER = WikiLifeAdapter()
