#!/usr/bin/env python3
"""
Extract a new biograph subject from a PDF using an LLM.

Usage:
    python3 scripts/extract_subject.py <pdf_path> <slug> [--name "Display Name"]

Reads a source PDF straight through and asks an OpenAI-compatible chat
completion endpoint to draft entities.json / events.json / relations.json
/ sources.json / subject.json for it, against this repo's own
schema/*.schema.json (fed to the model verbatim, so the prompt can never
drift from the data model). Writes them to subjects/<slug>/, validates
them, and — if they pass — builds dist/<slug>.html, exactly like
scripts/build_site.py does.

Works with any OpenAI-compatible endpoint: OpenAI itself, OpenRouter,
KISSKI, or anything else that speaks the same chat-completions API.
Configure via flags or environment variables:

    BIOGRAPH_API_KEY / OPENAI_API_KEY   API key (prompted for if unset)
    BIOGRAPH_BASE_URL                   default: https://api.openai.com/v1
    BIOGRAPH_MODEL                      default: gpt-4o

Treat the result as a first-pass draft, not ground truth — review it
against the PDF before trusting it. See extraction/EXTRACTION_GUIDE.md.
"""
import argparse, getpass, json, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
SCHEMA_DIR = os.path.join(ROOT, "schema")
SUBJECTS_DIR = os.path.join(ROOT, "subjects")
DATA_DIR = os.path.join(ROOT, "data")
SCHEMA_FILES = ["date", "entity", "event", "relation", "source"]

RULES = """\
Rules, non-negotiable:
- Every fact must trace to the text. If the paper doesn't say it, don't
  include it — no inference from general knowledge, no filling gaps.
- An event needs a date (however fuzzy), an event_type, >=1 participant,
  and >=1 source citation. A date's `display` should quote the source's
  own wording ("early 1970s"); `precision` and `sort_start`/`sort_end`
  encode that same fuzziness as an ISO range — never invent a false-precise
  exact date for a vague one.
- Quote sparingly, but quote the load-bearing sentence for pivotal events
  (the invention moment, the first disclosure) in sources[].quote, with
  the printed page number if the text shows one, else the nearest
  "[pdf page N]" marker.
- entity/event/relation ids: snake_case, derived from the name/label,
  unique within their file. Don't reuse an id across files.
- entities[].summary is static facts only (no dates — if a sentence has a
  "when," it's an event, not a summary clause).
- Capture connective-tissue events too (an organization founded/sold, a
  collaborator's milestone), not just the subject's own life events.
- Don't split one coherent episode into many events, and don't merge
  distinct dateable moments into one.
- relations[] follow the schema's fixed reading direction (e.g. worked_at
  always reads person -> organization). Add a relation for every event
  that implies a durable connection (employment, invention, founding),
  linked back via event_id; add standalone relations (no event_id) for
  facts stated without a specific date ("they remained lifelong friends").
- If nothing in an enum fits, use "other" (events) and explain in the
  description, rather than inventing a new vocabulary value.
- Output ONLY the JSON object. No markdown fences, no commentary.
"""


def pdf_text(path, max_chars):
    from pypdf import PdfReader
    reader = PdfReader(path)
    parts = [f"\n\n[pdf page {i}]\n{page.extract_text() or ''}"
             for i, page in enumerate(reader.pages, 1)]
    text = "".join(parts)
    if len(text) > max_chars:
        print(f"  (PDF text is {len(text):,} chars, truncating to {max_chars:,} "
              f"— raise with --max-chars if your model's context allows more)")
        text = text[:max_chars]
    return text


def build_prompt(slug, name, text):
    schemas = {fn: json.load(open(os.path.join(SCHEMA_DIR, f"{fn}.schema.json"), encoding="utf-8"))
               for fn in SCHEMA_FILES}
    system = (
        "You are extracting a biographical knowledge graph from a source document.\n"
        "Output a single JSON object with exactly five top-level keys: subject, "
        "entities, events, relations, sources. Every object in entities/events/"
        "relations/sources must validate against the matching JSON Schema below "
        "(draft 2020-12) — same field names, same enums, nothing extra.\n\n"
        + "\n\n".join(f"{fn}.schema.json:\n{json.dumps(schemas[fn])}" for fn in SCHEMA_FILES)
        + "\n\n" + RULES
    )
    user = (
        f'subject.json: {{"slug": "{slug}", "name": "{name}", "summary": "<one line>"}}\n\n'
        "Source document text (page markers inserted as [pdf page N]):\n\n" + text
    )
    return system, user


