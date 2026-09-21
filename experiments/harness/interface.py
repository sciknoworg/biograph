"""The contract every benchmark adapter implements.

Five external benchmarks are scored against one extraction pipeline that none of them
were designed for. The pipeline is not modified for any of them -- scripts/build_site.py
runs byte-identically (see sandbox.py, which proves it by hash) and everything
benchmark-specific lives on either side of it:

    benchmark's native format  -> [input adapter] -> .txt -> [build_site.py --text] ->
    entities/events/relations/sources.json -> [output adapter] -> benchmark's label
    space -> [scorer] -> the benchmark's own published metric

Three data classes carry the work across those arrows, and one Protocol names the four
methods an adapter must supply.

Two design decisions are load-bearing, because the honesty of the paper rests on them:

Prediction.unmapped -- every extracted item the output adapter could NOT express in the
benchmark's label space is recorded, not silently dropped. Taxonomy loss is then a
measured per-run quantity rather than a sentence in a limitations section.

ScoreReport.not_applicable -- benchmark labels the schema cannot represent at all
(Biographical's `occupation` has no typed home in biograph) are reported as N/A and
excluded from macro-averages. Scoring them as 0 would understate the pipeline by
averaging in a label it was never asked to produce; scoring them at all would claim a
capability the data model does not have. Neither is defensible, so they are named.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable

# --------------------------------------------------------------- input side


@dataclass(frozen=True)
class BenchmarkDoc:
    """One unit of work: whatever the benchmark calls a document, rendered as text.

    `text` is exactly what build_site.py --text will read and what --check-grounding
    will later verify quotes against, so any framing or anchoring the input adapter
    adds (see pmoa_tts for both) is part of it and is disclosed in `transform`.
    """

    doc_id: str                 # the benchmark's own id, kept verbatim for joins
    slug: str                   # must match ^[a-z][a-z0-9_]*$ -- build_site.py exits otherwise
    name: str                   # --name; the person the document is about
    text: str                   # written to <sandbox>/data/, passed as --text
    gold: Any                   # the benchmark's own annotation, untouched
    transform: tuple[str, ...] = ()   # input transformations applied, for the writeup
    meta: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------- pipeline side


@dataclass(frozen=True)
class GroundingReport:
    """Output of build_site.py --check-grounding, parsed. Never reimplemented here."""

    quotes_checked: int
    quotes_verbatim: int
    entities_checked: int
    entities_present: int
    issues: tuple[str, ...] = ()

    @property
    def quote_rate(self) -> float | None:
        return self.quotes_verbatim / self.quotes_checked if self.quotes_checked else None

    @property
    def entity_rate(self) -> float | None:
        return self.entities_present / self.entities_checked if self.entities_checked else None


@dataclass(frozen=True)
class Extraction:
    """What the unmodified pipeline produced for one BenchmarkDoc.

    `scope` is the verdict from --scope-out, captured for every document including the
    rejected ones. SCOPE_DEFINITION is in the prompt whether or not --strict-scope is
    passed, so a document the project considers out of scope yields no graph at all --
    and for corpora outside the biographical-essay genre that is a result, not an error.
    It is counted, never silently skipped.
    """

    doc_id: str
    slug: str
    subject: dict[str, Any] | None = None
    entities: tuple[dict[str, Any], ...] = ()
    events: tuple[dict[str, Any], ...] = ()
    relations: tuple[dict[str, Any], ...] = ()
    sources: tuple[dict[str, Any], ...] = ()
    scope: dict[str, Any] | None = None          # {"fits", "reason", "subject_name"}
    grounding: GroundingReport | None = None
    exit_code: int = 0
    wall_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""

    @property
    def in_scope(self) -> bool:
        return not (self.scope and self.scope.get("fits") is False)

    @property
    def empty(self) -> bool:
        return not (self.events or self.relations)

    def events_sorted(self) -> list[dict[str, Any]]:
        """events.json in the same order build_site.py's build() renders the timeline in
        -- the ordering TLEX is asked to check."""
        return sorted(self.events,
                      key=lambda e: (e["date"]["sort_start"], e["date"]["sort_end"]))


# --------------------------------------------------------------- output side


@dataclass(frozen=True)
class Prediction:
    """One document's extraction, projected into the benchmark's label space."""

    doc_id: str
    items: tuple[Any, ...] = ()
    #: (kind, id, type, why) for each extracted item with no target in this label space.
    #: Counted and reported per run; this is where taxonomy loss becomes a number.
    unmapped: tuple[tuple[str, str, str, str], ...] = ()
    #: Projections that succeeded but lost information (a three-way collapse onto
    #: family_of, a year-precision date scored against a day-precision gold).
    lossy: tuple[tuple[str, str, str, str], ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreReport:
    benchmark: str
    metric: str                                  # the benchmark's own, named
    scores: dict[str, float] = field(default_factory=dict)
    published_baseline: dict[str, float] = field(default_factory=dict)
    #: label -> why it cannot be scored. Excluded from every macro-average below.
    not_applicable: dict[str, str] = field(default_factory=dict)
    per_label: dict[str, dict[str, float]] = field(default_factory=dict)
    #: documents the scope gate refused, documents that produced nothing, etc.
    attrition: dict[str, int] = field(default_factory=dict)
    n_docs: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "benchmark": self.benchmark, "metric": self.metric, "n_docs": self.n_docs,
            "scores": self.scores, "published_baseline": self.published_baseline,
            "not_applicable": self.not_applicable, "per_label": self.per_label,
            "attrition": self.attrition, "notes": self.notes,
        }


# --------------------------------------------------------------- the adapter


@runtime_checkable
class BenchmarkAdapter(Protocol):
    """Four methods and a citation block. Nothing here may import build_site."""

    name: str                       # "pmoa_tts"
    citation: str                   # arXiv id / ACL anthology id
    license: str                    # as published, or "UNRESOLVED -- see README"
    label_space: tuple[str, ...]    # the benchmark's own labels, ("<untyped>",) if none
    metric: str                     # the benchmark's own metric, named
    published_baseline: dict[str, float]

    def load(self, data_root: str, limit: int | None = None) -> Iterable[BenchmarkDoc]:
        """Input adapter: the benchmark's native files -> text build_site.py can read."""

    def project(self, doc: BenchmarkDoc, extraction: Extraction) -> Prediction:
        """Output adapter: biograph's fixed vocabulary -> this benchmark's label space."""

    def score(self, pairs: Iterable[tuple[BenchmarkDoc, Prediction]]) -> ScoreReport:
        """Scorer: the benchmark's published metric, not a new one."""

    def coverage(self) -> dict[str, tuple[str, str]]:
        """This benchmark's column of the vocabulary coverage matrix:
        biograph type -> (cell, note). See harness/coverage.py for the cell vocabulary."""
