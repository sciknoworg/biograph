"""biograph's controlled vocabularies, read from schema/ rather than copied.

The coverage matrix is only trustworthy if it cannot drift from the schema it describes.
So the row labels come from schema/event.schema.json and schema/relation.schema.json at
import time, and coverage.py fails loudly if a benchmark column is missing a row or
names one that does not exist. A type added to the schema shows up as an unmapped row in
the next matrix build instead of quietly vanishing from the paper's table.

Nothing here writes to schema/. It is read-only, by design and by the project's own
constraint.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_DIR = os.path.join(REPO_ROOT, "schema")


@lru_cache(maxsize=None)
def _schema(name: str) -> dict:
    with open(os.path.join(SCHEMA_DIR, f"{name}.schema.json"), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def event_types() -> tuple[str, ...]:
    return tuple(_schema("event")["properties"]["event_type"]["enum"])


@lru_cache(maxsize=None)
def relation_types() -> tuple[str, ...]:
    return tuple(_schema("relation")["properties"]["type"]["enum"])


@lru_cache(maxsize=None)
def entity_types() -> tuple[str, ...]:
    return tuple(_schema("entity")["properties"]["entity_type"]["enum"])


@lru_cache(maxsize=None)
def date_precisions() -> tuple[str, ...]:
    return tuple(_schema("date")["properties"]["precision"]["enum"])


def all_types() -> tuple[str, ...]:
    """Every row of the coverage matrix: events first, then relations, schema order."""
    return tuple(f"event:{t}" for t in event_types()) + \
           tuple(f"relation:{t}" for t in relation_types())


# --------------------------------------------------------------- date helpers
#
# Every event carries a FuzzyDate with sort_start/sort_end, and 66% of the corpus is
# year-precision (measured over subjects/**/events.json at the time of writing). Any
# scorer comparing a biograph date against a day-precision gold must therefore compare
# an INTERVAL against a point, not two strings -- which is what sort_start/sort_end are
# for, per their own schema description ("sort key only, not an assertion of exactness").

def interval(date: dict) -> tuple[str, str]:
    return date["sort_start"], date["sort_end"]


def contains(date: dict, iso_day: str) -> bool:
    """Does this fuzzy date's interval contain the gold day? The correct hit test for a
    year-precision prediction against a day-precision annotation: '1923' predicted for a
    gold '1923-04-17' is right to the precision the source offered, and scoring it as
    wrong would measure the source's vagueness rather than the pipeline's accuracy."""
    lo, hi = interval(date)
    return lo <= iso_day <= hi


def resolution_days(date: dict) -> int:
    """Width of the interval in days -- how much the prediction actually commits to.
    Reported alongside `contains`, so a containment rate achieved by predicting
    'the 1920s' is visibly not the same result as one achieved by predicting a day."""
    from datetime import date as _d
    lo, hi = interval(date)
    try:
        a = _d(*(int(p) for p in lo.split("-")))
        b = _d(*(int(p) for p in hi.split("-")))
    except (TypeError, ValueError):
        return -1
    return (b - a).days + 1
