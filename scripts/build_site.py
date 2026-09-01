#!/usr/bin/env python3
"""
Build a standalone, self-contained HTML explorer for one biograph subject.

Usage:
    python3 scripts/build_site.py <subject_slug>
    python3 scripts/build_site.py --all

Reads subjects/<slug>/{subject,entities,events,relations,sources}.json,
validates them against schema/*.schema.json, and writes a single
standalone HTML file to dist/<slug>.html by inlining the data into
frontend/template.html. The output has no dependency on this repo layout
at all (aside from loading D3 from a CDN) — it can be opened directly in
a browser, emailed, or dropped anywhere.
"""
import json, sys, os, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(ROOT, "schema")
SUBJECTS_DIR = os.path.join(ROOT, "subjects")
TEMPLATE = os.path.join(ROOT, "frontend", "template.html")
DIST_DIR = os.path.join(ROOT, "dist")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_subject(slug):
    """Validate the subject's four data files against the JSON Schemas.
    Returns (entities, events, relations, sources). Raises on any error."""
    try:
        from jsonschema import Draft202012Validator, RefResolver
    except ImportError:
        print("  (jsonschema not installed — skipping schema validation; "
              "pip install jsonschema to enable it)")
        Draft202012Validator = None

    sdir = os.path.join(SUBJECTS_DIR, slug)
    entities = load(os.path.join(sdir, "entities.json"))
    events = load(os.path.join(sdir, "events.json"))
    relations = load(os.path.join(sdir, "relations.json"))
    sources = load(os.path.join(sdir, "sources.json"))

    if Draft202012Validator:
        store = {}
        for fn in ["date", "entity", "event", "relation", "source"]:
            schema = load(os.path.join(SCHEMA_DIR, f"{fn}.schema.json"))
            store[schema["$id"]] = schema
        errors = []

        def check(schema_name, items):
            schema = store[f"https://biograph/schema/{schema_name}.schema.json"]
            resolver = RefResolver.from_schema(schema, store=store)
            v = Draft202012Validator(schema, resolver=resolver)
            for it in items:
                for e in v.iter_errors(it):
                    errors.append(f"{schema_name} {it.get('id')}: {e.message}")

        check("entity", entities)
        check("event", events)
        check("relation", relations)
        check("source", sources)

        # referential integrity
        ent_ids = {e["id"] for e in entities}
        src_ids = {s["id"] for s in sources}
        event_ids = {e["id"] for e in events}
        for ev in events:
            for p in ev["participants"]:
                if p["entity_id"] not in ent_ids:
                    errors.append(f"event {ev['id']}: unknown participant '{p['entity_id']}'")
            if ev.get("location") and ev["location"] not in ent_ids:
                errors.append(f"event {ev['id']}: unknown location '{ev['location']}'")
            for s in ev["sources"]:
                if s["source_id"] not in src_ids:
                    errors.append(f"event {ev['id']}: unknown source '{s['source_id']}'")
        for r in relations:
            if r["source"] not in ent_ids:
                errors.append(f"relation {r['id']}: unknown source entity '{r['source']}'")
            if r["target"] not in ent_ids:
                errors.append(f"relation {r['id']}: unknown target entity '{r['target']}'")
            if r.get("event_id") and r["event_id"] not in event_ids:
                errors.append(f"relation {r['id']}: unknown event_id '{r['event_id']}'")
            for s in r["sources"]:
                if s["source_id"] not in src_ids:
                    errors.append(f"relation {r['id']}: unknown source '{s['source_id']}'")

        if errors:
            raise SystemExit("Validation failed for subject '%s':\n  " % slug + "\n  ".join(errors))

    return entities, events, relations, sources


def build(slug):
    print(f"Building '{slug}'...")
    subject = load(os.path.join(SUBJECTS_DIR, slug, "subject.json"))
    entities, events, relations, sources = validate_subject(slug)

    events_sorted = sorted(events, key=lambda e: (e["date"]["sort_start"], e["date"]["sort_end"]))

    payload = {
        "subject": subject,
        "entities": entities,
        "events": events_sorted,
        "relations": relations,
        "sources": sources,
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    # Safe to inline in a <script type="application/json"> block: escape "</" so
    # the JSON text can never prematurely close the surrounding <script> tag.
    data_json_safe = data_json.replace("</", "<\\/")

    tpl = open(TEMPLATE, encoding="utf-8").read()
    out = (tpl
           .replace("__SUBJECT_NAME__", html.escape(subject["name"]))
           .replace("__SUBJECT_SUMMARY__", html.escape(subject.get("summary", "")))
           .replace("__GRAPH_DATA_JSON__", data_json_safe))

    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"  {len(entities)} entities, {len(events)} events, {len(relations)} relations")
    print(f"  -> {out_path}")
    return out_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "--all":
        slugs = [d for d in os.listdir(SUBJECTS_DIR)
                 if os.path.isdir(os.path.join(SUBJECTS_DIR, d)) and not d.startswith("_")]
        for slug in sorted(slugs):
            build(slug)
    else:
        build(sys.argv[1])


if __name__ == "__main__":
    main()
