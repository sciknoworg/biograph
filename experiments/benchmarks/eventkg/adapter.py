"""Benchmark 5: EventKG biographical timelines (Gottschalk & Demidova, Semantic Web 2019).

This is the closest published work to what biograph does, which is the only reason to run
it. It generates a dated biographical timeline for a person -- but in the opposite
direction. EventKG+BT is handed a knowledge graph and selects which of a person's temporal
relations belong on a timeline, using features computed FROM the graph (entity types,
Wikipedia link counts, property frequency). Barack Obama has 2,608 temporal relations in
EventKG and roughly twelve belong on his timeline. Their model never reads a biography.
biograph is handed a biography and must produce the graph. The benchmark's gold is
therefore reusable, and its task is not: nothing here reproduces their metric, and their
published figures are not a bar this pipeline clears or misses.

WHAT THE RELEASE ACTUALLY IS. One file, `benchmark.tsv`, nine columns:

    entity_label  entity_id  property  connected_entity_label  connected_entity_id
    start_date  end_date  biography_score  wikipedia_score

    Rachel_Weisz  entity_817926  .../P1346  Academy_Award_for_Best_Supporting_Actress
    entity_5589621  2005-01-01  2005-12-31  0.0  1.0

Every row is a CANDIDATE relation, and the two scores are binary relevance judgements
(0.0/1.0) from the two biographical sources the authors aligned against. Positives are a
fraction of a percent of rows; the rest is the distractor pool their classifier had to
reject. The site's own field documentation names the score columns `bio_score` and
`wiki_score`; the file says `biography_score` and `wikipedia_score`. The file wins.

ONLY THE WIKIPEDIA HALF IS RUNNABLE, AND THAT IS A LICENCE FACT, NOT A DESIGN CHOICE.
`biography_score` was derived from Thefamouspeople.com and Biography.com article texts,
which are third-party copyrighted and are not redistributed with the benchmark. Those
documents cannot be obtained, so that column cannot be scored and is read only to report
how much of the benchmark is unreachable. `wikipedia_score` was derived from English
Wikipedia abstracts, which are CC BY-SA and fetchable, so that column is the gold here.
See fetch_abstracts.py, and the README for the licence position on both halves.

THE ABSTRACTS ARE PINNED TO A 2019 REVISION. The judgements were made against Wikipedia as
it stood when the paper was written. Scoring against today's article would charge seven
years of editing to the extractor as recall failure: an abstract rewritten since could have
dropped a gold fact entirely. fetch_abstracts.py resolves each title to its last revision
before a cutoff date and stores that text. Disclosed as `revision_pinned`.

FOUR THINGS THE GOLD'S CONSTRUCTION FORCES.

**The same fact appears under several properties.** Rachel Weisz in `The Whistleblower` is
three rows -- YAGO `actedIn`, DBpedia `starring`, Wikidata `P161` -- each separately
labelled. Counting them as three gold facts would inflate the denominator with knowledge-
graph vocabulary redundancy and depress recall by a factor set by how many of the four
source graphs happened to cover a relation. Gold is deduplicated on
`(connected_entity_id, start_date, end_date)`; the property set is kept on the fact, and
both denominators are reported.

**`wikipedia:link` carries no relation type.** A large share of rows have it, and it means
only that two entities are linked and co-temporal. It has no target in biograph's 27
relation types, so for those rows relation type is unscoreable in either direction -- the
same situation as WikiBio's untyped `EVENT`. The typed rows are no better behaved: the
property vocabulary spans Wikidata P-numbers, DBpedia ontology terms and YAGO resources,
and much of it is not biographical at all (`P170` creator, `P127` owned-by, `P136` genre).
Relation type is named not-applicable.

**The dates are knowledge-graph validity intervals, and often belong to the connected
entity rather than to anything that happened to the person.** A `wikipedia:link` row
joining Delacroix to `Vincent_van_Gogh` carries `1853-03-30 .. 1890-07-29` -- van Gogh's
lifespan. A row joining Rachel Weisz to `World_War_II` carries the war's span, and is
labelled relevant because her family fled it. Comparing those to the date biograph assigns
an event in the person's life is a category error. Date agreement is therefore computed
only over rows whose connected entity is an EVENT in EventKG (`connected_entity_id`
begins `event_`) or whose property is in DATED_PROPERTIES, where the interval is the
relation's own validity. Every other row is scored by name alone and counted in
`date_semantics_unusable`.

**Some gold rows have no label.** `connected_entity_label` is `-` for entities EventKG
holds without an English Wikipedia title, and one of them carries the single most
important fact in the file: Rachel Weisz's birth arrives as an unlabelled entity dated
`1970-03-07`. An unnameable target cannot be matched by name, so those rows are excluded
from the name-matched denominator and reported as `unlabelled_gold`.

WHAT IS MEASURED. Recall, in two tiers, mirroring the trigger anchoring in B2 and B4:

    strong  the connected entity is named by an extracted item AND an extracted event's
            date interval overlaps the gold interval
    weak    the connected entity is named anywhere in the extracted graph

Relations carry no date in biograph's schema -- dates live on events -- so only an event
can earn the strong tier, and a relation or entity match alone is weak by construction.
That is a property of the data model, not of this benchmark, and it is why the two tiers
are reported separately rather than summed.

PRECISION IS NOT REPORTED, BUT THE DISTRACTOR POOL IS. The 0.0 rows are not false: they
are relations EventKG holds for this person which the abstract does not mention. An
extraction landing on one is either a fact the rule-based alignment missed or a fact
imported from outside the document, and this benchmark cannot tell those apart. The rate
is reported as `distractor_hit_rate` for what it is -- a diagnostic, not an error count.

Nothing is downloaded here. load() reads a local copy via --data-root.
"""
from __future__ import annotations

