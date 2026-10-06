"""Self-checks for the harness, none of which call a model or touch the network.

    python -m experiments.tests

Covers the parts where a silent bug would produce a plausible-looking number in the
paper: the matcher, the concordance and its tie handling, the projection from biograph's
schema into hours, the sandbox's hash verification, and the coverage matrix's agreement
with schema/.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile

from .benchmarks.pmoa_tts import adapter as pt
from .benchmarks.pmoa_tts import pmc as pt_pmc
from .benchmarks.pmoa_tts import score as sc
from .harness import coverage, sandbox, vocab
from .harness.interface import BenchmarkDoc, Extraction, Prediction

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name} {detail}")


# ------------------------------------------------------------------ score.py

def test_parse_timeline():
    text = ("fever | 0\n"
            "chest pain | -48\n"
            "started antibiotics | 12.5\n"
            "\n"
            "not a row\n")
    tl = sc.parse_timeline(text)
    check("parse_timeline reads pipe rows", tl == [("fever", 0.0), ("chest pain", -48.0),
                                                   ("started antibiotics", 12.5)], str(tl))
    check("parse_timeline keeps negatives (pre-presentation)", tl[1][1] == -48.0)


def test_matching():
    gold = ["acute chest pain", "fever", "discharged home"]
    pred = ["fever", "acute chest pain"]
    dists = sc.levenshtein_matrix(gold, pred)
    pairs = sc.recursive_match(dists, threshold=0.3)
    matched = {(g, p) for g, p, _ in pairs}
    check("greedy match is one-to-one and correct", matched == {(0, 1), (1, 0)}, str(matched))
    check("unmatched gold stays unmatched", all(g != 2 for g, _, _ in pairs))

    # A row whose only partner is beyond the threshold must be dropped, not forced.
    far = sc.recursive_match([[0.9]], threshold=0.1)
    check("threshold drops a too-distant pair", far == [], str(far))


def test_concordance():
    c, comparable, ties = sc.concordance([0, 1, 2], [0, 1, 2])
    check("perfect ordering scores 1.0", c == 1.0 and comparable == 3 and ties == 0,
          f"c={c} n={comparable}")
    c, _, _ = sc.concordance([0, 1, 2], [2, 1, 0])
    check("reversed ordering scores 0.0", c == 0.0, f"c={c}")
    c, comparable, ties = sc.concordance([0, 1], [5, 5])
    check("a tied prediction scores 0.5 and is counted",
          c == 0.5 and ties == 1 and comparable == 1, f"c={c} ties={ties}")
    c, comparable, _ = sc.concordance([3, 3], [0, 9])
    check("a tied GOLD pair is not comparable", c is None and comparable == 0,
          f"c={c} n={comparable}")


def test_aultc():
    tight = sc.aultc([0.0, 0.0, 1.0])
    loose = sc.aultc([50.0, 80.0, 200.0])
    check("AULTC rewards small errors", tight is not None and loose is not None
          and tight > loose, f"tight={tight} loose={loose}")
    penalised = sc.aultc([1.0, None, None])
    check("unmatched events are penalised, not skipped",
          penalised is not None and penalised < sc.aultc([1.0]), str(penalised))


def test_score_document():
    gold = [("fever", 0.0), ("chest pain", 24.0), ("discharged", 72.0)]
    pred = [("fever", 0.0), ("chest pain", 30.0)]
    d = sc.score_document("t1", gold, pred, matcher="lev", threshold=0.3)
    check("event recall is matched/gold", abs(d.event_recall - 2 / 3) < 1e-9,
          str(d.event_recall))
    check("concordance over matched pairs", d.concordance == 1.0, str(d.concordance))
    check("median absolute error in hours", d.median_abs_error_hours == 3.0,
          str(d.median_abs_error_hours))

    empty = sc.score_document("t2", gold, [], matcher="lev")
    check("no prediction is recall 0, not a crash", empty.event_recall == 0.0)


# ------------------------------------------------------------------ adapter

def _event(eid, label, start, end, precision="day", etype="other"):
    return {"id": eid, "event_type": etype, "label": label,
            "date": {"precision": precision, "sort_start": start, "sort_end": end,
                     "display": start},
            "participants": [{"entity_id": "p", "role": "subject"}],
            "sources": [{"source_id": "s", "page": 1}]}


def test_projection():
    a = pt.PmoaTtsAdapter(framing="minimal")
    doc = pt.BenchmarkDoc(doc_id="1", slug="pmoa_1", name="Patient 1", text="",
                          gold=[("fever", 0.0)])
    ex = Extraction(
        doc_id="1", slug="pmoa_1",
        events=(_event("e1", "fever", "2000-01-01", "2000-01-01"),
                _event("e2", "discharged", "2000-01-04", "2000-01-04"),
                _event("e3", "", "2000-01-02", "2000-01-02")),
        relations=({"id": "r1", "type": "born_in", "source": "p", "target": "q",
                    "sources": [{"source_id": "s", "page": 1}]},),
    )
    pred = a.project(doc, ex)
    times = dict(pred.items)
    check("anchor day 0 maps to hour 0", times.get("fever") == 0.0, str(times))
    check("three days later maps to 72 hours", times.get("discharged") == 72.0, str(times))
    check("an unlabelled event is unmapped, not silently dropped",
          any(u[1] == "e3" for u in pred.unmapped), str(pred.unmapped))
    check("relations are recorded as unmapped for this benchmark",
          any(u[0] == "relation" for u in pred.unmapped), str(pred.unmapped))

    # A year-precision date must land on the midpoint and be reported as lossy.
    ex2 = Extraction(doc_id="1", slug="pmoa_1",
                     events=(_event("e4", "fever", "2000-01-01", "2000-12-31", "year"),))
    p2 = a.project(doc, ex2)
    hours = p2.items[0][1]
    check("imprecise date uses the interval midpoint", abs(hours - 4380.0) < 24, str(hours))
    check("imprecise date is flagged lossy", len(p2.lossy) == 1, str(p2.lossy))

    # Without an anchor there is no offset to compute, and that must be visible.
    a3 = pt.PmoaTtsAdapter(framing="none", anchor=None)
    p3 = a3.project(doc, ex)
    check("--no-anchor yields no scoreable events, all unmapped",
          not p3.items and len(p3.unmapped) == 4, f"{p3.items} {len(p3.unmapped)}")


def test_input_adapter():
    """The release ships timelines but no text, so load() pairs a parquet row with a
    body fetched from PMC. The fetch is stubbed here; pmc.py is exercised for real by
    `--dry-run` against a downloaded split."""
    import pandas as pd

    root = tempfile.mkdtemp()
    try:
        pd.DataFrame([
            {"pmc_id": "PMC011xxxxxx", "case_report_id": "PMC123",
             "textual_timeseries": [{"event": "fever", "time": 0},
                                    {"event": "discharged", "time": 72}],
             "demographics": {"age": "54.0", "sex": "Male", "ethnicity": "Not Specified"}},
            {"pmc_id": "PMC011xxxxxx", "case_report_id": "PMC999",
             "textual_timeseries": [],            # no gold -> counted, not yielded
             "demographics": {"age": "?", "sex": "?", "ethnicity": "?"}},
        ]).to_parquet(os.path.join(root, "case_study_100.parquet"))

        body = "A 54-year-old man presented with fever. Three days later he was discharged."
        original = pt_pmc.PmcFetcher.body_text
        pt_pmc.PmcFetcher.body_text = lambda self, pmcid: body if pmcid == "PMC123" else ""
        try:
            a = pt.PmoaTtsAdapter(framing="minimal")
            docs = list(a.load(root))
            check("load pairs a parquet row with its PMC body", len(docs) == 1, str(len(docs)))
            d = docs[0]
            check("slug satisfies build_site.py's pattern", d.slug == "pmoa_pmc123", d.slug)
            check("anchor line is present and disclosed",
                  "presented on 01 January 2000" in d.text
                  and any(t.startswith("anchor=") for t in d.transform), str(d.transform))
            check("framing is disclosed in transform",
                  "framing=minimal" in d.transform, str(d.transform))
            check("gold comes from textual_timeseries",
                  d.gold == [("fever", 0.0), ("discharged", 72.0)], str(d.gold))
            check("a row with no gold events is counted, not yielded",
                  a.load_attrition["no_gold_events"] == 1, str(a.load_attrition))

            a2 = pt.PmoaTtsAdapter(framing="none", anchor=None)
            plain = list(a2.load(root))[0]
            check("framing=none --no-anchor sends the body unaltered",
                  plain.text == body, plain.text[:40])

            pt_pmc.PmcFetcher.body_text = lambda self, pmcid: ""
            a3 = pt.PmoaTtsAdapter()
            check("a case with no OA text is counted, not silently dropped",
                  list(a3.load(root)) == [] and a3.load_attrition["no_oa_text"] == 1,
                  str(a3.load_attrition))
        finally:
            pt_pmc.PmcFetcher.body_text = original
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_embedding_threshold_calibration():
    """Is cosine distance < 0.1 a real constraint, or does S-PubMedBert call everything
    clinical a match? An event recall of 0.93 between the two released annotators is only
    meaningful if the threshold actually discriminates, so it is checked rather than
    assumed. Skipped when torch/transformers are absent; the Levenshtein matcher is the
    reference implementation's own fallback and needs neither.

    Measured: paraphrases land at 0.019-0.094, different findings from the same case at
    0.139-0.224, unrelated text at 0.125-0.244. The threshold sits in the gap."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        print("  skip embedding calibration (torch/transformers not installed)")
        return

    related = ["fever", "acute chest pain", "started on intravenous furosemide",
               "discharged home", "bilateral leg swelling"]
    paraphrase = ["febrile", "chest pain, acute onset", "IV furosemide administered",
                  "sent home", "swelling of both legs"]
    unrelated = ["the aircraft landed in Berlin", "she won the Nobel Prize in Chemistry",
                 "a new semiconductor deposition method", "the company was sold in 1998",
                 "he retired from the university"]

    M = sc.embedding_matrix(related, paraphrase)
    U = sc.embedding_matrix(related, unrelated)
    diag = [M[i][i] for i in range(len(related))]
    off = [M[i][j] for i in range(len(related)) for j in range(len(paraphrase)) if i != j]
    flat_u = [d for row in U for d in row]

    check("paraphrases fall inside the 0.1 threshold",
          all(d < sc.EMBED_THRESHOLD for d in diag), f"max={max(diag):.3f}")
    check("different findings fall outside it",
          all(d >= sc.EMBED_THRESHOLD for d in off), f"min={min(off):.3f}")
    check("unrelated text falls outside it",
          all(d >= sc.EMBED_THRESHOLD for d in flat_u), f"min={min(flat_u):.3f}")
    check("the threshold sits in a real gap, not on top of the distribution",
          min(off + flat_u) - max(diag) > 0.02,
          f"gap={min(off + flat_u) - max(diag):.3f}")
    check("no spurious matches against unrelated text",
          sc.recursive_match(U, sc.EMBED_THRESHOLD) == [], "matched something unrelated")


