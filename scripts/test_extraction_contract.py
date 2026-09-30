"""Offline regression checks: python -B -m unittest scripts.test_extraction_contract."""
import copy
import io
import json
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