import csv
import os
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from ...harness.interface import BenchmarkDoc, Extraction, Prediction, ScoreReport

#: The columns the release actually ships, in order. A file whose header does not start
#: with these is refused rather than guessed at.
COLUMNS = ("entity_label", "entity_id", "property", "connected_entity_label",
           "connected_entity_id", "start_date", "end_date",
           "biography_score", "wikipedia_score")

#: Missing value, in both the label and the date columns.
MISSING = "-"

#: Properties whose interval is the relation's own validity rather than the connected
#: entity's lifespan. Only these, plus rows pointing at an EventKG event, take part in
#: date-matched scoring. Deliberately short: a property is listed only where the release's
#: own rows show the interval tracking the relation.
DATED_PROPERTIES = frozenset({
    "http://www.wikidata.org/entity/P26",      # spouse
    "http://www.wikidata.org/entity/P451",     # unmarried partner
    "http://www.wikidata.org/entity/P1346",    # winner (award, in the award's year)
    "http://www.wikidata.org/entity/P166",     # award received
    "http://www.wikidata.org/entity/P69",      # educated at
    "http://www.wikidata.org/entity/P108",     # employer
    "http://www.wikidata.org/entity/P39",      # position held
    "http://www.wikidata.org/entity/P161",     # cast member (film release date)
    "http://dbpedia.org/ontology/starring",
    "http://dbpedia.org/ontology/award",
    "http://yago-knowledge.org/resource/actedIn",
    "http://yago-knowledge.org/resource/created",
    "http://yago-knowledge.org/resource/graduatedFrom",
    "http://yago-knowledge.org/resource/worksAt",
})

#: Tokens that carry no identifying signal, so a gold label consisting only of these
#: cannot be matched on. Kept consistent with the wikilife adapter's list.
STOP = {"the", "a", "an", "of", "in", "at", "to", "and", "for", "on", "with", "from",
        "by", "as", "award", "awards", "best", "film", "movie", "tv", "series",
        "national", "international", "united", "states", "city", "university",
        "college", "school"}

#: A gold label must contribute at least this many distinctive tokens to be matchable.
#: `New_York`, `London`, `Christmas` and `England` all appear as connected entities, and
#: matching them by a single common word credits recall for words any biography contains.
MIN_DISTINCTIVE_TOKENS = 1

#: Parenthetical disambiguators in Wikipedia titles: `Youth_(2015_film)`.
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

DEFAULT_MAX_CHARS = 180_000