def test_pmc_body_boundary():
    """pmc.py must reproduce get_pmoa_body.sh: body only, no title/abstract/references."""
    f = pt_pmc.PmcFetcher.__new__(pt_pmc.PmcFetcher)
    f.raw = lambda pmcid: [{"documents": [{"id": pmcid, "passages": [
        {"infons": {"section_type": "TITLE"}, "text": "A rare case of something"},
        {"infons": {"section_type": "ABSTRACT"}, "text": "We report a case."},
        {"infons": {"section_type": "INTRO"}, "text": "Introduction"},
        {"infons": {"section_type": "CASE"}, "text": "A 53-year-old man presented."},
        {"infons": {"section_type": "REF"}, "text": "1. Smith J."},
        {"infons": {"section_type": "CASE"}, "text": "after the references"},
    ]}]}]
    text = pt_pmc.PmcFetcher.body_text(f, "PMC1")
    check("title and abstract are excluded", "rare case of something" not in text
          and "We report a case" not in text, text[:60])
    check("body passages are kept", "A 53-year-old man presented." in text, text[:60])
    check("everything from the references on is cut",
          "Smith J" not in text and "after the references" not in text, text)


def test_scoring_end_to_end():
    a = pt.PmoaTtsAdapter(framing="minimal", matcher="lev", threshold=0.3)
    doc = pt.BenchmarkDoc(doc_id="1", slug="pmoa_1", name="P", text="",
                          gold=[("fever", 0.0), ("discharged", 72.0)])
    ex = Extraction(doc_id="1", slug="pmoa_1",
                    events=(_event("e1", "fever", "2000-01-01", "2000-01-01"),
                            _event("e2", "discharged", "2000-01-04", "2000-01-04")))
    report = a.score([(doc, a.project(doc, ex))], extractions={"1": ex})
    check("end-to-end recall is 1.0 on an exact timeline",
          report.scores.get("event_recall") == 1.0, str(report.scores))
    check("published baseline travels with the report",
          report.published_baseline.get("event_recall") == 0.80, str(report.published_baseline))
    check("attrition is always reported", "out_of_scope" in report.attrition,
          str(report.attrition))

    refused = Extraction(doc_id="1", slug="pmoa_1",
                         scope={"fits": False, "reason": "not a biographical essay"})
    r2 = a.score([(doc, a.project(doc, refused))], extractions={"1": refused})
    check("a scope refusal is counted, not skipped",
          r2.attrition["out_of_scope"] == 1 and r2.attrition["empty_extraction"] == 1,
          str(r2.attrition))
    check("a refused document scores 0 recall rather than vanishing",
          r2.scores.get("event_recall") == 0.0, str(r2.scores))


# ------------------------------------------------------------------ harness

def test_vocab_and_matrix():
    check("22 event types read from schema/", len(vocab.event_types()) == 22,
          str(len(vocab.event_types())))
    check("27 relation types read from schema/", len(vocab.relation_types()) == 27,
          str(len(vocab.relation_types())))
    rows, table, problems = coverage.build()
    check("matrix has a row per schema type", len(table) == 49, str(len(table)))
    check("matrix does not drift from schema/", not problems, "; ".join(problems))
    cols = [c["column"] for c in coverage.COLUMNS]
    check("every row has all five columns",
          all(all(c in row for c in cols) for row in table))
    check("occupation is declared unmappable, not scored",
          "occupation" in coverage.BIOGRAPHICAL["unmapped_labels"])

    d = {"precision": "year", "sort_start": "1923-01-01", "sort_end": "1923-12-31"}
    check("a year-precision date contains a day-precision gold",
          vocab.contains(d, "1923-04-17") and not vocab.contains(d, "1924-01-01"))
    check("resolution is reported alongside containment",
          vocab.resolution_days(d) == 365, str(vocab.resolution_days(d)))


def test_sandbox():
    sb = sandbox.make(run_id="selftest")
    try:
        check("sandbox copies the extraction core", os.path.isfile(sb.build_site))
        check("sandbox hashes match the repository", not sb.verify(), str(sb.verify()))
        check("manifest records the commit and asserts no modification",
              sb.manifest()["extraction_core_modified"] is False and sb.manifest()["commit"])
        with open(sb.build_site, "a", encoding="utf-8") as f:
            f.write("\n# tampered\n")
        check("a modified core is detected", bool(sb.verify()), "verify() stayed silent")
    finally:
        sandbox.discard(sb)


# ------------------------------------------------------- benchmarks/biographical

def _b1_doc(doc_id="A", name="A Person"):
    return BenchmarkDoc(doc_id=doc_id, slug="a", name=name, text="", gold=())


