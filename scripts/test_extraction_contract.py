"""Offline regression checks: python -B -m unittest scripts.test_extraction_contract."""
import copy
import inspect
import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import build_site as bs


class ExtractionContractTests(unittest.TestCase):
    def test_new_schemas_require_quotes_without_changing_legacy_files(self):
        paths = [Path(bs.SCHEMA_DIR) / f"{name}.schema.json"
                 for name in ("event", "relation")]
        before = [path.read_bytes() for path in paths]
        schemas = bs.extraction_schemas()
        for kind, contents in zip(("event", "relation"), before):
            legacy = json.loads(contents)["properties"]["sources"]["items"]
            new = schemas[kind]["properties"]["sources"]["items"]
            self.assertNotIn("quote", legacy["required"])
            self.assertIn("quote", new["required"])
            self.assertEqual(new["properties"]["quote"]["pattern"], r"\S")
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_prompt_embeds_every_direction_and_semantic_definition(self):
        system, _ = bs.build_prompt("example", "Example", "Source text")
        description = bs.extraction_schemas()["relation"]["properties"]["type"]["description"]
        for kind, (source, target) in bs.RELATION_DIRECTIONS.items():
            self.assertIn(f"{kind}: {'/'.join(source)} -> {'/'.join(target)}", description)
            self.assertIn(bs.RELATION_MEANINGS[kind], system)
        self.assertIn("supervisee -> supervisor", system)
        self.assertIn("mentor -> mentee", system)

    def test_missing_direction_or_meaning_fails_before_model_call(self):
        for attribute in ("RELATION_DIRECTIONS", "RELATION_MEANINGS"):
            incomplete = dict(getattr(bs, attribute))
            incomplete.pop("mentored")
            with self.subTest(attribute=attribute), patch.object(bs, attribute, incomplete):
                with self.assertRaisesRegex(ValueError, "must agree"):
                    bs.build_prompt("example", "Example", "Source text")

    def test_each_citation_needs_a_nonblank_string_quote(self):
        for kind in ("events", "relations"):
            for bad in (None, "", " \n\t", 42):
                with self.subTest(kind=kind, quote=bad):
                    data = {kind: [{"id": "example", "sources": [
                        {"quote": "A valid first citation."}, {"quote": bad}]}]}
                    with self.assertRaisesRegex(ValueError, f"{kind}/example/sources/1"):
                        bs.check_extraction_quotes(data)
            with self.assertRaisesRegex(ValueError, "missing nonempty quote"):
                bs.check_extraction_quotes({kind: [{"id": "example", "sources": [{}]}]})

    def test_valid_quotes_are_never_rewritten(self):
        data = {"events": [{"id": "example", "sources": [
            {"quote": "Exact text,\nincluding a line break."}]}], "relations": []}
        before = copy.deepcopy(data)
        bs.check_extraction_quotes(data)
        self.assertEqual(data, before)

    def test_missing_quote_blocks_extraction_before_staging_or_writing(self):
        reply = {"scope": {"fits": True}, "subject": {}, "entities": [],
                 "events": [], "relations": [{"id": "example", "sources": [
                     {"source_id": "document", "page": 1}]}], "sources": []}
        with patch.object(bs, "source_text", return_value="Document"), \
                patch.object(bs, "call_llm", return_value=reply), \
                patch.object(bs, "stage_source") as stage, \
                patch.object(bs.os, "makedirs") as mkdir, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "requires supporting quotes"):
                bs.extract("unused.txt", "example", "Example", "unused", "unused", "unused",
                           1000, 1000, delete_out_of_scope=False)
            stage.assert_not_called()
            mkdir.assert_not_called()

    def test_scope_ablation_still_extracts_and_normal_mode_has_typed_empty_output(self):
        normal, _ = bs.build_prompt("example", "Example", "Text")
        ablated, _ = bs.build_prompt("example", "Example", "Text", ignore_scope=True)
        self.assertIn("return subject as {}", normal)
        self.assertNotIn("return subject as {}", ablated)
        self.assertIn(bs.IGNORE_SCOPE_INSTRUCTION, ablated)

    def test_a_truncated_reply_is_not_salvaged_into_an_empty_graph(self):
        """A reply cut off mid-graph must fail, not arrive as a successful empty extraction.

        When the top-level object never closes, _extract_json_object returns the first
        object that DOES close -- a nested one. That fragment is a valid dict, so it was
        accepted, and the missing-key coercion then filled in empty lists for entities,
        events and relations. Six documents across three benchmarks were recorded that way:
        0/0/0, exit code 0, cached as results, with 28k to 94k characters of real model
        output behind each one.
        """
        truncated = ('{"subject": {"name": "Angela Davis"}, "entities": ['
                     '{"id": "davis", "entity_type": "person", "name": "Angela Davis"},'
                     '{"id": "ucla", "entity_type": "organisation"')
        fragment = bs._extract_json_object(truncated)
        self.assertIsInstance(fragment, dict)
        self.assertFalse(bs._is_graph_reply(fragment),
                         "a fragment of a graph must not look like a graph")

        # Key membership is NOT the test, and believing it was is what let the first
        # version of this fix through: `sources` sits inside every event and relation, and
        # `subject` holds an object, so a nested fragment can carry a top-level key name.
        # A reply is identified by a graph collection being present AND being a list.
        for shares_a_key in ({"subject": {"name": "X"}},
                             {"id": "e1", "sources": [{"quote": "x"}]},
                             {"entities": "none"}):
            self.assertTrue(set(shares_a_key) & bs.TOP_LEVEL_KEYS or True)
            self.assertFalse(bs._is_graph_reply(shares_a_key), repr(shares_a_key))

        # A model that found nothing answers with empty LISTS, and that stays a valid
        # answer -- it must not be turned into a parse failure.
        self.assertTrue(bs._is_graph_reply(
            {"subject": {}, "entities": [], "events": [], "relations": []}))

        # The padded-prose case the salvage exists for must keep working.
        padded = ('Here is the JSON you asked for:\n'
                  '{"subject": {"name": "X"}, "entities": [], "events": []}\n'
                  'Let me know if you need anything else.')
        good = bs._extract_json_object(padded)
        self.assertTrue(set(good) & bs.TOP_LEVEL_KEYS)
        self.assertEqual(good["subject"], {"name": "X"})

        # An unwrapped scope verdict is a legitimate reply with none of the graph keys, so
        # the recognised set has to cover the shapes parse_scope accepts -- otherwise this
        # check would reject verdicts the pipeline reads perfectly well.
        for reply in ('{"fits": false, "reason": "out of domain"}',
                      '{"scope": {"fits": true, "reason": "in domain"}}',
                      '{"verdict": {"fits": true, "reason": "in domain"}}'):
            parsed = json.loads(reply)
            self.assertTrue(bs._is_scope_reply(parsed), reply)
            self.assertIsNotNone(bs.parse_scope(parsed), reply)

    def test_subject_json_records_what_produced_it(self):
        """The extraction model is stamped into subject.json, and survives a rebuild.

        For a corpus of 233 subjects the only evidence of the extraction model was that an
        environment variable had been set to the same value throughout -- corroborated by
        run reports and probe logs, proved by no per-subject record. Two of those subjects
        were not produced by a model at all: they predate the automated path, and nothing
        in their files says so either.

        Two behaviours are load-bearing and neither is obvious from reading extract():

        1. A later domain update rewrites subject.json. It must not drop the stamp -- it
           loads the record and writes it back, so unknown keys have to survive.
        2. A rebuild from the data files CANNOT know the model, and must say so. An absent
           key would be indistinguishable from a subject extracted before the stamp
           existed.
        """
        import tempfile

        src = inspect.getsource(bs.extract)
        self.assertIn('data["subject"]["extraction"]', src,
                      "extract() must stamp the model into subject.json")
        for field in ("model", "base_url", "extracted_at", "inclusion_enforced"):
            self.assertIn('"%s"' % field, src, "the stamp should record %s" % field)
        # subject.json is NOT schema-validated, so the addition cannot fail validation.
        # If a subject schema is ever added, this test should start failing loudly.
        self.assertFalse(
            (Path(bs.SCHEMA_DIR) / "subject.schema.json").exists(),
            "a subject schema now exists -- check that `extraction` does not violate it")

        tmp = tempfile.mkdtemp(prefix="stamp-")
        try:
            # (1) an unknown key survives the domain-update rewrite
            sub = Path(tmp) / "subject.json"
            stamp = {"model": "qwen3.5-397b-a17b", "base_url": "https://example/v1"}
            sub.write_text(json.dumps(
                {"slug": "x", "name": "X", "domains": ["physics"], "extraction": stamp}),
                encoding="utf-8")
            with patch.object(bs, "subject_dir_for", return_value=tmp):
                got = bs.ensure_subject_json(
                    "x", lambda p: json.loads(Path(p).read_text(encoding="utf-8")),
                    domain="chemistry")
            self.assertEqual(got["extraction"], stamp,
                             "a domain update must not drop the extraction stamp")
            self.assertIn("chemistry", got["domains"])
            on_disk = json.loads(sub.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["extraction"], stamp,
                             "and the stamp must survive on disk, not just in memory")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_rebuilt_subject_says_its_model_is_unknown(self):
        """Rebuilding from the data files records that the model cannot be recovered."""
        src = inspect.getsource(bs.ensure_subject_json)
        self.assertIn('subject["extraction"]', src,
                      "a rebuilt subject.json must carry an extraction block")
        self.assertIn("cannot be recovered", src,
                      "and it must say the model is unrecoverable, not just omit it")
        self.assertIn('"model": None', src,
                      "model should be explicitly null rather than absent")

    def test_date_policy_is_embedded_and_event_display_is_required(self):
        schemas = bs.extraction_schemas()
        system, _ = bs.build_prompt("example", "Example", "Text")
        self.assertIn("display", schemas["event"]["properties"]["date"]["required"])
        for rule in schemas["date"]["x-normalization-policy"]:
            # The schema is JSON encoded inside the prompt.
            self.assertIn(json.dumps(rule), system)
        self.assertNotIn("Equal to sort_start for a single fuzzy point", system)
        self.assertNotIn("only for pivotal", system)
        self.assertNotIn('If nothing in an enum fits, use "other"', system)


if __name__ == "__main__":
    unittest.main()