#: Apostrophes are removed rather than treated as separators. `Thiong'o` split into
#: `thiong` + `o` while a biography spelling it `Thiongo` gave one token, so the two could
#: never match -- and the stray single letter was a token that matched almost anything.
_APOSTROPHE = re.compile("['‘’ʼ´`]")


def _fold(value: Any) -> str:
    """Casefold, strip accents and apostrophes, collapse whitespace and underscores."""
    flat = "".join(c for c in unicodedata.normalize("NFKD", str(value))
                   if not unicodedata.combining(c))
    return " ".join(_APOSTROPHE.sub("", flat.replace("_", " ")).casefold().split())


def _tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", _fold(value)) if t and t not in STOP}


def label_tokens(label: str) -> set[str]:
    """The distinctive tokens of a gold label, with any disambiguator removed.

    `Youth_(2015_film)` -> {"youth"}; the year and the word `film` are the encyclopaedia's
    disambiguation apparatus, not part of the name a biography would use.
    """
    return _tokens(_PAREN.sub("", _fold(label)))


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", _fold(name)).strip("_")
    if not s or not s[0].isalpha():
        s = "ekg_" + s
    return s[:60] or "ekg_doc"


def parse_date(value: str) -> str | None:
    """An ISO date from the release, or None for the `-` placeholder.

    Anything that is not exactly `YYYY-MM-DD` is None rather than a guess: the release is
    machine-generated and a row whose date does not parse is a row whose date this adapter
    does not understand, which must not become a silent match.
    """
    s = str(value or "").strip()
    if not s or s == MISSING:
        return None
    return s if _ISO.match(s) else None


def gold_interval(start: str, end: str) -> tuple[str, str] | None:
    """The [start, end] interval a gold row denotes, or None if it has no usable date.

    Two conventions in the release have to be undone. An absent `end_date` means a point
    in time, not an open-ended relation -- a film release, an award, a birth. And a
    year-precision fact is stored as `YYYY-01-01`, indistinguishable from a genuine
    1 January; with no end date it is widened to the whole year, because leaving it as a
    point would score an extractor that correctly read `June 1830` as wrong for not
    saying 1 January. The cost is that a real 1 January point event is widened too,
    which can only make this adapter more generous, never less.
    """
    s, e = parse_date(start), parse_date(end)
    if s is None:
        return None
    if e is None:
        return (s, "%s-12-31" % s[:4]) if s.endswith("-01-01") else (s, s)
    return (s, e) if s <= e else (e, s)