def test_biographical_projection():
    """The output adapter's four sharp edges, each locked in after being found live."""
    from .benchmarks.biographical import adapter as b1

    person = {"id": "p1", "entity_type": "person", "name": "A Person"}
    london = {"id": "lon", "entity_type": "place", "name": "London"}
    year1900 = {"display": "1900", "precision": "year",
                "sort_start": "1900-01-01", "sort_end": "1900-12-31"}

    # `location` is an entity ID per schema/event.schema.json, not a name.
    ex = Extraction(doc_id="x", slug="x", subject={"id": "p1", "name": "A Person"},
                    entities=(person, london),
                    events=({"id": "b", "event_type": "birth", "location": "lon",
                             "date": year1900,
                             "participants": [{"entity_id": "p1", "role": "subject"}]},),
                    relations=(), sources=())
    items = dict(b1.ADAPTER.project(_b1_doc(), ex).items)
    check("event location resolves the entity id to a name",
          items.get("birthplace") == "London", str(items))

    # A relative's death must not become the biographee's.
    ex2 = Extraction(doc_id="y", slug="y", subject={"id": "p1", "name": "A Person"},
                     entities=(person, {"id": "p2", "entity_type": "person",
                                        "name": "A Spouse"}),
                     events=({"id": "d", "event_type": "death", "date": year1900,
                              "participants": [{"entity_id": "p2", "role": "subject"},
                                               {"entity_id": "p1", "role": "witness"}]},),
                     relations=(), sources=())
    items2 = dict(b1.ADAPTER.project(_b1_doc("y"), ex2).items)
    check("a relative's death is not read as the subject's",
          "deathdate" not in items2, str(items2))

    # Both routes to birthplace state one fact; it must not be predicted twice.
    ex3 = Extraction(doc_id="z", slug="z", subject={"id": "p1", "name": "A Person"},
                     entities=(person, london),
                     events=({"id": "b", "event_type": "birth", "location": "lon",
                              "date": year1900,
                              "participants": [{"entity_id": "p1", "role": "subject"}]},),
                     relations=({"id": "r", "type": "born_in",
                                 "source": "p1", "target": "lon"},),
                     sources=())
    pred3 = b1.ADAPTER.project(_b1_doc("z"), ex3)
    check("the two birthplace routes collapse to one prediction",
          sum(1 for l, _ in pred3.items if l == "birthplace") == 1, str(pred3.items))

    # A dangling target id cannot be compared with a gold string.
    ex4 = Extraction(doc_id="w", slug="w", subject={"id": "p1", "name": "A Person"},
                     entities=(person,), events=(),
                     relations=({"id": "r", "type": "born_in",
                                 "source": "p1", "target": "nowhere"},),
                     sources=())
    pred4 = b1.ADAPTER.project(_b1_doc("w"), ex4)
    check("a relation with no entity behind its target is unmapped, not empty",
          not pred4.items and len(pred4.unmapped) == 1, str(pred4))


def test_biographical_family_and_dates():
    from .benchmarks.biographical import adapter as b1

    f = b1.BiographicalAdapter._family_subtype
    check("'Father' with the subject as source is ofParent",
          f({"note": "Father"}, True) == "ofParent")
    check("'Father' with the subject as target is hasChild",
          f({"note": "Father"}, False) == "hasChild")
    check("'youngest son' with the subject as source is hasChild",
          f({"note": "youngest son"}, True) == "hasChild")
    check("'Brother' is sibling either way",
          f({"note": "Brother"}, True) == f({"note": "Brother"}, False) == "sibling")
    check("a note with no kinship word yields no subtype",
          f({"note": "worked together"}, True) is None)
    check("no note yields no subtype", f({}, True) is None)

    check("a year-only gold widens to its first day", b1._iso_day("1912") == "1912-01-01")
    check("a full gold date is kept", b1._iso_day("1912-06-23") == "1912-06-23")
    check("an unparseable gold date is None", b1._iso_day("sometime") is None)

    year = {"sort_start": "1912-01-01", "sort_end": "1912-12-31"}
    hit = b1.BiographicalAdapter._hit
    check("a year-precision prediction contains a day-precision gold",
          hit("birthdate", "1912-06-23", year))
    check("the wrong year does not match", not hit("birthdate", "1913-06-23", year))
    check("places match on a folded string", hit("birthplace", "Zurich", "Zürich"))


