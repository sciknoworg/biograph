#!/usr/bin/env python3
"""
Build a biograph subject: optionally draft it from a PDF via an LLM, then
validate it and render dist/<slug>.html.

    python3 scripts/build_site.py <slug>                     build existing subjects/<slug>/
    python3 scripts/build_site.py --all                       build every subject
    python3 scripts/build_site.py <slug> --pdf <paper.pdf>    draft from a PDF first, then build

With --pdf: reads the PDF and asks a chat model, via an OpenAI-compatible
API (OpenRouter, KISSKI, or any other gateway speaking that format), to
draft entities/events/relations/sources against schema/*.schema.json,
embedded in the prompt verbatim so it can't drift from the data model.
Prompts for provider, model, and API key (or set
--base-url/--model/--api-key, or the matching BIOGRAPH_* env vars, to
skip the prompts). A reply that hits the token limit is automatically
continued rather than left truncated.

Either way, the result is validated against schema/ (structure and
referential integrity) before it's inlined into frontend/template.html.

Optional next step: python3 scripts/find_portraits.py <slug> to attach
verified Wikidata/Commons photos.

Treat an LLM-drafted subject as a first-pass draft, not ground truth —
review it against the PDF before trusting it. See extraction/EXTRACTION_GUIDE.md.
"""
import argparse, getpass, html, json, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(ROOT, "schema")
SUBJECTS_DIR = os.path.join(ROOT, "subjects")
DATA_DIR = os.path.join(ROOT, "data")
TEMPLATE = os.path.join(ROOT, "frontend", "template.html")
WORLD_GEOJSON = os.path.join(ROOT, "frontend", "world-countries.geo.json")
DIST_DIR = os.path.join(ROOT, "dist")
SCHEMA_FILES = ["date", "entity", "event", "relation", "source"]

# ---------------------------------------------------------------- extraction

PROVIDERS = [  # (label, base_url) -- None means "ask the user to paste one" (e.g. KISSKI)
    ("OpenRouter", "https://openrouter.ai/api/v1"),
    ("Other (paste a base URL)", None),
]

RULES = """\
Rules, non-negotiable:
- Every fact must trace to the text: no inference from general knowledge, no filling gaps.
- An event needs a date (however fuzzy), an event_type, >=1 participant, >=1 source citation --
  and every citation needs a page number (sources[].page: the source's own printed page if
  shown, else the nearest "[pdf page N]" marker). Provenance is exactly where in the text this
  came from, and it is not optional. date.display should quote the source's own wording
  ("early 1970s"); precision and sort_start/sort_end encode that same fuzziness as an ISO
  range -- never a false-precise exact date for a vague one.
- Quote sparingly -- only the load-bearing sentence for pivotal events, in sources[].quote.
- Keep entities[].summary and events[].label terse and scannable: an expert should read a
  label alone and know what happened ("Moved to Texas Instruments"), not a full sentence
  explaining why. Save extra context for description -- at most one tight sentence, and only
  if the label doesn't already say it.
- ids: snake_case, derived from the name/label, unique within their file.
- entities[].summary is static facts only -- a sentence with a "when" is an event, not a summary.
- Capture connective-tissue events too (an organization founded/sold, a collaborator's
  milestone), not just the subject's own life events. Don't split one episode into many
  events, or merge distinct moments into one.
- relations[] follow the schema's fixed reading direction (e.g. worked_at always reads
  person -> organization). Add one for every event implying a durable connection, linked
  via event_id; add standalone ones (no event_id) for facts stated without a specific date.
- If nothing in an enum fits, use "other" and explain in the description.
- Output ONLY the JSON object -- no markdown fences, no commentary.
"""


def pdf_text(path, max_chars):
    from pypdf import PdfReader
    text = "".join(f"\n\n[pdf page {i}]\n{p.extract_text() or ''}"
                    for i, p in enumerate(PdfReader(path).pages, 1))
    if len(text) > max_chars:
        print(f"  (PDF text is {len(text):,} chars, truncating to {max_chars:,} "
              f"-- raise with --max-chars if your model's context allows more)")
        text = text[:max_chars]
    return text