def _overlaps(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """Interval overlap, not containment.

    Gold intervals and extracted intervals carry different precisions on purpose -- a
    year-precision event against a day-precision gold must count as agreement, and
    containment in either direction would reject one of those two cases.
    """
    return a[0] <= b[1] and b[0] <= a[1]


def _name_match(gold: set[str], candidate: str) -> bool:
    """Does `candidate` name the gold entity?

    Token containment, with the gold label's distinctive tokens all required. A gold
    label reduced to nothing by the stop list never matches, which is why
    `label_tokens` is checked for emptiness by the caller rather than here.
    """
    if not gold:
        return False
    return gold <= _tokens(candidate)


# --------------------------------------------------------------------- gold


class GoldFact:
    """One deduplicated gold relation: a target entity, an interval, and its properties.

    __slots__ because a full benchmark run holds every candidate row for 2,760 people in
    memory at once and the vast majority are distractors.
    """

    __slots__ = ("entity_id", "label", "tokens", "interval", "properties", "is_event")

    def __init__(self, entity_id: str, label: str, interval: tuple[str, str] | None,
                 properties: set[str], is_event: bool) -> None:
        self.entity_id = entity_id
        self.label = label
        self.tokens = label_tokens(label) if label != MISSING else set()
        self.interval = interval
        self.properties = properties
        self.is_event = is_event

    @property
    def labelled(self) -> bool:
        return bool(self.tokens)

    @property
    def date_usable(self) -> bool:
        """Is this row's interval the relation's own validity, rather than its target's?"""
        if self.interval is None:
            return False
        return self.is_event or bool(self.properties & DATED_PROPERTIES)

    def as_dict(self) -> dict[str, Any]:
        return {"entity_id": self.entity_id, "label": self.label,
                "interval": list(self.interval) if self.interval else None,
                "properties": sorted(self.properties), "is_event": self.is_event}


def _dedupe(rows: list[dict[str, str]]) -> list[GoldFact]:
    """Candidate rows -> one GoldFact per (connected entity, interval).

    The release labels each source graph's version of a relation separately, so
    `actedIn`, `starring` and `P161` arrive as three rows for one fact.
    """
    merged: dict[tuple[str, Any], GoldFact] = {}
    for row in rows:
        interval = gold_interval(row["start_date"], row["end_date"])
        key = (row["connected_entity_id"], interval)
        fact = merged.get(key)
        if fact is None:
            merged[key] = GoldFact(
                entity_id=row["connected_entity_id"],
                label=row["connected_entity_label"],
                interval=interval,
                properties={row["property"]},
                is_event=row["connected_entity_id"].startswith("event_"))
        else:
            fact.properties.add(row["property"])
            # A labelled row wins over `-`: the same entity can arrive both ways.
            if fact.label == MISSING and row["connected_entity_label"] != MISSING:
                fact.label = row["connected_entity_label"]
                fact.tokens = label_tokens(fact.label)
    return list(merged.values())


# ----------------------------------------------------------------- adapter


class EventKgAdapter:
    """Recall of a person's Wikipedia-attested temporal relations, two anchor tiers."""

    name = "eventkg"
    citation = "Gottschalk & Demidova, Semantic Web 10(6), 2019"
    license = ("UNRESOLVED for the biography half -- see "
               "experiments/corpora/eventkg/README.md; Wikipedia abstracts are CC BY-SA 4.0")
    label_space = ("<untyped>",)
    metric = ("recall of Wikipedia-attested temporal relations per person, name-anchored "
              "(weak) and date-anchored (strong); no precision -- see module docstring")
    #: Their published figures measure a different task on a different input and are
    #: deliberately not a baseline. Recorded so the paper can cite them as context.
    published_baseline: dict[str, float] = {}
    reference_timeline_task = ("SVM relation selection over knowledge-graph features; "
                               "input is the graph, not the biography")

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS, min_facts: int = 1,
                 cutoff: str = "2019-05-21") -> None:
        self.max_chars = max_chars
        self.min_facts = min_facts
        self.cutoff = cutoff

    # ---------------------------------------------------------------- load

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        tsv = os.path.join(data_root, "benchmark.tsv")
        if not os.path.isfile(tsv):
            raise SystemExit(
                "benchmark.tsv not found under %s -- see "
                "experiments/corpora/eventkg/README.md for the download command" % data_root)
        abstracts = os.path.join(data_root, "abstracts")
        if not os.path.isdir(abstracts):
            raise SystemExit(
                "no abstracts/ under %s. The benchmark ships relevance judgements but no "
                "text; run experiments/benchmarks/eventkg/fetch_abstracts.py first "
                "(see the corpus README)" % data_root)

        by_person: dict[str, list[dict[str, str]]] = defaultdict(list)
        with open(tsv, encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            header = next(reader, None)
            if not header or tuple(header[:len(COLUMNS)]) != COLUMNS:
                raise SystemExit(
                    "benchmark.tsv header is not the released format.\n  expected: %s\n"
                    "  found:    %s" % (", ".join(COLUMNS), ", ".join(header or [])))
            for parts in reader:
                if len(parts) < len(COLUMNS):
                    continue
                row = dict(zip(COLUMNS, parts))
                by_person[row["entity_label"]].append(row)

        available = {os.path.splitext(f)[0]: os.path.join(abstracts, f)
                     for f in sorted(os.listdir(abstracts)) if f.endswith(".txt")}
        emitted = 0
        for label in sorted(by_person):
            path = available.get(label)
            if path is None:
                continue
            rows = by_person[label]
            positives = [r for r in rows if r["wikipedia_score"].strip() in ("1", "1.0")]
            facts = _dedupe(positives)
            if len([f for f in facts if f.labelled]) < self.min_facts:
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read().strip()
            if not text:
                continue
            transform: list[str] = ["revision_pinned", "wikipedia_abstract"]
            if len(text) > self.max_chars:
                text = text[:self.max_chars]
                transform.append("truncated")
            bio_positives = sum(1 for r in rows
                                if r["biography_score"].strip() in ("1", "1.0"))
            yield BenchmarkDoc(
                doc_id=label,
                slug=slugify(label),
                name=_fold(label).title(),
                text=text,
                gold={"facts": facts,
                      "distractors": _dedupe([r for r in rows
                                              if r["wikipedia_score"].strip()
                                              in ("0", "0.0")])},
                transform=tuple(transform),
                meta={"entity_id": rows[0]["entity_id"],
                      "candidate_rows": len(rows),
                      "wikipedia_positive_rows": len(positives),
                      "biography_positive_rows": bio_positives,
                      "chars": len(text)})
            emitted += 1
            if limit and emitted >= limit:
                return

    # ------------------------------------------------------------- project

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        """Extracted graph -> (name, interval or None) candidates.

        Three places can name a gold entity, and only one of them can date it. An event
        carries `date.sort_start`/`sort_end` and so can earn the strong tier; a relation
        target and an entity name carry no date in biograph's schema and are weak by
        construction. All three are collected because a gold fact this extractor got right
        as an untimed relation is still a fact it got right.
        """
        items: list[dict[str, Any]] = []
        unmapped: list[tuple[str, str, str, str]] = []
        lossy: list[tuple[str, str, str, str]] = []

        for e in extraction.events:
            date = e.get("date") or {}
            start, end = date.get("sort_start"), date.get("sort_end")
            interval = (start, end) if start and end else None
            if interval is None:
                unmapped.append(("event", str(e.get("id", "")),
                                 str(e.get("event_type", "")),
                                 "no sort interval, so it cannot be date-anchored"))
            surface = " ".join(str(e.get(k) or "") for k in ("label", "description"))
            if e.get("location"):
                surface += " " + str(e["location"])
            items.append({"kind": "event", "id": e.get("id"), "surface": surface,
                          "interval": interval})
            # Every projected event loses its type: no gold row carries a biograph event
            # type, and a third of them carry no relation type at all.
            lossy.append(("event", str(e.get("id", "")), str(e.get("event_type", "")),
                          "gold relations are typed in four foreign vocabularies; "
                          "event_type is not compared"))

        names = {str(en.get("id")): str(en.get("name") or "")
                 for en in extraction.entities}
        aliases = {str(en.get("id")): " ".join(str(a) for a in (en.get("aliases") or []))
                   for en in extraction.entities}
        for en in extraction.entities:
            eid = str(en.get("id"))
            items.append({"kind": "entity", "id": eid,
                          "surface": " ".join((names.get(eid, ""), aliases.get(eid, ""),
                                               str(en.get("summary") or ""))),
                          "interval": None})
        for r in extraction.relations:
            target = str(r.get("target") or "")
            surface = " ".join((target, names.get(target, ""), aliases.get(target, "")))
            items.append({"kind": "relation", "id": r.get("id"), "surface": surface,
                          "interval": None})
            lossy.append(("relation", str(r.get("id", "")), str(r.get("type", "")),
                          "relations carry no date in this schema, so a relation match "
                          "cannot reach the date-anchored tier"))

        return Prediction(doc_id=doc.doc_id, items=tuple(items),
                          unmapped=tuple(unmapped), lossy=tuple(lossy),
                          meta={"n_events": len(extraction.events),
                                "n_relations": len(extraction.relations)})

    # --------------------------------------------------------------- score

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]],
              extractions: dict[str, Extraction] | None = None) -> ScoreReport:
        extractions = extractions or {}
        rep = ScoreReport(benchmark=self.name, metric=self.metric)
        rep.not_applicable = {
            "relation_type": ("gold properties span Wikidata, DBpedia and YAGO, and a "
                              "large share of rows are `wikipedia:link`, which carries no "
                              "relation type at all"),
            "event_type": "no gold row carries an event type",
            "precision": ("the 0.0 rows are relations EventKG holds but the abstract does "
                          "not state; an extraction matching one is not demonstrably "
                          "wrong. Reported as distractor_hit_rate instead"),
            "biography_half": ("`biography_score` was derived from Thefamouspeople.com and "
                               "Biography.com texts, which the benchmark does not "
                               "redistribute; those documents cannot be scored"),
        }

        gold_total = gold_labelled = gold_dateable = 0
        weak = strong = 0
        unlabelled = date_unusable = 0
        distractor_total = distractor_hit = 0
        bio_only = 0
        empty_docs = out_of_scope = timed_out = 0
        n_docs = 0

        for doc, pred in pairs:
            n_docs += 1
            ex = extractions.get(doc.doc_id)
            if ex is not None:
                if ex.timed_out:
                    timed_out += 1
                if not ex.in_scope:
                    out_of_scope += 1
                if ex.empty:
                    empty_docs += 1
            bio_only += doc.meta.get("biography_positive_rows", 0)

            facts: list[GoldFact] = list(doc.gold["facts"])
            gold_total += len(facts)
            dated_items = [i for i in pred.items if i["interval"]]

            for fact in facts:
                if not fact.labelled:
                    unlabelled += 1
                    continue
                gold_labelled += 1
                hit = [i for i in pred.items if _name_match(fact.tokens, i["surface"])]
                if not hit:
                    continue
                weak += 1
                if not fact.date_usable:
                    date_unusable += 1
                    continue
                gold_dateable += 1
                if any(_overlaps(fact.interval, i["interval"])
                       for i in dated_items
                       if _name_match(fact.tokens, i["surface"])):
                    strong += 1

            for fact in doc.gold["distractors"]:
                if not fact.labelled:
                    continue
                distractor_total += 1
                if any(_name_match(fact.tokens, i["surface"]) for i in pred.items):
                    distractor_hit += 1

        # gold_dateable counts only facts that were already name-matched, so the
        # date-anchored rate below is conditional on a name match by construction. The
        # unconditional figure a reader wants is strong / gold_labelled, which is
        # reported as `recall_date_anchored`.
        rep.n_docs = n_docs
        rep.scores = {
            "gold_facts_deduplicated": float(gold_total),
            "gold_facts_matchable": float(gold_labelled),
            "recall_name_anchored": (weak / gold_labelled) if gold_labelled else 0.0,
            "recall_date_anchored": (strong / gold_labelled) if gold_labelled else 0.0,
            "date_agreement_given_name_match": ((strong / gold_dateable)
                                                if gold_dateable else 0.0),
            "distractor_hit_rate": ((distractor_hit / distractor_total)
                                    if distractor_total else 0.0),
        }
        rep.attrition = {
            "unlabelled_gold": unlabelled,
            "date_semantics_unusable": date_unusable,
            "distractor_facts": distractor_total,
            "biography_half_rows_unreachable": bio_only,
            "documents_empty": empty_docs,
            "documents_out_of_scope": out_of_scope,
            "documents_timed_out": timed_out,
        }
        rep.notes = [
            "Recall only. The gold's 0.0 rows are unstated-in-abstract, not false, so no "
            "precision is computable; distractor_hit_rate reports the rate at which "
            "extractions land on them.",
            "Gold is deduplicated on (connected entity, interval): the release labels "
            "`actedIn`, `starring` and `P161` separately for one fact.",
            "Date agreement is computed only where the interval is the relation's own "
            "validity. %d name-matched facts carried an interval belonging to the "
            "connected entity instead and were excluded from it." % date_unusable,
            "%d gold facts have no English label and cannot be matched by name; one such "
            "row carries a birth date." % unlabelled,
            "Abstracts are pinned to the last revision before %s, so the text is the text "
            "the judgements were made against." % self.cutoff,
            "The published SVM figures measure relation selection over graph features, "
            "with the graph as input and no biography read. They are not a baseline for "
            "this task and are omitted from published_baseline.",
        ]
        return rep

    # ------------------------------------------------------------ coverage

    def coverage(self) -> dict[str, tuple[str, str]]:
        """Every type is untyped here: the metric never compares a category."""
        from ...harness import vocab
        cells: dict[str, tuple[str, str]] = {}
        note = ("gold properties come from four knowledge graphs and a large share of "
                "rows are untyped `wikipedia:link`; recall is name- and date-anchored")
        for t in vocab.event_types():
            cells["event:" + t] = ("untyped", note)
        for t in vocab.relation_types():
            cells["relation:" + t] = ("untyped", note)
        return cells


ADAPTER = EventKgAdapter()