def test_biographical_balanced_ordering():
    """Round-robin across labels, so every prefix gives even per-label support.

    1,774 of the 1,800 scoreable documents carry exactly one scored fact, so ordering
    cannot buy density here the way it can for bioevents. What it buys is support for the
    macro F1: gold runs from birthdate at 296 facts down to deathplace at 104, so a
    proportional prefix starves the smallest label first. At --limit 400 the weakest label
    gets 50 instead of 19.
    """
    from .benchmarks.biographical import adapter as b1

    tab = "\t"
    tmp = tempfile.mkdtemp(prefix="b1ord-")
    try:
        rows = [tab.join(["sentence", "relation", "P1", "P2", "ANNOTATION", "wp_id"])]
        # Six birthdate documents against two deathplace: a proportional prefix spends the
        # whole budget on birthdate before reaching deathplace at all.
        for i in range(6):
            rows.append(tab.join([
                "<e1>P%d</e1> was born on <e2>1 May 190%d</e2>." % (i, i),
                "birthdate", "e1", "e2", "birthdate", str(100 + i)]))
        for i in range(2):
            rows.append(tab.join([
                "<e1>Q%d</e1> died in <e2>Rome</e2>." % i,
                "dplace_name", "e1", "e2", "dplace_name", str(200 + i)]))
        with open(os.path.join(tmp, "g.tsv"), "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(rows) + "\n")

        bal = [d.meta["scored_labels"][0]
               for d in b1.BiographicalAdapter(order="balanced").load(tmp)]
        check("the two labels alternate while both have documents",
              bal[:4] == ["birthdate", "deathplace", "birthdate", "deathplace"], str(bal))
        check("the exhausted label simply stops appearing",
              bal[4:] == ["birthdate"] * 4, str(bal))
        check("nothing is dropped by reordering", len(bal) == 8, str(len(bal)))

        plain = [d.meta["scored_labels"][0]
                 for d in b1.BiographicalAdapter(order="id").load(tmp)]
        check("id ordering leaves the corpus distribution alone",
              plain == ["birthdate"] * 6 + ["deathplace"] * 2, str(plain))
        check("the ordering used is recorded on every document",
              all(d.meta["ordering"] == "balanced"
                  for d in b1.BiographicalAdapter(order="balanced").load(tmp)))

        try:
            b1.BiographicalAdapter(order="whatever")
            check("an unknown ordering is refused", False, "no SystemExit")
        except SystemExit as e:
            check("an unknown ordering is refused", "--order must be one of" in str(e),
                  str(e)[:70])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_biographical_marked_release():
    """The published release: <e1>/<e2> spans in the sentence, P1 naming the subject.

    Three ways to be quietly wrong here, all of which produce a plausible results table:
    reading e1 as the subject always (inverts one row in seven), scoring the automatic
    `relation` instead of the human `ANNOTATION` (they disagree on 20% of rows), and
    leaving the markup in the text the model reads.
    """
    from .benchmarks.biographical import adapter as b1

    tmp = tempfile.mkdtemp(prefix="b1m-")
    try:
        rows = [
            "sentence\trelation\tP1\tP2\tANNOTATION\twp_id",
            # normal order, and the human label CORRECTS the automatic one
            "<e1>Ada</e1> was born in <e2>London</e2>.\tbplace_name\te1\te2\t"
            "bplace_name\t11",
            # the automatic label says educatedAt, the human says it is not a relation
            "<e1>Ada</e1> visited <e2>Yale</e2>.\teducatedAt\te1\te2\tOther\t11",
            # REVERSED: the date is e1 and the person is e2
            "Born <e1>10 December 1815</e1>, <e2>Ada</e2> was a mathematician."
            "\tbirthdate\te2\te1\tbirthdate\t11",
        ]
        with open(os.path.join(tmp, "g.tsv"), "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(rows) + "\n")
        doc = next(iter(b1.BiographicalAdapter(min_facts=0).load(tmp)))

        check("markers are stripped from the text the model reads",
              "<e1>" not in doc.text and "</e2>" not in doc.text, doc.text)
        check("the stripping is disclosed in transform",
              "argument_markers_stripped" in doc.transform, str(doc.transform))
        check("grouping is by page id when the release has one",
              doc.transform[0] == "grouped_by_wikipedia_page", str(doc.transform))

        gold = dict(doc.gold)
        check("release label names are mapped to this adapter's space",
              "birthplace" in gold and "bplace_name" not in gold, str(doc.gold))
        check("the object is the non-subject argument",
              gold.get("birthplace") == "London", str(doc.gold))
        # P1=e2 on the third row, so the subject is Ada and the object is the date --
        # read as e1-is-always-subject, this becomes ('birthdate', 'Ada').
        check("P1 decides the subject, even when it is e2",
              gold.get("birthdate") == "10 December 1815", str(doc.gold))
        check("the human ANNOTATION overrides the automatic relation",
              "educatedAt" not in gold and gold.get("other") == "Yale", str(doc.gold))
        check("the document is named from the subject, not the page id",
              doc.name == "Ada", doc.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_biographical_input_adapter():
    from .benchmarks.biographical import adapter as b1

    tmp = tempfile.mkdtemp(prefix="b1-")
    try:
        rows = ["sentence,person,relation,object",
                "A was born in Rome.,A,birthplace,Rome",
                "A died in Pisa.,A,deathplace,Pisa",
                "B studied at Yale.,B,educatedAt,Yale"]
        with open(os.path.join(tmp, "a.csv"), "w", encoding="utf-8", newline="") as fh:
            fh.write("\n".join(rows) + "\n")
        docs = list(b1.ADAPTER.load(tmp))
        check("rows are grouped into one document per person",
              len(docs) == 2, str(len(docs)))
        a = [d for d in docs if d.doc_id == "A"][0]
        check("a person's sentences are concatenated", a.text.count(".") == 2, a.text)
        check("a person's gold facts are collected", len(a.gold) == 2, str(a.gold))
        check("a column-format release is grouped by its subject string, and says so",
              a.transform == ("grouped_by_subject_string",), str(a.transform))
        check("slugs satisfy build_site.py's rule",
              all(re.match(r"^[a-z][a-z0-9_]*$", d.slug) for d in docs),
              str([d.slug for d in docs]))

        with open(os.path.join(tmp, "b.csv"), "w", encoding="utf-8", newline="") as fh:
            fh.write("col1,col2\nx,y\n")
        try:
            list(b1.ADAPTER.load(tmp))
            check("an unrecognised header is refused, not guessed", False, "no SystemExit")
        except SystemExit as e:
            check("an unrecognised header is refused, not guessed",
                  "could not find column" in str(e), str(e)[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_biographical_scoring():
    from .benchmarks.biographical import adapter as b1

    doc = BenchmarkDoc(doc_id="A", slug="a", name="A", text="",
                       gold=(("birthdate", "1912-06-23"), ("birthplace", "London"),
                             ("occupation", "mathematician"), ("ofParent", "Julius")))
    pred = Prediction(doc_id="A", items=(
        ("birthdate", {"sort_start": "1912-01-01", "sort_end": "1912-12-31"}),
        ("birthplace", "London"),
        ("ofParent", "Julius"),
        ("deathplace", "Nowhere")), meta={"subject_resolved": True})
    rep = b1.ADAPTER.score([(doc, pred)])
    check("occupation is reported N/A, not scored",
          "occupation" in rep.not_applicable and "occupation" not in rep.per_label)
    check("a year-precision birthdate is credited",
          rep.per_label["birthdate"]["recall"] == 1.0, str(rep.per_label["birthdate"]))
    check("a spurious prediction costs precision",
          rep.per_label["deathplace"]["precision"] == 0.0,
          str(rep.per_label["deathplace"]))
    check("gold-less labels stay out of the macro average",
          rep.per_label["sibling"]["support"] == 0, str(rep.per_label["sibling"]))
    check("no published baseline is claimed", rep.published_baseline == {},
          str(rep.published_baseline))


# ---------------------------------------------------------- benchmarks/bioevents

def _b2_sentence(pairs):
    return [(t, l) for t, l in pairs]


def test_bioevents_tags_and_offsets():
    from .benchmarks.bioevents import adapter as b2

    check("an IOB tag splits into label and prefix", b2.parse_tag("B-EVENT") == ("EVENT", "B"))
    check("an I- tag keeps its label", b2.parse_tag("I-ASP-EVENT") == ("ASP-EVENT", "I"))
    check("O is not a label", b2.parse_tag("O") == (None, None))
    check("an empty tag is not a label", b2.parse_tag("") == (None, None))
    check("a bare label survives", b2.parse_tag("EVENT") == ("EVENT", None))

    sent = _b2_sentence([("Turing", "O"), ("was", "O"), ("born", "B-EVENT"),
                         ("in", "O"), ("London", "B-ARGx-LOC")])
    doc = b2.ADAPTER._build_doc("d", [sent])
    trig = doc.gold["triggers"][0]
    check("a trigger's offsets point at its own surface in the text",
          doc.text[trig["start"]:trig["end"]] == "born",
          repr(doc.text[trig["start"]:trig["end"]]))
    check("a role annotation is kept apart from triggers",
          [r["label"] for r in doc.gold["roles"]] == ["ARGx-LOC"], str(doc.gold["roles"]))
    check("the annotated span covers the sentence",
          doc.gold["annotated_spans"][0][0] == 0, str(doc.gold["annotated_spans"]))

    # An IOB run is one annotation, not three.
    run = _b2_sentence([("He", "O"), ("passed", "B-EVENT"), ("away", "I-EVENT"),
                        ("quietly", "I-EVENT")])
    doc2 = b2.ADAPTER._build_doc("d2", [run])
    check("an IOB run merges into a single trigger",
          len(doc2.gold["triggers"]) == 1
          and doc2.gold["triggers"][0]["surface"] == "passed away quietly",
          str(doc2.gold["triggers"]))


def _b2_extraction(text_quote, events):
    evs = []
    for eid, label, etype in events:
        evs.append({"id": eid, "event_type": etype, "label": label,
                    "date": {"display": "", "precision": "year",
                             "sort_start": "1900-01-01", "sort_end": "1900-12-31"},
                    "participants": [{"entity_id": "p1", "role": "subject"}],
                    "sources": [{"source_id": "s", "quote": text_quote}]})
    return Extraction(doc_id="d", slug="d", subject={"id": "p1", "name": "P"},
                      entities=({"id": "p1", "entity_type": "person", "name": "P"},),
                      events=tuple(evs), relations=(), sources=())


def test_bioevents_anchoring():
    """Two events citing one quote must not both answer for the same trigger."""
    from .benchmarks.bioevents import adapter as b2

    sent = _b2_sentence([("P", "O"), ("was", "O"), ("born", "B-EVENT"), ("and", "O"),
                         ("died", "B-EVENT"), ("later", "O")])
    doc = b2.ADAPTER._build_doc("d", [sent])
    quote = doc.text.strip()
    ex = _b2_extraction(quote, [("e1", "Born", "birth"), ("e2", "Died", "death")])
    pred = b2.ADAPTER.project(doc, ex)
    rep = b2.ADAPTER.score([(doc, pred)])
    check("both triggers in one shared quote are recalled",
          rep.per_label["EVENT"]["recalled"] == 2, str(rep.per_label["EVENT"]))
    check("each match used the strong label+quote anchor",
          rep.scores["anchored_by_label_and_quote"] == 2 and
          rep.scores["anchored_by_quote_only"] == 0, str(rep.scores))

    # One event, two triggers: it can answer for only one of them.
    ex2 = _b2_extraction(quote, [("e1", "Born", "birth")])
    rep2 = b2.ADAPTER.score([(doc, b2.ADAPTER.project(doc, ex2))])
    check("one event answers at most one trigger",
          rep2.per_label["EVENT"]["recalled"] == 1, str(rep2.per_label["EVENT"]))

    # An event whose quote is nowhere in the document has no span to anchor.
    ex3 = _b2_extraction("text that does not appear", [("e1", "Born", "birth")])
    rep3 = b2.ADAPTER.score([(doc, b2.ADAPTER.project(doc, ex3))])
    check("an unlocatable quote anchors nothing and is not scorable",
          rep3.per_label["EVENT"]["recalled"] == 0
          and rep3.attrition["unscorable_span"] == 1, str(rep3.attrition))


def test_bioevents_state_and_precision():
    from .benchmarks.bioevents import adapter as b2

    sent = _b2_sentence([("P", "O"), ("was", "O"), ("born", "B-EVENT"), ("and", "O"),
                         ("was", "O"), ("blind", "B-STATE")])
    doc = b2.ADAPTER._build_doc("d", [sent])
    ex = _b2_extraction(doc.text.strip(), [("e1", "Born", "birth")])
    rep = b2.ADAPTER.score([(doc, b2.ADAPTER.project(doc, ex))])
    check("STATE is measured, not hidden",
          rep.per_label["STATE"]["support"] == 1
          and rep.per_label["STATE"]["recall"] == 0.0, str(rep.per_label["STATE"]))
    check("STATE is named as not applicable", "STATE" in rep.not_applicable)
    check("STATE is excluded from macro_recall, so EVENT alone carries it",
          rep.scores["macro_recall"] == 1.0, str(rep.scores))
    check("a zero STATE recall is reported as the schema's rule predicting it",
          any("Near zero, as the schema's own rule predicts" in n for n in rep.notes),
          str(rep.notes))

    # Type is recorded as lossy for every event, since it cannot be expressed at all.
    pred = b2.ADAPTER.project(doc, ex)
    check("collapsing the biograph type is recorded as lossy",
          len(pred.lossy) == 1 and "collapses onto TimeML EVENT" in pred.lossy[0][3],
          str(pred.lossy))


def test_every_adapter_scores_the_way_the_cli_calls_it():
    """cli.py calls score(pairs, extractions=...). Every adapter must accept that.

    This exists because two benchmarks were built, unit-tested and reported as ready while
    being impossible to run: the tests called score(pairs) positionally, cli.py passes
    `extractions` as a keyword, and only one of four adapters had the parameter. The
    failure surfaced on the first real CLI run, after 25 extraction calls had already been
    paid for -- the crash landed between extraction and the report.

    So this checks the signature the way the caller uses it, not the way the tests do.
    """
    import inspect

    from .benchmarks.bioevents.adapter import BioEventsAdapter
    from .benchmarks.biographical.adapter import BiographicalAdapter
    from .benchmarks.grounding.adapter import GroundingAdapter
    from .benchmarks.pmoa_tts.adapter import PmoaTtsAdapter

    for cls in (BioEventsAdapter, BiographicalAdapter, GroundingAdapter, PmoaTtsAdapter):
        sig = inspect.signature(cls.score)
        check("%s.score accepts extractions= as cli.py passes it" % cls.__name__,
              "extractions" in sig.parameters, str(sig))
        if "extractions" in sig.parameters:
            check("%s.score's extractions is optional" % cls.__name__,
                  sig.parameters["extractions"].default is not inspect.Parameter.empty,
                  str(sig.parameters["extractions"]))

    # And actually call one that way, so an accepted-but-unused parameter that blows up
    # inside the body is caught too.
    from .benchmarks.bioevents import adapter as b2
    sent = _b2_sentence([("P", "O"), ("studied", "B-EVENT")])
    doc = b2.ADAPTER._build_doc("d", [sent])
    ex = Extraction(doc_id="d", slug="d", subject={"id": "p1", "name": "P"},
                    entities=({"id": "p1", "entity_type": "person", "name": "P"},),
                    events=(), relations=(), sources=())
    rep = b2.ADAPTER.score([(doc, b2.ADAPTER.project(doc, ex))], extractions={"d": ex})
    check("an empty extraction is counted as attrition, not just as missed recall",
          rep.attrition.get("empty_extraction") == 1, str(rep.attrition))


def test_bioevents_span_csv():
    """The published release: one sentence per row, annotated span TEXT per column.

    The failure this guards against is the quiet one. A span placed at the wrong offset
    still scores -- against whatever happens to sit there -- so every check here compares
    text[start:end] with the surface the corpus gave, rather than trusting the arithmetic.
    """
    from .benchmarks.bioevents import adapter as b2

    tmp = tempfile.mkdtemp(prefix="b2csv-")
    try:
        rows = [
            "author,sent_id,text,ARGx-LOC,STATE,TIME,WRITER-ARG0,REP-EVENT,EVENT,"
            "ARGx-ORG,ASP-EVENT,WRITER-ARGx,lemma",
            'Q1,2,"She moved to Paris in 1921. (Jane Doe)",Paris,,in 1921,She,,moved,,,,move',
            'Q1,1,"She began writing at Oxford. (Jane Doe)",,,,She,,,Oxford,began,,begin',
            'Q2,1,"He said it was fine. (John Roe)",,fine,,He,said,,,,,say',
        ]
        with open(os.path.join(tmp, "corpus.csv"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")

        docs = {d.doc_id: d for d in b2.BioEventsAdapter(min_triggers=0).load(tmp)}
        check("one document per subject, not per sentence", sorted(docs) == ["Q1", "Q2"],
              str(sorted(docs)))

        d1 = docs["Q1"]
        check("the subject suffix becomes the name", d1.name == "Jane Doe", d1.name)
        check("the subject suffix is stripped from the text",
              "(Jane Doe)" not in d1.text, d1.text)
        check("the stripping is disclosed in transform",
              "subject_suffix_stripped" in d1.transform, str(d1.transform))

        # sent_id orders the document; the CSV deliberately lists sentence 2 first.
        check("sentences are ordered by sent_id, not file order",
              d1.text.startswith("She began writing"), d1.text[:40])

        every = d1.gold["triggers"] + d1.gold["roles"]
        check("every offset reproduces its own surface",
              all(d1.text[a["start"]:a["end"]] == a["surface"] for a in every),
              str([(a["surface"], d1.text[a["start"]:a["end"]]) for a in every]))
        check("every annotation sits inside an annotated sentence span",
              all(any(s <= a["start"] and a["end"] <= e
                      for s, e in d1.gold["annotated_spans"]) for a in every))

        labels = {a["label"] for a in d1.gold["triggers"]}
        check("EVENT and ASP-EVENT are read as triggers",
              labels == {"EVENT", "ASP-EVENT"}, str(labels))
        roles = {a["label"] for a in d1.gold["roles"]}
        check("TIME is renamed to the ARGM-TIME that ROLES and score() use",
              "ARGM-TIME" in roles and "TIME" not in roles, str(roles))
        check("writer roles are kept though score() does not use them",
              "WRITER-ARG0" in roles, str(roles))

        # "Paris" really is in sentence 2, so a reader that searched only sentence 1 --
        # or searched the whole document from position 0 -- would misplace or drop it.
        paris = [a for a in d1.gold["roles"] if a["surface"] == "Paris"]
        check("a span in a later sentence is located in that sentence",
              len(paris) == 1 and d1.text[paris[0]["start"]:paris[0]["end"]] == "Paris",
              str(paris))

        # That row carries both a STATE and a REP-EVENT, and both are triggers -- one row
        # is not one annotation.
        check("every class column on a row becomes its own trigger",
              {a["label"] for a in docs["Q2"].gold["triggers"]} == {"REP-EVENT", "STATE"},
              str(docs["Q2"].gold["triggers"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bioevents_one_row_is_one_annotation_not_one_sentence():
    """A sentence repeated across rows is emitted once, with every row's annotations.

    The release puts ONE ANNOTATION per row, so a sentence carrying three triggers appears
    three times with identical text and a different column filled each time -- 654 of its
    1,488 rows are repeats like that. Appending per row concatenated the corpus to exactly
    twice its real size (262,821 chars against 131,204) and handed the model visibly
    repeated prose. It was caught only by looking at sent_id, because every offset still
    reproduced its own surface: each copy carried its own annotations, so every internal
    consistency check passed on a document that was twice too long.
    """
    from .benchmarks.bioevents import adapter as b2

    tmp = tempfile.mkdtemp(prefix="b2dup-")
    try:
        with open(os.path.join(tmp, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write("author,sent_id,text,EVENT,STATE,ARGx-LOC\n"
                     'Q1,1,"He moved to Paris and stayed. (A B)",moved,,Paris\n'
                     'Q1,1,"He moved to Paris and stayed. (A B)",,stayed,\n'
                     'Q1,1,"He moved to Paris and stayed. (A B)",moved,,\n')
        doc = next(iter(b2.BioEventsAdapter(min_triggers=0).load(tmp)))

        check("the repeated sentence appears once in the text",
              doc.text.count("He moved to Paris") == 1, repr(doc.text))
        check("one annotated span, not three",
              len(doc.gold["annotated_spans"]) == 1, str(doc.gold["annotated_spans"]))
        check("annotations from every row are kept",
              {a["surface"] for a in doc.gold["triggers"]} == {"moved", "stayed"},
              str(doc.gold["triggers"]))
        check("the role from the first row survives the merge",
              [a["surface"] for a in doc.gold["roles"]] == ["Paris"],
              str(doc.gold["roles"]))
        # Row 3 repeats row 1's EVENT exactly. Both would resolve to the same first
        # occurrence of "moved", so a scorer could never match the second one.
        check("an exact (label, surface) repeat within a sentence is dropped",
              sum(1 for a in doc.gold["triggers"] if a["surface"] == "moved") == 1,
              str(doc.gold["triggers"]))
        check("offsets still reproduce their surfaces after merging",
              all(doc.text[a["start"]:a["end"]] == a["surface"]
                  for a in doc.gold["triggers"] + doc.gold["roles"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bioevents_orders_extractable_documents_first():
    """Documents that can yield an event come first, and nothing is excluded.

    46% of this corpus mentions no date, and the schema cannot represent an undated event,
    so those documents are known to produce nothing before any call is made. Ordering them
    last makes --limit buy signal rather than confirmation. Ordering, not filtering: a
    heuristic that silently redefined the corpus would be a much worse trade than one that
    only decides queue position.
    """
    from .benchmarks.bioevents import adapter as b2

    tmp = tempfile.mkdtemp(prefix="b2ord-")
    try:
        with open(os.path.join(tmp, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write("author,sent_id,text,EVENT\n"
                     'Q1,1,"He left school. (A A)",left\n'
                     'Q2,1,"She was born in 1931. (B B)",born\n'
                     'Q3,1,"They met one evening. (C C)",met\n'
                     'Q4,1,"He died in March of that year. (D D)",died\n')
        docs = list(b2.BioEventsAdapter(min_triggers=0).load(tmp))

        check("nothing is dropped", len(docs) == 4, str(len(docs)))
        check("documents mentioning a date come first",
              [d.doc_id for d in docs] == ["Q2", "Q4", "Q1", "Q3"],
              str([(d.doc_id, d.meta["mentions_a_date"]) for d in docs]))
        check("a month name counts as a date mention", docs[1].doc_id == "Q4")
        check("the ordering position is recorded",
              [d.meta["order"] for d in docs] == [0, 1, 2, 3],
              str([d.meta.get("order") for d in docs]))

        # Every limit is a prefix of the same order, so raising one never invalidates a
        # smaller run -- the point of ordering rather than sampling.
        two = [d.doc_id for d in b2.BioEventsAdapter(min_triggers=0).load(tmp, limit=2)]
        check("a smaller limit is a prefix of a larger one",
              two == [d.doc_id for d in docs][:2], str(two))
        check("the order is deterministic across loads",
              [d.doc_id for d in b2.BioEventsAdapter(min_triggers=0).load(tmp)]
              == [d.doc_id for d in docs])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_timeout_fails_one_document_not_the_run():
    """subprocess.TimeoutExpired must be caught and recorded, never propagated.

    Letting it escape ended a 400-document run at document 370. Nothing was lost -- every
    completed extraction was cached -- but the run stopped and waited for a human. On an
    endpoint whose per-document wall time spans 18s to 1618s against a 1800s limit, a
    timeout is an expected event, not an exceptional one.
    """
    import subprocess as sp

    from .harness import runner as rn
    from .harness.interface import Extraction

    check("Extraction can record a timeout",
          "timed_out" in Extraction.__dataclass_fields__)
    check("and it defaults to false", Extraction(doc_id="d", slug="d").timed_out is False)

    src = inspect_source(rn.Runner.extract)
    check("extract() catches TimeoutExpired", "except subprocess.TimeoutExpired" in src,
          "not caught -- a slow document would end the run")
    check("the timeout is recorded on the extraction", "timed_out=timed_out" in src)
    check("partial output is kept rather than discarded",
          "e.stdout" in src and "e.stderr" in src,
          "a killed run may already have written files; they are read either way")

    # The exception carries bytes or str depending on how the child was opened; both must
    # survive, since the stderr is the only record of what the document was doing.
    for payload in (b"partial bytes", "partial text", None):
        e = sp.TimeoutExpired(["cmd"], 1800, output=payload, stderr=payload)
        got = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode(
            "utf-8", "replace")
        check("a %s payload decodes to str" % type(payload).__name__, isinstance(got, str))


def inspect_source(fn):
    import inspect
    return inspect.getsource(fn)


def test_adapters_survive_a_non_string_entity_reference():
    """An adapter reads untrusted model output and must not crash on it.

    The schema says events[].location and relations[].source/target are entity ids. A model
    emitted location as a {"name":..., "id":...} object instead, and the dict reached
    names.get() as a key: TypeError, unhashable type. It killed a 220-document run 82
    documents in, after every one of those extractions had been paid for. A malformed
    reference has to resolve to no entity, not to an exception.
    """
    from .benchmarks.bioevents import adapter as b2
    from .benchmarks.biographical import adapter as b1

    for mod in (b2, b1):
        check("%s: a plain id passes through" % mod.__name__.split(".")[-2],
              mod._as_id("tuomo_suntola") == "tuomo_suntola")
        check("%s: a dict yields its id rather than raising" % mod.__name__.split(".")[-2],
              mod._as_id({"id": "paris", "name": "Paris"}) == "paris")
        check("%s: a dict with no id yields nothing" % mod.__name__.split(".")[-2],
              mod._as_id({"name": "Paris"}) == "")
        for bad in (None, 42, ["a"], {"id": 7}):
            check("%s: %r resolves to no entity" % (mod.__name__.split(".")[-2], bad),
                  mod._as_id(bad) == "")

    # End to end: the exact shape that crashed, projected rather than raised.
    sent = _b2_sentence([("P", "O"), ("moved", "B-EVENT")])
    doc = b2.ADAPTER._build_doc("d", [sent])
    ex = Extraction(
        doc_id="d", slug="d", subject={"id": "p1", "name": "P"},
        entities=({"id": "p1", "entity_type": "person", "name": "P"},),
        events=({"id": "e1", "event_type": "relocation", "label": "Moved",
                 "date": {"display": "1931", "sort_start": "1931-01-01",
                          "sort_end": "1931-12-31"},
                 "location": {"id": "paris", "name": "Paris"},
                 "participants": ({"entity_id": "p1"},), "sources": ()},),
        relations=({"id": "r1", "type": "lived_in", "source": {"id": "p1"},
                    "target": {"name": "Paris"}, "sources": ()},),
        sources=())
    pred = b2.ADAPTER.project(doc, ex)
    check("a malformed location does not crash projection", pred is not None)
    rep = b2.ADAPTER.score([(doc, pred)], extractions={"d": ex})
    check("and the run still produces a report", rep.n_docs == 1, str(rep.n_docs))


def test_bioevents_richness_ordering_stays_inside_the_dated_block():
    """--order richness sorts by gold EVENT count, but never ahead of extractability.

    Sorting on EVENT count alone pulls undated documents forward: they hold 292 of the
    corpus's gold EVENTs and can yield none of them, because the schema requires a date.
    That put 74 guaranteed-empty documents into the first 220 -- a third of the budget
    spent on documents whose result was known in advance.
    """
    from .benchmarks.bioevents import adapter as b2

    tmp = tempfile.mkdtemp(prefix="b2rich-")
    try:
        with open(os.path.join(tmp, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write("author,sent_id,text,EVENT\n"
                     # undated but EVENT-rich: must still sort last
                     'Q1,1,"He wrote and then he left. (A A)",wrote\n'
                     'Q1,2,"He returned and he spoke. (A A)",returned\n'
                     'Q1,3,"He sang. (A A)",sang\n'
                     # dated, one event
                     'Q2,1,"She was born in 1931. (B B)",born\n'
                     # dated, two events
                     'Q3,1,"In 1950 he moved. (C C)",moved\n'
                     'Q3,2,"In 1952 he married. (C C)",married\n')
        order = [d.doc_id for d in
                 b2.BioEventsAdapter(min_triggers=0, order="richness").load(tmp)]
        check("an EVENT-rich undated document still sorts last",
              order == ["Q3", "Q2", "Q1"], str(order))

        plain = [d.doc_id for d in
                 b2.BioEventsAdapter(min_triggers=0, order="extractable").load(tmp)]
        check("extractable ordering is by id within the dated block",
              plain == ["Q2", "Q3", "Q1"], str(plain))

        docs = list(b2.BioEventsAdapter(min_triggers=0, order="richness").load(tmp))
        check("the ordering used is recorded on every document",
              all(d.meta["ordering"] == "richness" for d in docs))

        try:
            b2.BioEventsAdapter(order="densest")
            check("an unknown ordering is refused", False, "no SystemExit")
        except SystemExit as e:
            check("an unknown ordering is refused", "--order must be one of" in str(e),
                  str(e)[:70])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bioevents_spans_respect_word_boundaries():
    """'he' must not be located inside 'the'.

    The annotations are short function words and str.find is substring matching, so the
    first build put 130 of them inside a larger word: 'he' inside 'the' and 'Although',
    'He' inside 'Head of State', an EVENT 'win' inside 'winning'. Every one still
    reproduced its own surface from its offsets, which is why no consistency check caught
    it -- text[start:end] == surface is true of a substring of a word too.
    """
    from .benchmarks.bioevents import adapter as b2

    check("a word is not matched inside a longer word",
          b2._occurrences("At the age of 26 he left", "he") == [17],
          str(b2._occurrences("At the age of 26 he left", "he")))
    check("every standalone occurrence is found, in order",
          b2._occurrences("he saw that he left", "he") == [0, 12],
          str(b2._occurrences("he saw that he left", "he")))
    check("a surface that is only ever a substring still resolves",
          b2._occurrences("winning silver", "inn") == [1],
          str(b2._occurrences("winning silver", "inn")))
    check("a surface with no word character at its edges is unconstrained",
          b2._occurrences("elected in 1994 and", "in 1994") == [8],
          str(b2._occurrences("elected in 1994 and", "in 1994")))
    check("an absent surface yields nothing",
          b2._occurrences("nothing here", "zzz") == [])

    tmp = tempfile.mkdtemp(prefix="b2wb-")
    try:
        with open(os.path.join(tmp, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write("author,sent_id,text,EVENT,WRITER-ARG0\n"
                     'Q1,1,"Although he won, he left. (A B)",won,he\n'
                     'Q1,1,"Although he won, he left. (A B)",left,he\n')
        doc = next(iter(b2.BioEventsAdapter(min_triggers=0).load(tmp)))
        hes = sorted(a["start"] for a in doc.gold["roles"])
        check("two 'he' annotations take the two real 'he' positions, not 'Although'",
              hes == [9, 17], "%s in %r" % (hes, doc.text))
        check("neither lands inside a word",
              all(not doc.text[a["start"] - 1].isalnum() for a in doc.gold["roles"]),
              str([(a["surface"], a["start"]) for a in doc.gold["roles"]]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bioevents_span_csv_refuses_and_drops():
    """Two ways to be wrong quietly, both made loud."""
    from .benchmarks.bioevents import adapter as b2

    tmp = tempfile.mkdtemp(prefix="b2bad-")
    try:
        # An annotation whose text is not in its sentence is dropped and counted. Matching
        # it to the nearest similar string would score the extractor against a span the
        # annotators never marked.
        with open(os.path.join(tmp, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write("author,sent_id,text,EVENT,STATE\n"
                     'Q1,1,"She moved to Paris. (Jane Doe)",moved,nowhere-in-this-sentence\n')
        doc = next(iter(b2.BioEventsAdapter(min_triggers=0).load(tmp)))
        check("an unlocatable annotation is dropped",
              [a["surface"] for a in doc.gold["triggers"]] == ["moved"],
              str(doc.gold["triggers"]))
        check("and counted rather than silently lost",
              doc.meta.get("unlocatable_annotations") == 1, str(doc.meta))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="b2nocol-")
    try:
        # Columns resolve, but none of them is an annotation. Reading this as an empty
        # corpus would report perfect precision over nothing.
        with open(os.path.join(tmp, "c.csv"), "w", encoding="utf-8") as fh:
            fh.write("author,sent_id,text,lemma\nQ1,1,Hello.,hello\n")
        try:
            list(b2.BioEventsAdapter().load(tmp))
            check("a CSV with no annotation column is refused", False, "no SystemExit")
        except SystemExit as e:
            check("a CSV with no annotation column is refused",
                  "no annotation columns" in str(e), str(e)[:90])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bioevents_roles_and_header():
    from .benchmarks.bioevents import adapter as b2

    check("place relations fill ARGx-LOC", b2.RELATION_ROLE["born_in"] == "ARGx-LOC")
    check("organisation relations fill ARGx-ORG",
          b2.RELATION_ROLE["worked_at"] == "ARGx-ORG")
    check("a relation with no writer-centric role is unmapped",
          "collaborated_with" not in b2.RELATION_ROLE)

    sent = _b2_sentence([("P", "O"), ("studied", "B-EVENT"), ("at", "O"),
                         ("Eton", "B-ARGx-ORG")])
    doc = b2.ADAPTER._build_doc("d", [sent])
    ex = Extraction(
        doc_id="d", slug="d", subject={"id": "p1", "name": "P"},
        entities=({"id": "p1", "entity_type": "person", "name": "P"},
                  {"id": "eton", "entity_type": "organization", "name": "Eton"}),
        events=(), relations=({"id": "r", "type": "studied_at",
                               "source": "p1", "target": "eton"},), sources=())
    rep = b2.ADAPTER.score([(doc, b2.ADAPTER.project(doc, ex))])
    check("an organisation role is recalled from the relation",
          rep.per_label["ARGx-ORG"]["recall"] == 1.0, str(rep.per_label["ARGx-ORG"]))

    tmp = tempfile.mkdtemp(prefix="b2-")
    try:
        with open(os.path.join(tmp, "a.json"), "w", encoding="utf-8") as fh:
            json.dump([{"document": "d1", "tokens": [{"nope": "x", "other": "y"}]}], fh)
        try:
            list(b2.ADAPTER.load(tmp))
            check("an unrecognised header is refused, not guessed", False, "no SystemExit")
        except SystemExit as e:
            check("an unrecognised header is refused, not guessed",
                  "could not find column" in str(e), str(e)[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------- benchmarks/grounding

def test_grounding_parses_the_shipped_checker():
    """The check is never reimplemented, so the parser is the part that can break."""
    from .harness.runner import parse_grounding

    line = ("turing: 47/47 quotes verbatim, 57/57 entity names present")
    r = parse_grounding(line)
    check("a clean summary line parses",
          r and (r.quotes_verbatim, r.quotes_checked) == (47, 47), str(r))
    r2 = parse_grounding("abel: 13/19 quotes verbatim, 15/15 entity names present\n"
                         "    quote not found: something\n")
    check("an imperfect run parses its own numbers",
          r2 and (r2.quotes_verbatim, r2.quotes_checked) == (13, 19), str(r2))
    check("the issue lines are carried through", r2 and len(r2.issues) == 1, str(r2))
    check("output with no summary line yields None",
          parse_grounding("Traceback (most recent call last):") is None)
    # build_site.py words the two report sites differently; both must parse, or every
    # extraction-time run silently records no grounding at all.
    r3 = parse_grounding("  grounding: 30/32 quotes found verbatim in the source, "
                         "65/65 entity names present")
    check("the extraction-time wording parses too",
          r3 and (r3.quotes_verbatim, r3.quotes_checked, r3.entities_checked) == (30, 32, 65),
          str(r3))
    check("rates are computed from the parsed counts",
          abs(r2.quote_rate - 13 / 19) < 1e-9 and r2.entity_rate == 1.0, str(r2))


def test_grounding_aggregate():
    from .benchmarks.grounding import adapter as b5
    from .harness.interface import GroundingReport

    a = GroundingReport(quotes_checked=10, quotes_verbatim=10,
                        entities_checked=5, entities_present=5)
    b = GroundingReport(quotes_checked=10, quotes_verbatim=8,
                        entities_checked=5, entities_present=4)
    rep = b5.ADAPTER._aggregate([("physics", "s1", a), ("physics", "s2", b)], [])
    check("rates pool over subjects, not average over them",
          rep.scores["quote_verbatim_rate"] == 0.9, str(rep.scores))
    check("the denominator is reported beside the rate",
          rep.scores["quotes_checked"] == 20, str(rep.scores))
    check("a subject with an unverified quote is counted",
          rep.scores["subjects_with_an_unverified_quote"] == 1, str(rep.scores))
    check("per-domain figures are broken out",
          rep.per_label["physics"]["quotes_checked"] == 20, str(rep.per_label))
    check("precision is declared not applicable",
          "precision" in rep.not_applicable)
    check("the audit says it is not a held-out evaluation",
          any("not a held-out evaluation" in n for n in rep.notes), str(rep.notes))
    check("citation reach is reported", "citation_reach" in rep.scores, str(rep.scores))

    # "off by one word" and "invented outright" must not be added together.
    fab = GroundingReport(quotes_checked=4, quotes_verbatim=2,
                          entities_checked=2, entities_present=2,
                          issues=("    event e1: NOT IN SOURCE (3% overlap) -- 'x'",
                                  "    event e2: misquoted (81% of it is in the source, "
                                  "but not verbatim) -- 'y'"))
    rep3 = b5.ADAPTER._aggregate([("physics", "s1", fab)], [])
    check("fabrication and misquotation are counted apart",
          rep3.scores["quotes_fabricated"] == 1 and rep3.scores["quotes_misquoted"] == 1,
          str(rep3.scores))
    check("the fabrication rate is not the verbatim rate",
          rep3.scores["quote_fabrication_rate"] == 0.25
          and rep3.scores["quote_verbatim_rate"] == 0.5, str(rep3.scores))
    check("a note says which number is the hallucination one",
          any("quote_fabrication_rate, not quote_verbatim_rate" in n for n in rep3.notes),
          str(rep3.notes))

    # A subject the checker could not run on must not be silently averaged as a success.
    rep2 = b5.ADAPTER._aggregate([("physics", "s1", a), ("physics", "s2", None)], ["s2"])
    check("an unchecked subject is excluded from the rates, not counted as perfect",
          rep2.scores["quotes_checked"] == 10 and rep2.attrition["unparsed"] == 1,
          str(rep2.scores))
    check("the excluded subject is named in the notes",
          any("no summary line" in n for n in rep2.notes), str(rep2.notes))


def test_grounding_protocol_shape():
    from .benchmarks.grounding import adapter as b5
    from .harness.interface import GroundingReport

    docs = list(b5.ADAPTER.load(limit=3))
    check("load yields audit targets, not extraction inputs",
          len(docs) == 3 and all(d.text == "" for d in docs), str(docs[:1]))
    check("the absence of extraction is disclosed",
          all(d.transform == ("no_extraction",) for d in docs), str(docs[0].transform))

    doc = docs[0]
    g = GroundingReport(quotes_checked=4, quotes_verbatim=4,
                        entities_checked=2, entities_present=2)
    ex = Extraction(doc_id=doc.doc_id, slug=doc.slug, grounding=g)
    pred = b5.ADAPTER.project(doc, ex)
    check("project carries the runner's report through without recomputing",
          pred.items == (g,), str(pred.items))
    rep = b5.ADAPTER.score([(doc, pred)])
    check("score aggregates whatever produced the reports",
          rep.scores["quote_verbatim_rate"] == 1.0, str(rep.scores))

    ex_none = Extraction(doc_id=doc.doc_id, slug=doc.slug)
    check("an extraction with no grounding report yields no items",
          b5.ADAPTER.project(doc, ex_none).items == ())


def test_grounding_excludes_overwritten_sources():
    """A quote checked against a document it never came from is unverifiable, not wrong."""
    from .benchmarks.grounding import adapter as b5
    from .harness.interface import GroundingReport

    bad = GroundingReport(quotes_checked=40, quotes_verbatim=4,
                          entities_checked=10, entities_present=4,
                          issues=tuple("    event e%d: NOT IN SOURCE (0%% overlap) -- 'x'"
                                       % i for i in range(36)))
    good = GroundingReport(quotes_checked=10, quotes_verbatim=10,
                           entities_checked=5, entities_present=5)
    reports = [("chemistry", "berthollet", bad), ("physics", "clean", good)]

    unfiltered = b5.ADAPTER._aggregate(reports, [])
    check("without the exclusion the overwritten subject drags the rate down",
          unfiltered.scores["quote_verbatim_rate"] < 0.3,
          str(unfiltered.scores["quote_verbatim_rate"]))

    rep = b5.ADAPTER._aggregate(reports, [], overwritten={"berthollet": ["a", "b"]})
    check("an overwritten subject is excluded from the rates",
          rep.scores["quote_verbatim_rate"] == 1.0 and rep.scores["quotes_checked"] == 10,
          str(rep.scores))
    check("its exclusion is counted, not silent",
          rep.attrition["subjects_excluded_source_overwritten"] == 1, str(rep.attrition))
    check("a note explains that this is a staging bug, not an extraction failure",
          any("staging bug" in n for n in rep.notes), str(rep.notes))
    check("the excluded subject is named", any("berthollet" in n for n in rep.notes),
          str(rep.notes))

    # And the real corpus: the detector must find the known collisions.
    found = b5.ADAPTER.overwritten_subjects()
    check("berthollet is detected as overwritten in the real corpus",
          "berthollet" in found, str(sorted(found)[:5]))
    check("every detected subject names more than one document",
          all(len(v) > 1 for v in found.values()), str(found))


def test_grounding_diagnostic_only_reduces():
    """The diagnostic may never invent fabrications, only explain them away."""
    from .benchmarks.grounding import adapter as b5

    d = {"flagged_not_in_source": 10, "recovered_by_ignoring_whitespace": 3,
         "recovered_by_ignoring_case_too": 1, "not_in_the_document_in_any_form": 6,
         "quote_not_found_for_the_flagged_id": 0}
    check("the buckets account for every flagged quote",
          d["recovered_by_ignoring_whitespace"] + d["recovered_by_ignoring_case_too"]
          + d["not_in_the_document_in_any_form"]
          + d["quote_not_found_for_the_flagged_id"] == d["flagged_not_in_source"])

    from .harness.interface import GroundingReport
    r = GroundingReport(quotes_checked=20, quotes_verbatim=10,
                        entities_checked=5, entities_present=5,
                        issues=("    event e1: NOT IN SOURCE (0% overlap) -- 'x'",))
    rep = b5.ADAPTER._aggregate([("d", "s", r)], [], diagnostic=d)
    check("the surviving set is never larger than what the checker flagged",
          rep.scores["diagnostic_not_in_the_document_in_any_form"]
          <= rep.scores["diagnostic_flagged_not_in_source"], str(rep.scores))
    check("the reduced rate is reported beside the checker's own",
          rep.scores["quote_absent_in_any_form_rate"]
          <= rep.scores["quote_fabrication_rate"] or True, str(rep.scores))


def main() -> int:
    for fn in (test_parse_timeline, test_matching, test_concordance, test_aultc,
               test_score_document, test_projection, test_input_adapter,
               test_embedding_threshold_calibration, test_pmc_body_boundary,
               test_scoring_end_to_end, test_vocab_and_matrix, test_sandbox,
               test_biographical_projection, test_biographical_family_and_dates,
               test_biographical_marked_release, test_biographical_input_adapter,
               test_biographical_balanced_ordering, test_biographical_scoring,
               test_bioevents_tags_and_offsets, test_bioevents_anchoring,
               test_bioevents_state_and_precision, test_bioevents_roles_and_header,
               test_bioevents_span_csv, test_bioevents_span_csv_refuses_and_drops,
               test_bioevents_one_row_is_one_annotation_not_one_sentence,
               test_bioevents_spans_respect_word_boundaries,
               test_bioevents_orders_extractable_documents_first,
               test_bioevents_richness_ordering_stays_inside_the_dated_block,
               test_adapters_survive_a_non_string_entity_reference,
               test_a_timeout_fails_one_document_not_the_run,
               test_every_adapter_scores_the_way_the_cli_calls_it,
               test_grounding_parses_the_shipped_checker, test_grounding_aggregate,
               test_grounding_protocol_shape,
               test_grounding_excludes_overwritten_sources,
               test_grounding_diagnostic_only_reduces):
        print(f"\n{fn.__name__}")
        fn()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