def build_prompt(slug, name, text):
    schemas = {fn: json.load(open(os.path.join(SCHEMA_DIR, f"{fn}.schema.json"), encoding="utf-8"))
               for fn in SCHEMA_FILES}
    system = (
        "You are extracting a biographical knowledge graph from a source document.\n"
        "Output a single JSON object with exactly five top-level keys: subject, entities, "
        "events, relations, sources. Every object in entities/events/relations/sources must "
        "validate against the matching JSON Schema below (draft 2020-12).\n\n"
        + "\n\n".join(f"{fn}.schema.json:\n{json.dumps(schemas[fn])}" for fn in SCHEMA_FILES)
        + "\n\n" + RULES
    )
    user = (f'subject.json: {{"slug": "{slug}", "name": "{name}", "summary": "<one line>"}}\n\n'
            "Source document text (page markers inserted as [pdf page N]):\n\n" + text)
    return system, user


def call_llm(system, user, model, base_url, api_key, max_tokens, max_continuations=8):
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def request(json_mode):
        kwargs = dict(model=model, temperature=0.2, max_tokens=max_tokens, messages=messages)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    full, rounds = "", 0
    while True:
        try:
            resp = request(json_mode=(rounds == 0))
        except Exception:
            try:
                resp = request(json_mode=False)  # a mid-JSON continuation isn't valid JSON on its own
            except Exception as e:
                sys.exit(f"Request to {base_url} failed for model '{model}': {e}\n\n"
                          f"Check the model name is exactly what your provider lists for chat "
                          f"completions and that your key can access it.")
        choice = resp.choices[0]
        full += choice.message.content
        if getattr(choice, "finish_reason", None) != "length":
            break
        rounds += 1
        if rounds > max_continuations:
            sys.exit(f"Reply hit the {max_tokens}-token limit {max_continuations} times in a row "
                      f"and still isn't finished. Try a smaller --max-chars or larger --max-tokens.")
        print(f"  (reply hit the {max_tokens}-token limit -- asking the model to continue, part {rounds + 1})")
        messages = messages + [{"role": "assistant", "content": choice.message.content},
                                {"role": "user", "content": "Continue the JSON exactly where you left "
                                 "off, character for character -- no repetition, no restarting, "
                                 "no markdown fences, no commentary."}]

    content = re.sub(r"^```(json)?|```$", "", full.strip(), flags=re.M).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        sys.exit(f"Model's reply wasn't valid JSON after {rounds} continuation(s) ({e}). "
                  f"First 500 chars:\n{content[:500]}")
    if isinstance(data, str):  # some models double-encode: a JSON string containing JSON
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            pass
    if not isinstance(data, dict):
        sys.exit(f"Model's JSON wasn't an object at the top level (got {type(data).__name__}).")
    if not isinstance(data.get("subject"), dict):
        data["subject"] = {}
    for key in ("entities", "events", "relations", "sources"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def stage_pdf(pdf_path, slug):
    """Ensure the PDF lives under data/; return its path relative to the repo root."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.dirname(os.path.abspath(pdf_path)) == os.path.abspath(DATA_DIR):
        return os.path.join("data", os.path.basename(pdf_path))
    dest = os.path.join(DATA_DIR, f"{slug}.pdf")
    shutil.copyfile(pdf_path, dest)
    return os.path.join("data", f"{slug}.pdf")


def choose_base_url():
    print("Model provider:")
    for i, (label, _) in enumerate(PROVIDERS, 1):
        print(f"  {i}. {label}")
    choice = input(f"Choose [1-{len(PROVIDERS)}]: ").strip()
    try:
        _, url = PROVIDERS[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit(f"Invalid choice: {choice!r}")
    return url or input("Base URL: ").strip()


def choose_model():
    model = input("Model name, exactly as your provider lists it "
                   "(e.g. gpt-5.5, anthropic/claude-opus-4.6, meta-llama/llama-4-maverick): ").strip()
    return model or sys.exit("a model name is required")


def extract(pdf_path, slug, name, model, base_url, api_key, max_chars, max_tokens):
    print(f"Reading {pdf_path}...")
    text = pdf_text(pdf_path, max_chars)
    system, user = build_prompt(slug, name, text)
    print(f"Asking {model} to draft the graph ({len(text):,} chars of source text)...")
    data = call_llm(system, user, model, base_url, api_key, max_tokens)
    data["subject"]["slug"] = slug
    data["subject"].setdefault("name", name)
    file_rel = stage_pdf(pdf_path, slug)
    if data["sources"]:
        data["sources"][0]["file"] = file_rel  # trust our own copy, not the model's guess

    sdir = os.path.join(SUBJECTS_DIR, slug)
    os.makedirs(sdir, exist_ok=True)
    for fname, payload in [("subject.json", data["subject"]), ("entities.json", data["entities"]),
                            ("events.json", data["events"]), ("relations.json", data["relations"]),
                            ("sources.json", data["sources"])]:
        with open(os.path.join(sdir, fname), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
    print(f"  wrote subjects/{slug}/ ({len(data['entities'])} entities, {len(data['events'])} events, "
          f"{len(data['relations'])} relations, {len(data['sources'])} sources)")


# ---------------------------------------------------------------- validate + build

# Fixed reading direction for every relation.schema.json type: (allowed source
# entity_types, allowed target entity_types). Keep in sync with that enum --
# see schema/README.md "Extending the vocabularies".
RELATION_DIRECTIONS = {
    "born_in": (("person",), ("place",)),
    "died_in": (("person",), ("place",)),
    "lived_in": (("person",), ("place",)),
    "visited": (("person",), ("place",)),
    "relocated_to": (("person",), ("place",)),
    "worked_at": (("person",), ("organization",)),
    "employed_by": (("person",), ("organization",)),
    "founded": (("person", "organization"), ("organization",)),
    "member_of": (("person", "organization"), ("organization",)),
    "supervised_by": (("person",), ("person",)),
    "mentored": (("person",), ("person",)),
    "collaborated_with": (("person",), ("person", "organization")),
    "met": (("person",), ("person",)),
    "married_to": (("person",), ("person",)),
    "family_of": (("person",), ("person",)),
    "studied_at": (("person",), ("organization",)),
    "educated_by": (("person",), ("person",)),
    "invented": (("person", "organization"), ("artifact",)),
    "patented": (("person", "organization"), ("artifact",)),
    "published": (("person", "organization"), ("artifact",)),
    "developed": (("person", "organization"), ("artifact",)),
    "awarded": (("person", "organization"), ("artifact",)),
    "licensed_to": (("organization",), ("organization",)),
    "acquired_by": (("organization",), ("organization",)),
    "sold_to": (("organization",), ("organization",)),
    "renamed_to": (("organization",), ("organization",)),
    "corresponded_with": (("person",), ("person",)),
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_subject(slug):
    """Validate the subject's four data files against the JSON Schemas.
    Returns (entities, events, relations, sources). Raises on any error."""
    try:
        from jsonschema import Draft202012Validator, RefResolver
    except ImportError:
        print("  (jsonschema not installed -- skipping schema validation; "
              "pip install jsonschema to enable it)")
        Draft202012Validator = None

    sdir = os.path.join(SUBJECTS_DIR, slug)
    entities = load(os.path.join(sdir, "entities.json"))
    events = load(os.path.join(sdir, "events.json"))
    relations = load(os.path.join(sdir, "relations.json"))
    sources = load(os.path.join(sdir, "sources.json"))

    if Draft202012Validator:
        store = {}
        for fn in SCHEMA_FILES:
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

        ent_ids = {e["id"] for e in entities}
        ent_type = {e["id"]: e["entity_type"] for e in entities}
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
            src_ok, tgt_ok = r["source"] in ent_ids, r["target"] in ent_ids
            if not src_ok:
                errors.append(f"relation {r['id']}: unknown source entity '{r['source']}'")
            if not tgt_ok:
                errors.append(f"relation {r['id']}: unknown target entity '{r['target']}'")
            if src_ok and tgt_ok:  # both resolve -- check the vocabulary's fixed reading direction
                exp_src, exp_tgt = RELATION_DIRECTIONS.get(r["type"], ((), ()))
                got_src, got_tgt = ent_type[r["source"]], ent_type[r["target"]]
                if exp_src and got_src not in exp_src:
                    errors.append(f"relation {r['id']}: '{r['type']}' expects source entity_type "
                                  f"{'/'.join(exp_src)}, but '{r['source']}' is '{got_src}'")
                if exp_tgt and got_tgt not in exp_tgt:
                    errors.append(f"relation {r['id']}: '{r['type']}' expects target entity_type "
                                  f"{'/'.join(exp_tgt)}, but '{r['target']}' is '{got_tgt}'")
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

    payload = {"subject": subject, "entities": entities, "events": events_sorted,
               "relations": relations, "sources": sources}
    data_json_safe = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    with open(WORLD_GEOJSON, encoding="utf-8") as f:
        world_json_safe = f.read().replace("</", "<\\/")

    out = (open(TEMPLATE, encoding="utf-8").read()
           .replace("__SUBJECT_NAME__", html.escape(subject["name"]))
           .replace("__SUBJECT_SUMMARY__", html.escape(subject.get("summary", "")))
           .replace("__GRAPH_DATA_JSON__", data_json_safe)
           .replace("__WORLD_TOPOJSON_JSON__", world_json_safe))

    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"  {len(entities)} entities, {len(events)} events, {len(relations)} relations")
    print(f"  -> {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--all", action="store_true", help="build every subject under subjects/")
    ap.add_argument("--pdf", help="draft the subject from this PDF before building")
    ap.add_argument("--name", help="display name for --pdf (default: slug, title-cased)")
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL"), help="for --pdf; prompted if unset")
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"), help="for --pdf; prompted if unset")
    ap.add_argument("--api-key", default=os.environ.get("BIOGRAPH_API_KEY"))
    ap.add_argument("--max-chars", type=int, default=180_000, help="for --pdf: truncate source text beyond this")
    ap.add_argument("--max-tokens", type=int, default=32_000, help="for --pdf: reply budget per request")
    args = ap.parse_args()

    if args.all:
        slugs = sorted(d for d in os.listdir(SUBJECTS_DIR)
                        if os.path.isdir(os.path.join(SUBJECTS_DIR, d)) and not d.startswith("_"))
        for slug in slugs:
            build(slug)
        return
    if not args.slug:
        ap.error("provide a subject slug, or --all")

    if args.pdf:
        if not re.match(r"^[a-z][a-z0-9_]*$", args.slug):
            sys.exit(f"slug must match ^[a-z][a-z0-9_]*$, got '{args.slug}'")
        base_url = args.base_url or choose_base_url()
        model = args.model or choose_model()
        api_key = args.api_key or getpass.getpass(f"API key for {base_url}: ")
        name = args.name or args.slug.replace("_", " ").title()
        extract(args.pdf, args.slug, name, model, base_url, api_key, args.max_chars, args.max_tokens)

    try:
        build(args.slug)
    except SystemExit as e:
        if not args.pdf:
            raise
        sys.exit(f"\n{e}\n\nThis is a first-pass draft -- fix the errors above in "
                  f"subjects/{args.slug}/*.json (or re-run) before building. "
                  f"See extraction/EXTRACTION_GUIDE.md for the data model.")

    if args.pdf:
        print(f"\nTreat this as a first-pass draft -- review subjects/{args.slug}/*.json "
              f"against {args.pdf} before trusting it.")


if __name__ == "__main__":
    main()
