#!/usr/bin/env python3
"""
Extract a new biograph subject from a PDF using an LLM.

Usage:
    python3 scripts/extract_subject.py <pdf_path> <slug> [--name "Display Name"]

Reads a source PDF straight through and asks an OpenAI-compatible chat
completion endpoint to draft entities.json / events.json / relations.json
/ sources.json / subject.json for it, against this repo's own
schema/*.schema.json (fed to the model verbatim, so the prompt can never
drift from the data model). If a reply gets cut off at the token limit
mid-subject, it automatically asks the model to continue and stitches the
pieces back together (bounded — see MAX_CONTINUATIONS), rather than
failing or silently losing data. Writes the result to subjects/<slug>/,
validates it, and — if it passes — builds dist/<slug>.html, exactly like
scripts/build_site.py does.

Works with any OpenAI-compatible endpoint: OpenAI itself, OpenRouter,
KISSKI, or anything else that speaks the same chat-completions API. No
provider or model is hardcoded — pick a provider, then type the exact
model name your provider currently offers (whatever that is today; model
lineups move fast and a baked-in default goes stale). Configure via flags
or environment variables to skip the prompts (e.g. in a script):

    BIOGRAPH_API_KEY / OPENAI_API_KEY   API key (prompted for if unset)
    BIOGRAPH_BASE_URL                   provider endpoint (prompted for if unset)
    BIOGRAPH_MODEL                      model name (prompted for if unset)

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

# (label, base_url) — base_url None means "ask the user to paste one" (e.g.
# KISSKI, or any other gateway, whose URL we don't want to guess and hardcode).
PROVIDERS = [
    ("OpenAI", "https://api.openai.com/v1"),
    ("OpenRouter", "https://openrouter.ai/api/v1"),
    ("Other (paste a base URL)", None),
]

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


MAX_CONTINUATIONS = 8  # hard cap on continuation round-trips, so a stuck model can't loop forever


def call_llm(system, user, model, base_url, api_key, max_tokens):
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def request(use_json_mode):
        kwargs = dict(model=model, temperature=0.2, max_tokens=max_tokens, messages=messages)
        if use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    full_content, rounds = "", 0
    while True:
        try:
            resp = request(use_json_mode=(rounds == 0))  # only ask for strict JSON mode on the
        except Exception:                                # first call — a mid-JSON continuation
            try:                                          # chunk isn't a complete object on its own,
                resp = request(use_json_mode=False)        # and some providers reject that in JSON mode.
            except Exception as e:
                sys.exit(f"Request to {base_url} failed for model '{model}': {e}\n\n"
                          f"Check that name is exactly what your provider lists for chat completions "
                          f"(this is usually a wrong/misspelled model name, a model your key can't access, "
                          f"or one that isn't a chat model on this endpoint) and try again.")
        choice = resp.choices[0]
        full_content += choice.message.content
        if getattr(choice, "finish_reason", None) != "length":
            break
        rounds += 1
        if rounds > MAX_CONTINUATIONS:
            sys.exit(f"Model's reply hit the {max_tokens}-token limit {MAX_CONTINUATIONS} times in a "
                      f"row and still isn't finished — that's an unusually large subject, a model "
                      f"that won't stop elaborating, or a --max-chars input too long for it to digest "
                      f"in one draft. Try a smaller --max-chars, or a higher --max-tokens per round.")
        print(f"  (reply hit the {max_tokens}-token limit — asking the model to continue, part {rounds + 1})")
        messages = messages + [{"role": "assistant", "content": choice.message.content},
                                {"role": "user", "content": "Continue the JSON exactly where you left "
                                 "off, character for character — no repetition of anything already "
                                 "written, no restarting, no markdown fences, no commentary."}]

    content = re.sub(r"^```(json)?|```$", "", full_content.strip(), flags=re.M).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        sys.exit(f"Model's assembled reply still wasn't valid JSON after {rounds} continuation(s) "
                  f"({e}). This usually means a continuation didn't pick up exactly where the last "
                  f"one left off. First 500 chars:\n{content[:500]}")
    if isinstance(data, str):  # some models double-encode: a JSON string containing JSON
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            pass
    if not isinstance(data, dict):
        sys.exit(f"Model's JSON wasn't an object at the top level (got {type(data).__name__}). "
                  f"First 500 chars:\n{content[:500]}")
    # Coerce each expected field to its right shape rather than trusting the model —
    # a wrong shape here should become an empty default, not a crash three lines later.
    if not isinstance(data.get("subject"), dict):
        data["subject"] = {}
    for key in ("entities", "events", "relations", "sources"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


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


def choose_base_url():
    print("Model provider:")
    for i, (label, _) in enumerate(PROVIDERS, 1):
        print(f"  {i}. {label}")
    choice = input(f"Choose [1-{len(PROVIDERS)}]: ").strip()
    try:
        label, url = PROVIDERS[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit(f"Invalid choice: {choice!r}")
    return url or input("Base URL: ").strip()


def choose_model():
    model = input("Model name, exactly as your provider lists it "
                   "(e.g. gpt-5.5, anthropic/claude-opus-4.6, meta-llama/llama-4-maverick): ").strip()
    return model or sys.exit("a model name is required")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf_path")
    ap.add_argument("slug")
    ap.add_argument("--name", help="Display name (default: slug, title-cased)")
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL"),
                     help="model name; prompted for if unset (no hardcoded default — pick current, not stale)")
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"),
                     help="provider API base URL; prompted for (provider, then base URL) if unset")
    ap.add_argument("--api-key", default=os.environ.get("BIOGRAPH_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    ap.add_argument("--max-chars", type=int, default=180_000, help="truncate source text beyond this many chars")
    ap.add_argument("--max-tokens", type=int, default=32_000,
                     help="max tokens for the model's reply — raise this if extraction fails with "
                          "a truncated-JSON error on a long/eventful source")
    ap.add_argument("--no-build", action="store_true", help="skip building dist/<slug>.html afterward")
    ap.add_argument("--portraits", action="store_true",
                     help="also run scripts/find_portraits.py on the new subject afterward "
                          "(Wikidata/Commons photo lookup — see that script's own --help)")
    args = ap.parse_args()

    if not re.match(r"^[a-z][a-z0-9_]*$", args.slug):
        sys.exit(f"slug must match ^[a-z][a-z0-9_]*$, got '{args.slug}'")
    base_url = args.base_url or choose_base_url()
    model = args.model or choose_model()
    api_key = args.api_key or getpass.getpass(f"API key for {base_url}: ")
    name = args.name or args.slug.replace("_", " ").title()

    print(f"Reading {args.pdf_path}...")
    text = pdf_text(args.pdf_path, args.max_chars)
    system, user = build_prompt(args.slug, name, text)

    print(f"Asking {model} to draft the graph ({len(text):,} chars of source text)...")
    data = call_llm(system, user, model, base_url, api_key, args.max_tokens)
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

    if args.portraits:
        print(f"\nLooking for verified portraits...")
        import find_portraits
        find_portraits.run(args.slug, base_url=base_url, model=model, api_key=api_key,
                            rebuild=not args.no_build)

    print(f"\nTreat this as a first-pass draft — review subjects/{args.slug}/*.json "
          f"against {args.pdf_path} before trusting it.")


if __name__ == "__main__":
    main()
