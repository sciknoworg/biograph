"""Self-checks for the harness, none of which call a model or touch the network.

    python -m experiments.tests

Covers the parts where a silent bug would produce a plausible-looking number in the
paper: the matcher, the concordance and its tie handling, the projection from biograph's
schema into hours, the sandbox's hash verification, and the coverage matrix's agreement
with schema/.
"""
from __future__ import annotations

import datetime as dt
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
        check("the grouping is disclosed in transform",
              a.transform == ("grouped_by_person",), str(a.transform))
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


def main() -> int:
    for fn in (test_parse_timeline, test_matching, test_concordance, test_aultc,
               test_score_document, test_projection, test_input_adapter,
               test_embedding_threshold_calibration, test_pmc_body_boundary,
               test_scoring_end_to_end, test_vocab_and_matrix, test_sandbox,
               test_biographical_projection, test_biographical_family_and_dates,
               test_biographical_input_adapter, test_biographical_scoring):
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
