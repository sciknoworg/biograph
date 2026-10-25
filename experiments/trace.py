#!/usr/bin/env python3
"""Show one worked example per benchmark: source, gold, extraction, verdict.

A score is a claim about thousands of decisions nobody has seen. This prints the four
things a reader needs to check one of those decisions by hand:

    1. the source text, as the pipeline received it
    2. the benchmark's own gold annotation for it
    3. what the unmodified pipeline extracted
    4. how the scorer treated the difference, and under which rule

Nothing here reimplements a scorer. Each trace calls the adapter's own matching helpers --
`_name_match`, `_overlaps`, `_inside`, `_content_tokens`, `_hit`, `label_tokens` -- so an
example cannot drift from the figure it illustrates. To make that guarantee checkable
rather than merely stated, every trace is VERIFIED: the adapter's real score() is run over
the same single document and its counts are compared against the trace's. A mismatch is
printed as a failure and the example is not to be trusted.

Extractions are read from a finished run's cache, so no model is called and nothing is
re-extracted. The corpora are not vendored in this repository; --data-root must point at a
local copy, exactly as the harness itself requires.

    python -m experiments.trace --benchmark wikibio
    python -m experiments.trace --benchmark wikibio --doc 8108
    python -m experiments.trace --all
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap

from .harness.cli import get_adapter
from .harness.interface import Extraction, GroundingReport

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

#: Which finished run supplies the cached extractions for each benchmark, and the corpus
#: and flags that run was made with. Taken from each report.json's own `invocation`, so a
#: trace is of the run the paper reports and not of some other configuration.
RUNS = {
    "biographical": {"run": "b1_gold_64k", "root": "experiments/corpora/biographical",
                     "args": {"min_facts": 1, "b1_order": "balanced"}},
    "bioevents": {"run": "b2_rich_64k", "root": "experiments/corpora/bioevents",
                  "args": {"min_triggers": 1, "order": "richness"}},
    "wikilife": {"run": "b3_wikilife_64k", "root": "experiments/corpora/wikilife",
                 "args": {}},
    "wikibio": {"run": "b4_wikibio_64k", "root": "experiments/corpora/wikibio",
                "args": {"min_events": 1}},
    "eventkg": {"run": "b5_eventkg_full", "root": "experiments/corpora/eventkg",
                "args": {"min_facts": 10, "ekg_cutoff": "2019-05-21",
                         "ekg_order": "richness"}},
}

DEFAULTS = {"min_facts": 1, "min_triggers": 1, "min_events": 1, "order": "extractable",
            "b1_order": "balanced", "ekg_order": "richness", "ekg_cutoff": "2019-05-21"}


class _Args:
    def __init__(self, **kw):
        for k, v in {**DEFAULTS, **kw}.items():
            setattr(self, k, v)


# ------------------------------------------------------------------ plumbing


def load_cache(run: str) -> dict[str, Extraction]:
    """Every cached extraction in a finished run, keyed by the benchmark's own doc_id.

    The harness keys its cache by a hash of the document, model, core and budget, which is
    right for deciding whether a result may be reused and useless for looking one up by
    name. Each file records its own doc_id, so the directory is indexed by that instead.
    """
    out: dict[str, Extraction] = {}
    cdir = os.path.join(HERE, "runs", run, "cache")
    if not os.path.isdir(cdir):
        raise SystemExit("no cache at %s -- was this run made with --run-id %s?"
                         % (os.path.relpath(cdir, REPO_ROOT), run))
    for name in sorted(os.listdir(cdir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(cdir, name), encoding="utf-8") as f:
            raw = json.load(f)
        doc_id = str(raw.pop("doc_id"))
        g = raw.pop("grounding", None)
        ex = Extraction(doc_id=doc_id,
                        **{k: (tuple(v) if isinstance(v, list) else v)
                           for k, v in raw.items()})
        if g:
            ex = Extraction(**{**ex.__dict__,
                               "grounding": GroundingReport(
                                   **{**g, "issues": tuple(g.get("issues", ()))})})
        out[doc_id] = ex
    return out


def excerpt(text: str, start: int, end: int, pad: int = 160) -> str:
    """The source around a span, with the span itself marked with >> <<."""
    a, b = max(0, start - pad), min(len(text), end + pad)
    head = ("..." if a > 0 else "") + text[a:start]
    tail = text[end:b] + ("..." if b < len(text) else "")
    return (head + ">>" + text[start:end] + "<<" + tail).replace("\n", " ")


def wrap(s: str, indent: str = "      ", width: int = 92) -> str:
    return textwrap.fill(" ".join(str(s).split()), width=width,
                         initial_indent=indent, subsequent_indent=indent)


def head(n: int, title: str) -> None:
    print("\n" + "-" * 94)
    print("%d. %s" % (n, title))
    print("-" * 94)


def verify(label: str, traced: dict, scored: dict) -> None:
    """The trace must agree with the real scorer on this document, or say so loudly."""
    bad = [k for k, v in traced.items() if scored.get(k) != v]
    if bad:
        print("\n  !! TRACE DISAGREES WITH score() on %s: %s" % (label, ", ".join(bad)))
        for k in bad:
            print("       %-28s trace=%s  score()=%s" % (k, traced[k], scored.get(k)))
        print("     Treat this example as unverified.")
    else:
        print("\n  verified against the adapter's own score() on this document: %s"
              % ", ".join("%s=%s" % (k, v) for k, v in traced.items()))


# ------------------------------------------------------------------ 4. wikibio


def trace_wikibio(adapter, doc, ex, pred) -> None:
    from .benchmarks.wikibio.adapter import _content_tokens, _fold

    gold = doc.gold["triggers"]
    mentions = doc.gold["subject_mentions"]
    events = [dict(e) for e in pred.items]
    for e in events:
        e["about_subject"] = any(s <= m["start"] and m["end"] <= en
                                 for s, en in e["spans"] for m in mentions)

    used, verdicts, strong, weak = set(), [], 0, 0
    for trig in gold:
        token = _fold(trig["surface"])
        best = None
        for tier, want_label in (("label+quote", True), ("quote", False)):
            for idx, e in enumerate(events):
                if idx in used or not adapter._inside(trig["start"], trig["end"],
                                                      e["spans"]):
                    continue
                if want_label and not (_content_tokens(token) & e["label_tokens"]):
                    continue
                best = (idx, tier)
                break
            if best:
                break
        if best:
            used.add(best[0])
            strong += best[1] == "label+quote"
            weak += best[1] == "quote"
        verdicts.append((trig, best))

    hits = [(t, b) for t, b in verdicts if b]
    misses = [t for t, b in verdicts if not b]

    head(4, "WikiBio (benchmark 4) -- trigger-anchored event recall")
    print("  document %s, %s  (%d chars, %d gold triggers, %d extracted events)"
          % (doc.doc_id, doc.name, len(doc.text), len(gold), len(events)))

    print("\n  A GOLD TRIGGER THE PIPELINE RECALLED")
    trig, (idx, tier) = hits[0]
    e = events[idx]
    print("\n    source, trigger marked:")
    print(wrap(excerpt(doc.text, trig["start"], trig["end"])))
    print("\n    gold annotation:")
    print(wrap("label %s, surface %r at [%d, %d) -- the corpus asserts that an event "
               "occurred here and nothing about which kind"
               % (trig["label"], trig["surface"], trig["start"], trig["end"])))
    print("\n    BioGraph extracted:")
    print(wrap("event %s of type %r, labelled from tokens %s, evidence quote spanning %s"
               % (e["id"], e["type"], sorted(e["label_tokens"])[:8], e["spans"][:2])))
    print("\n    the scorer's verdict: RECALLED on the %s tier." % tier)
    print(wrap("The trigger span falls inside one of the event's evidence quotes%s. The "
               "event's own type (%r) is never compared, because the gold EVENT class is "
               "untyped -- all 22 biograph types collapse onto it -- so every extracted "
               "event is additionally recorded in `lossy` for that reason."
               % (" AND the trigger word appears in the event's own label, which is what "
                  "separates the strong tier from the weak one" if tier == "label+quote"
                  else ", but the trigger word does NOT appear in the event's label, so "
                       "this is the weak anchor: any event quoting that sentence could "
                       "have answered for any trigger in it", e["type"])))

    if misses:
        print("\n  A GOLD TRIGGER THE PIPELINE MISSED")
        m = misses[0]
        print("\n    source, trigger marked:")
        print(wrap(excerpt(doc.text, m["start"], m["end"])))
        print("\n    gold annotation:")
        print(wrap("label %s, surface %r at [%d, %d)"
                   % (m["label"], m["surface"], m["start"], m["end"])))
        print("\n    BioGraph extracted: nothing whose evidence quote covers this span.")
        print("\n    the scorer's verdict: MISSED, counted in the recall denominator.")
        print(wrap("No unused extracted event has a quote containing [%d, %d). This is a "
                   "genuine recall failure and is not excused."
                   % (m["start"], m["end"])))

    others = [e for e in events if not e["about_subject"]]
    if others:
        print("\n  AN EXTRACTION THE SCORER REFUSED TO PENALISE")
        o = others[0]
        print(wrap("event %s, type %r, quote at %s -- no quote span of this event covers "
                   "any of the %d gold ENTITY mentions of %s, so the scorer classes it as "
                   "an event about SOMEONE ELSE."
                   % (o["id"], o["type"], o["spans"][:1], len(mentions), doc.name)))
        print("\n    the scorer's verdict: EXCLUDED from precision, not counted as a "
              "false positive.")
        print(wrap("The annotation is exhaustive for the target person and silent about "
                   "everyone else, so an unmatched event about a colleague is correct "
                   "extraction with no gold to match. Counting it against precision would "
                   "punish the extractor for reading the parts of the document the "
                   "annotators ignored. %d of %d extracted events are excluded this way, "
                   "and precision is reported as "
                   "trigger_precision_over_subject_events for that reason."
                   % (len(others), len(events))))

    unmapped = [u for u in pred.unmapped]
    if unmapped:
        print("\n  AN EXTRACTION THAT COULD NOT ENTER THE LABEL SPACE AT ALL")
        k, eid, etype, why = unmapped[0]
        print(wrap("%s %s of type %r: %s" % (k, eid, etype, why)))
        print(wrap("Recorded in `unmapped` (%d this document) rather than dropped, so "
                   "taxonomy loss is a measured quantity." % len(unmapped)))

    rep = adapter.score([(doc, pred)], {doc.doc_id: ex})
    verify("wikibio", {"gold_recalled": len(hits), "gold_triggers": len(gold),
                       "anchored_by_label_and_quote": strong,
                       "anchored_by_quote_only": weak}, rep.scores)


# ------------------------------------------------------------------ 3. wikilife


def trace_wikilife(adapter, doc, ex, pred) -> None:
    from .benchmarks.wikilife.adapter import PRONOUNS, _fold, _name_match, _overlaps

    gold = list(doc.gold)
    items = list(pred.items)
    hits, misses, unanchorable = [], [], []
    for fact in gold:
        if fact.get("interval") is None:
            unanchorable.append(fact)
            continue
        want = fact["person"]
        if _fold(want) in PRONOUNS:
            want = doc.name
        found, near = None, None
        for idx, it in enumerate(items):
            p_ok = _name_match(want, it["person"])
            l_ok = _name_match(fact["location"], it["place"])
            t_ok = _overlaps(fact["interval"], it["interval"])
            if p_ok and l_ok and t_ok:
                found = idx
                break
            if near is None and sum((p_ok, l_ok, t_ok)) == 2:
                near = (idx, p_ok, l_ok, t_ok)
        if found is not None:
            hits.append((fact, found))
        else:
            misses.append((fact, near))

    head(3, "WikiLifeTrajectory (benchmark 3) -- person+place+time recall")
    print("  document %s  (%d chars, %d gold facts, %d scorable, %d projected triples)"
          % (doc.doc_id, len(doc.text), len(gold), len(gold) - len(unanchorable),
             len(items)))

    if hits:
        print("\n  A GOLD TRAJECTORY FACT THE PIPELINE RECALLED")
        fact, idx = hits[0]
        it = items[idx]
        where = doc.text.find(fact["location"])
        if where >= 0:
            print("\n    source, place mention marked:")
            print(wrap(excerpt(doc.text, where, where + len(fact["location"]))))
        print("\n    gold annotation:")
        print(wrap("person %r, time %r, location %r -> interval %s"
                   % (fact["person"], fact["time"], fact["location"], fact["interval"])))
        print("\n    BioGraph extracted:")
        print(wrap("from event %s: person %r, place %r, interval %s"
                   % (it["id"], it["person"], it["place"], it["interval"])))
        print("\n    the scorer's verdict: RECALLED.")
        print(wrap("All three parts matched at once -- name match on the person, name "
                   "match on the place, and the intervals overlap. A trajectory fact needs "
                   "all three simultaneously, and an event is where biograph holds them "
                   "together: the date on the event, the place in `location`, the people "
                   "in `participants`."))

    if misses:
        print("\n  A GOLD FACT THE PIPELINE MISSED, AND WHICH PART FAILED")
        fact, near = misses[0]
        print("\n    gold annotation:")
        print(wrap("person %r, time %r, location %r -> interval %s"
                   % (fact["person"], fact["time"], fact["location"], fact["interval"])))
        if near:
            idx, p_ok, l_ok, t_ok = near
            it = items[idx]
            got = [n for n, ok in (("person", p_ok), ("place", l_ok), ("time", t_ok)) if ok]
            lost = [n for n, ok in (("person", p_ok), ("place", l_ok), ("time", t_ok))
                    if not ok]
            print("\n    the closest BioGraph triple:")
            print(wrap("event %s: person %r, place %r, interval %s"
                       % (it["id"], it["person"], it["place"], it["interval"])))
            print("\n    the scorer's verdict: MISSED, recorded as a near miss on %s."
                  % " and ".join(got))
            print(wrap("The scorer got %s right and %s wrong, and counts the near miss in "
                       "`partial` so the report can say WHICH of the three parts the "
                       "extractor got wrong rather than only that it failed."
                       % (" and ".join(got), " and ".join(lost))))
        else:
            print("\n    the scorer's verdict: MISSED, with no near miss on any two parts.")

    if unanchorable:
        print("\n  A GOLD FACT THE SCORER REFUSED TO COUNT AS A MISS")
        f = unanchorable[0]
        print(wrap("person %r, location %r, time %r -- the time expression cannot be "
                   "placed on a timeline by any system, so it is counted apart and kept "
                   "OUT of the recall denominator rather than scored as a failure. %d of "
                   "%d gold facts in this document are excluded this way."
                   % (f["person"], f["location"], f["time"], len(unanchorable), len(gold))))

    print("\n  AN EXTRACTION WITH NO GOLD TO MATCH")
    matched = {items[i]["id"] for _f, i in hits}
    spare = [it for it in items if it["id"] not in matched]
    if spare:
        it = spare[0]
        print(wrap("event %s: person %r, place %r, interval %s -- matches no gold fact."
                   % (it["id"], it["person"], it["place"], it["interval"])))
    print("\n    the scorer's verdict: counted as unmatched_prediction, NOT as a false "
          "positive.")
    print(wrap("Every gold fact in this partition is positive; there are no negatives. The "
               "annotators' unit is the trajectory, not the life, so an extracted fact "
               "absent from gold may be perfectly true and simply unannotated. This "
               "benchmark is therefore recall-only and reports no precision at all."))

    rep = adapter.score([(doc, pred)], {doc.doc_id: ex})
    verify("wikilife", {"gold_recalled": len(hits),
                        "gold_scorable": len(gold) - len(unanchorable),
                        "predictions": len(items)}, rep.scores)


# ------------------------------------------------------------------ 5. eventkg


def trace_eventkg(adapter, doc, ex, pred) -> None:
    from .benchmarks.eventkg.adapter import _name_match, _overlaps

    facts = list(doc.gold["facts"])
    items = list(pred.items)
    dated = [i for i in items if i["interval"]]
    weak = strong = labelled = unlabelled = date_unusable = 0
    weak_eg = strong_eg = miss_eg = unlab_eg = None
    for fact in facts:
        if not fact.labelled:
            unlabelled += 1
            unlab_eg = unlab_eg or fact
            continue
        labelled += 1
        hit = [i for i in items if _name_match(fact.tokens, i["surface"])]
        if not hit:
            miss_eg = miss_eg or fact
            continue
        weak += 1
        if not fact.date_usable:
            date_unusable += 1
            weak_eg = weak_eg or (fact, hit[0])
            continue
        if any(_overlaps(fact.interval, i["interval"]) for i in dated
               if _name_match(fact.tokens, i["surface"])):
            strong += 1
            strong_eg = strong_eg or (fact, hit[0])
        else:
            weak_eg = weak_eg or (fact, hit[0])

    dist = [f for f in doc.gold["distractors"] if f.labelled]
    dist_hit = [f for f in dist if any(_name_match(f.tokens, i["surface"]) for i in items)]

    head(5, "EventKG (benchmark 5) -- two-tier recall over a knowledge graph")
    print("  document %s  (%d-char Wikipedia abstract, %d gold facts after dedup, "
          "%d matchable, %d projected mentions)"
          % (doc.doc_id, len(doc.text), len(facts), labelled, len(items)))

    if strong_eg:
        fact, it = strong_eg
        print("\n  A GOLD FACT RECALLED ON THE DATE-ANCHORED (STRONG) TIER")
        print("\n    gold annotation:")
        print(wrap("connected entity %r, validity interval %s, properties %s"
                   % (fact.label, fact.interval, sorted(fact.properties)[:2])))
        w = doc.text.find(it["surface"][:40])
        if w >= 0:
            print("\n    source, matched mention marked:")
            print(wrap(excerpt(doc.text, w, w + len(it["surface"][:40]))))
        print("\n    BioGraph extracted:")
        print(wrap("mention %r with interval %s" % (it["surface"], it["interval"])))
        print("\n    the scorer's verdict: RECALLED, date-anchored.")
        print(wrap("Every distinctive token of the gold label is present in the extracted "
                   "surface form, AND an extracted interval overlaps the gold validity "
                   "interval. Relation type is never compared: gold properties span "
                   "Wikidata, DBpedia and YAGO and a large share of rows are "
                   "`wikipedia:link`, which carries no relation type at all."))

    if weak_eg:
        fact, it = weak_eg
        print("\n  A GOLD FACT THAT REACHED ONLY THE NAME-ANCHORED (WEAK) TIER")
        print("\n    gold annotation:")
        print(wrap("connected entity %r, interval %s%s"
                   % (fact.label, fact.interval,
                      "" if fact.date_usable else
                      " -- but this interval is NOT the relation's own validity")))
        print("\n    BioGraph extracted:")
        print(wrap("mention %r with interval %s" % (it["surface"], it["interval"])))
        print("\n    the scorer's verdict: counted in recall_name_anchored, NOT in "
              "recall_date_anchored.")
        print(wrap("The name matched but the date did not agree%s. The two tiers are "
                   "reported separately because collapsing them would let a name match "
                   "stand in for a dated fact."
                   % (", and the gold interval belongs to the connected entity (a "
                      "lifespan, say) rather than to the relation, so date agreement is "
                      "not even askable here and the fact is excluded from the date "
                      "denominator instead of failed"
                      if not fact.date_usable else "")))

    if miss_eg:
        print("\n  A GOLD FACT THE PIPELINE MISSED")
        print(wrap("connected entity %r, interval %s -- no extracted mention contains "
                   "every distinctive token of this label."
                   % (miss_eg.label, miss_eg.interval)))
        print("\n    the scorer's verdict: MISSED, in the recall denominator.")

    if unlab_eg:
        print("\n  A GOLD FACT THE SCORER CANNOT MATCH IN EITHER DIRECTION")
        print(wrap("connected entity id %r carries no label in the release, so there is "
                   "nothing to match a surface form against. %d of %d facts here are "
                   "unlabelled; they are reported in attrition and excluded from the "
                   "matchable denominator rather than counted as misses."
                   % (unlab_eg.entity_id, unlabelled, len(facts))))

    print("\n  THE DISTRACTOR SET, AND WHY THERE IS NO PRECISION")
    print(wrap("%d labelled distractor facts -- relations EventKG holds for this person "
               "that the abstract does not state. %d of them were hit by an extraction. "
               "A hit is NOT scored as a false positive: the abstract not stating a "
               "relation does not make it false, so no precision is computable and the "
               "rate is reported as distractor_hit_rate instead."
               % (len(dist), len(dist_hit))))

    rep = adapter.score([(doc, pred)], {doc.doc_id: ex})
    verify("eventkg",
           {"gold_facts_matchable": float(labelled),
            "recall_name_anchored": (weak / labelled) if labelled else 0.0,
            "recall_date_anchored": (strong / labelled) if labelled else 0.0},
           rep.scores)


# ------------------------------------------------------------------ 1. biographical


def trace_biographical(adapter, doc, ex, pred) -> None:
    from collections import defaultdict

    from .benchmarks.biographical.adapter import FAMILY, SCORED

    by_label = defaultdict(list)
    for label, value in pred.items:
        by_label[label].append(value)

    used, hits, misses = set(), [], []
    for rel, obj in [(r, o) for r, o in doc.gold if r in SCORED]:
        candidates = FAMILY if rel in FAMILY else (rel,)
        found = None
        for cand in candidates:
            for i, value in enumerate(by_label.get(cand, [])):
                if (cand, i) in used:
                    continue
                if adapter._hit(rel, obj, value):
                    found = (cand, i)
                    break
            if found:
                break
        if not found and rel in FAMILY:
            for i, value in enumerate(by_label.get("family", [])):
                if ("family", i) not in used and adapter._hit(rel, obj, value):
                    found = ("family", i)
                    break
        if found:
            used.add(found)
            hits.append((rel, obj, found))
        else:
            misses.append((rel, obj))

    spare = [(l, i, v) for l, vs in by_label.items() for i, v in enumerate(vs)
             if (l, i) not in used and (l in SCORED or l == "family")]

    head(1, "BiographicalEvents / Biographical (benchmark 1) -- per-label P/R/F1")
    print("  document %s, %s  (%d chars, %d scored gold facts, %d projected labels)"
          % (doc.doc_id, doc.name, len(doc.text),
             len([1 for r, _o in doc.gold if r in SCORED]), len(pred.items)))
    print("\n    source (the whole pseudo-document; sentences are grouped by person):")
    print(wrap(doc.text))

    if hits:
        rel, obj, (cand, i) = hits[0]
        print("\n  A GOLD FACT THE PIPELINE RECALLED")
        print("\n    gold annotation:   %s = %r" % (rel, obj))
        print("    BioGraph projected: %s = %s"
              % (cand, json.dumps(by_label[cand][i], ensure_ascii=False)[:160]))
        print("\n    the scorer's verdict: TRUE POSITIVE for %s." % rel)
        if rel in ("birthdate", "deathdate"):
            print(wrap("Dates are matched by INTERVAL CONTAINMENT, not string equality: a "
                       "year-precision prediction against a day-precision gold is right to "
                       "the precision the source offered. The gold day is tested for "
                       "membership in the predicted interval."))
        elif rel in FAMILY:
            print(wrap("A family gold label matches any recovered family prediction. The "
                       "schema has only `family_of` and cannot distinguish parent, child "
                       "and sibling, so crediting only the exact subtype would score the "
                       "same collapse twice -- once as a miss here and once as `lossy`."))
        else:
            print(wrap("String match after case and accent folding."))

    if misses:
        rel, obj = misses[0]
        print("\n  A GOLD FACT THE PIPELINE MISSED")
        print("\n    gold annotation:   %s = %r" % (rel, obj))
        print("    BioGraph projected for that label: %s"
              % (json.dumps(by_label.get(rel, []), ensure_ascii=False)[:200] or "nothing"))
        print("\n    the scorer's verdict: FALSE NEGATIVE for %s, in the recall "
              "denominator." % rel)

    if spare:
        l, i, v = spare[0]
        print("\n  AN EXTRACTION COUNTED AGAINST PRECISION")
        print(wrap("projected %s = %s, matching no gold fact -> FALSE POSITIVE."
                   % (l, json.dumps(v, ensure_ascii=False)[:140])))
        print(wrap("Unlike benchmarks 3 and 5, this corpus IS scored for precision, so an "
                   "unmatched prediction is an error here. That is why micro_precision "
                   "(%s) sits so far below micro_recall across the run: the pipeline "
                   "extracts a fuller graph than the gold annotates."
                   % "0.3838 over the full 400"))

    if pred.unmapped:
        print("\n  AN EXTRACTION WITH NO HOME IN THIS LABEL SPACE")
        k, i_, t, why = pred.unmapped[0]
        print(wrap("%s %s (%s): %s" % (k, i_, t, why)))

    na = adapter.score([(doc, pred)], {doc.doc_id: ex})
    print("\n  LABELS REPORTED AS NOT APPLICABLE RATHER THAN ZERO")
    for label, why in list(na.not_applicable.items())[:2]:
        print(wrap("%s -- %s" % (label, why)))
    print(wrap("Scoring these as 0 would understate the pipeline by averaging in a label "
               "it was never asked to produce; scoring them at all would claim a "
               "capability the data model does not have. They are excluded from every "
               "macro-average and named."))

    rep = na
    traced_tp = len(hits)
    traced_fp = len(spare)
    traced_fn = len(misses)
    verify("biographical",
           {"micro_recall": round(traced_tp / (traced_tp + traced_fn), 4)
                            if (traced_tp + traced_fn) else 0.0,
            "micro_precision": round(traced_tp / (traced_tp + traced_fp), 4)
                               if (traced_tp + traced_fp) else 0.0},
           rep.scores)


# ------------------------------------------------------------------ 2. bioevents


def trace_bioevents(adapter, doc, ex, pred) -> None:
    from .benchmarks.bioevents.adapter import UNREACHABLE, _content_tokens, _fold

    triggers = doc.gold["triggers"]
    annotated = doc.gold["annotated_spans"]
    events = [v for k, v in pred.items if k == "trigger"]

    used, verdicts, tiers = set(), [], {"label+quote": 0, "quote": 0}
    for trig in triggers:
        token = _fold(trig["surface"])
        best = None
        for tier, want_label in (("label+quote", True), ("quote", False)):
            for idx, e in enumerate(events):
                if idx in used or not adapter._inside(trig["start"], trig["end"],
                                                      e["spans"]):
                    continue
                if want_label and not (_content_tokens(token) & e["label_tokens"]):
                    continue
                best = (idx, tier)
                break
            if best:
                break
        if best:
            used.add(best[0])
            tiers[best[1]] += 1
        verdicts.append((trig, best))

    hits = [(t, b) for t, b in verdicts if b]
    states = [(t, b) for t, b in verdicts if t["label"] == "STATE"]
    misses = [t for t, b in verdicts if not b]
    outside = [e for e in events
               if not (e["spans"] and adapter._overlaps(min(s for s, _ in e["spans"]),
                                                        max(x for _, x in e["spans"]),
                                                        annotated))]

    head(2, "BiographicalEvents / BioEvents (benchmark 2) -- TimeML trigger recall")
    print("  document %s, %s  (%d chars, %d gold triggers, %d extracted events)"
          % (doc.doc_id, doc.name, len(doc.text), len(triggers), len(events)))

    if hits:
        trig, (idx, tier) = hits[0]
        e = events[idx]
        print("\n  A GOLD TRIGGER THE PIPELINE RECALLED")
        print("\n    source, trigger marked:")
        print(wrap(excerpt(doc.text, trig["start"], trig["end"])))
        print("\n    gold annotation:")
        print(wrap("TimeML class %s, surface %r at [%d, %d)"
                   % (trig["label"], trig["surface"], trig["start"], trig["end"])))
        print("\n    BioGraph extracted:")
        print(wrap("an event labelled from tokens %s, evidence span %s"
                   % (sorted(e["label_tokens"])[:8], e["spans"][:2])))
        print("\n    the scorer's verdict: RECALLED on the %s tier." % tier)
        print(wrap("All 22 biograph event types collapse onto TimeML's single EVENT class, "
                   "so matching is trigger-anchored and the gold class is used only to "
                   "bucket recall afterwards. The type is never compared."))

    state_hits = [(t, b) for t, b in states if b]
    if state_hits:
        trig, (idx, tier) = state_hits[0]
        e = events[idx]
        print("\n  A GOLD **STATE** TRIGGER, THE INTERESTING CASE")
        print("\n    source, trigger marked:")
        print(wrap(excerpt(doc.text, trig["start"], trig["end"])))
        print("\n    gold annotation: TimeML STATE, surface %r -- a static condition, not "
              "an occurrence." % trig["surface"])
        print("\n    BioGraph extracted: an event labelled from tokens %s (%s tier)"
              % (sorted(e["label_tokens"])[:8], tier))
        print("\n    the scorer's verdict: RECALLED, but STATE is reported as NOT "
              "APPLICABLE and excluded from macro_recall.")
        print(wrap("Excluded because no biograph type targets STATE, NOT because it is "
                   "unreachable -- it measures 0.366 recall over 186 gold triggers across "
                   "the run. The two schemas disagree about ASPECT rather than coverage: "
                   "TimeML annotates the ongoing condition, biograph records the dated "
                   "transition into it, and one sentence licenses both readings. What "
                   "biograph genuinely cannot represent is an UNDATED static condition."))

    if misses:
        m = misses[0]
        print("\n  A GOLD TRIGGER THE PIPELINE MISSED")
        print("\n    source, trigger marked:")
        print(wrap(excerpt(doc.text, m["start"], m["end"])))
        print(wrap("gold class %s, surface %r -- no unused extracted event has an evidence "
                   "span containing [%d, %d)."
                   % (m["label"], m["surface"], m["start"], m["end"])))
        print("\n    the scorer's verdict: MISSED, in the recall denominator.")

    if outside:
        print("\n  AN EXTRACTION OUTSIDE THE ANNOTATED REGION")
        print(wrap("an event whose evidence span overlaps none of the %d annotated "
                   "sentences %s. The corpus annotates only part of each document."
                   % (len(annotated), annotated[:3])))
        print("\n    the scorer's verdict: EXCLUDED from precision (`unscorable_span`).")
        print(wrap("No annotated sentence covers it, so no gold could confirm or deny it. "
                   "Counting it against precision would penalise the extractor for reading "
                   "text the annotators did not label. %d of %d extracted events here."
                   % (len(outside), len(events))))

    # trigger_recall excludes UNREACHABLE classes -- STATE -- from BOTH the numerator and
    # the denominator, not only from the macro average. Verifying against len(triggers)
    # disagreed with score() by exactly the STATE triggers, which is how this was found.
    scored_gold = [t for t in triggers if t["label"] not in UNREACHABLE]
    scored_hits = [t for t, b in verdicts if b and t["label"] not in UNREACHABLE]
    print()
    print("  WHAT ENTERS trigger_recall")
    print(wrap("%d of the %d gold triggers here are STATE and are excluded from the "
               "headline trigger_recall on both sides of the division, so it is %d/%d and "
               "not %d/%d. STATE recall is reported separately in per_label and in the "
               "report's notes."
               % (len(triggers) - len(scored_gold), len(triggers), len(scored_hits),
                  len(scored_gold), len(hits), len(triggers))))

    rep = adapter.score([(doc, pred)], {doc.doc_id: ex})
    verify("bioevents",
           {"trigger_recall": round(len(scored_hits) / len(scored_gold), 4)
                              if scored_gold else 0.0,
            "anchored_by_label_and_quote": tiers["label+quote"],
            "anchored_by_quote_only": tiers["quote"]}, rep.scores)


TRACES = {"biographical": trace_biographical, "bioevents": trace_bioevents,
          "wikilife": trace_wikilife, "wikibio": trace_wikibio,
          "eventkg": trace_eventkg}
ORDER = ["biographical", "bioevents", "wikilife", "wikibio", "eventkg"]


def pick(adapter, docs, cache, name):
    """A document with both a hit and a miss, so the example shows the scorer deciding.

    Deterministic: the first such document in the adapter's own load order, falling back
    to the first cached one when no document has both.
    """
    best = None
    for doc in docs:
        ex = cache.get(str(doc.doc_id))
        if ex is None:
            continue
        pred = adapter.project(doc, ex)
        if best is None:
            best = (doc, ex, pred)
        rep = adapter.score([(doc, pred)], {doc.doc_id: ex})
        s = rep.scores
        if name in ("wikibio", "bioevents"):
            got = s.get("gold_recalled", s.get("trigger_recall", 0))
            tot = s.get("gold_triggers", 1)
            if got and (s.get("trigger_recall", 1) < 1.0):
                return doc, ex, pred
        elif name == "wikilife":
            if s.get("gold_recalled") and s["gold_recalled"] < s.get("gold_scorable", 0):
                return doc, ex, pred
        elif name == "eventkg":
            if 0 < s.get("recall_name_anchored", 0) < 1:
                return doc, ex, pred
        elif name == "biographical":
            if 0 < s.get("micro_recall", 0) < 1:
                return doc, ex, pred
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--benchmark", choices=ORDER)
    ap.add_argument("--all", action="store_true", help="one example from each benchmark")
    ap.add_argument("--doc", help="a specific benchmark doc_id instead of a chosen one")
    args = ap.parse_args(argv)
    if not args.benchmark and not args.all:
        ap.error("pass --benchmark NAME or --all")

    names = ORDER if args.all else [args.benchmark]
    print("WORKED EXAMPLES FROM THE FIVE BENCHMARKS")
    print("\nExtractions are read from the finished runs' caches; no model is called.")
    print("Every verdict below is computed with the adapter's own matching helpers and")
    print("checked against that adapter's real score() on the same single document.")

    for name in names:
        cfg = RUNS[name]
        root = os.path.join(REPO_ROOT, cfg["root"])
        if not os.path.isdir(root):
            print("\n  %s: corpus not present at %s -- skipped (corpora are not "
                  "vendored)." % (name, cfg["root"]))
            continue
        adapter = get_adapter(name, _Args(**cfg["args"]))
        cache = load_cache(cfg["run"])
        docs = list(adapter.load(root))
        if args.doc:
            docs = [d for d in docs if str(d.doc_id) == str(args.doc)]
            if not docs:
                print("\n  %s: no document with id %r" % (name, args.doc))
                continue
        chosen = pick(adapter, docs, cache, name)
        if chosen is None:
            print("\n  %s: no cached extraction for any loaded document." % name)
            continue
        doc, ex, pred = chosen
        TRACES[name](adapter, doc, ex, pred)
        rp = os.path.join(HERE, "runs", cfg["run"], "report.json")
        meta = json.load(open(rp, encoding="utf-8")) if os.path.isfile(rp) else {}
        print()
        print("  source: run %s, model %s, core commit %s"
              % (cfg["run"], (meta.get("model") or {}).get("model", "?"),
                 (meta.get("core") or {}).get("commit", "?")[:7]))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