def call_llm(system, user, model, base_url, api_key, max_tokens):
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key)
    kwargs = dict(model=model, temperature=0.2, max_tokens=max_tokens,
                  messages=[{"role": "system", "content": system},
                            {"role": "user", "content": user}])
    try:
        resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception:
        resp = client.chat.completions.create(**kwargs)  # endpoint may not support response_format
    content = re.sub(r"^```(json)?|```$", "", resp.choices[0].message.content.strip(), flags=re.M).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        sys.exit(f"Model did not return valid JSON ({e}). First 500 chars:\n{content[:500]}")


def stage_pdf(pdf_path, slug):
    """Ensure the PDF lives under data/; return its path relative to the repo root."""
    os.makedirs(DATA_DIR, exist_ok=True)
    abspdf = os.path.abspath(pdf_path)
    if os.path.dirname(abspdf) == os.path.abspath(DATA_DIR):
        return os.path.join("data", os.path.basename(abspdf))
    dest = os.path.join(DATA_DIR, f"{slug}.pdf")
    shutil.copyfile(pdf_path, dest)
    return os.path.join("data", f"{slug}.pdf")


def write_subject(slug, data):
    sdir = os.path.join(SUBJECTS_DIR, slug)
    os.makedirs(sdir, exist_ok=True)
    files = {"subject.json": data.get("subject", {}), "entities.json": data.get("entities", []),
             "events.json": data.get("events", []), "relations.json": data.get("relations", []),
             "sources.json": data.get("sources", [])}
    for fname, payload in files.items():
        with open(os.path.join(sdir, fname), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf_path")
    ap.add_argument("slug")
    ap.add_argument("--name", help="Display name (default: slug, title-cased)")
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL", "gpt-4o"))
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL", "https://api.openai.com/v1"))
    ap.add_argument("--api-key", default=os.environ.get("BIOGRAPH_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    ap.add_argument("--max-chars", type=int, default=180_000, help="truncate source text beyond this many chars")
    ap.add_argument("--max-tokens", type=int, default=16_000, help="max tokens for the model's reply")
    ap.add_argument("--no-build", action="store_true", help="skip building dist/<slug>.html afterward")
    args = ap.parse_args()

    if not re.match(r"^[a-z][a-z0-9_]*$", args.slug):
        sys.exit(f"slug must match ^[a-z][a-z0-9_]*$, got '{args.slug}'")
    api_key = args.api_key or getpass.getpass(f"API key for {args.base_url}: ")
    name = args.name or args.slug.replace("_", " ").title()

    print(f"Reading {args.pdf_path}...")
    text = pdf_text(args.pdf_path, args.max_chars)
    system, user = build_prompt(args.slug, name, text)

    print(f"Asking {args.model} to draft the graph ({len(text):,} chars of source text)...")
    data = call_llm(system, user, args.model, args.base_url, api_key, args.max_tokens)
    data.setdefault("subject", {})
    data["subject"]["slug"] = args.slug
    data["subject"].setdefault("name", name)
    file_rel = stage_pdf(args.pdf_path, args.slug)
    if data.get("sources"):
        data["sources"][0]["file"] = file_rel  # trust our own copy, not the model's guess

    write_subject(args.slug, data)
    print(f"  wrote subjects/{args.slug}/ ({len(data.get('entities', []))} entities, "
          f"{len(data.get('events', []))} events, {len(data.get('relations', []))} relations, "
          f"{len(data.get('sources', []))} sources)")

    import build_site
    try:
        build_site.validate_subject(args.slug)
    except SystemExit as e:
        sys.exit(f"\n{e}\n\nThis is a first-pass draft — fix the errors above in "
                  f"subjects/{args.slug}/*.json (or re-run) before building. "
                  f"See extraction/EXTRACTION_GUIDE.md for the data model.")
    print("  validation passed")

    if not args.no_build:
        build_site.build(args.slug)

    print(f"\nTreat this as a first-pass draft — review subjects/{args.slug}/*.json "
          f"against {args.pdf_path} before trusting it.")


if __name__ == "__main__":
    main()
