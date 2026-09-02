#!/usr/bin/env python3
"""
Attach verified Wikidata/Commons portraits to a subject's person entities.

    python3 scripts/find_portraits.py <slug> [--force] [--no-llm] [--no-build]

For every `person` entity without a portrait, searches Wikidata and — only
if identity can be confirmed — attaches a photo from Wikimedia Commons (a
stable Special:FilePath link, never embedded). A wrong photo is worse than
none, so anything short of confirmed is left blank.

Two ways identity gets confirmed (schema/entity.schema.json's
portrait.confidence):

  birth_year_verified   this subject's own events.json has a birth event
                         that matches Wikidata's P569 for exactly one
                         candidate. Purely mechanical, no LLM call.
  description_verified  no birth-year match to check against, so an LLM
                         judges whether a candidate's Wikidata description
                         is specific enough to confidently be this person
                         and not a namesake -- using whatever provider/
                         model/key build_site.py's --pdf mode already
                         uses, prompted for the first time it's actually
                         needed. Never if birth year alone settles it.

Pass --no-llm to skip the description tier entirely (no API key needed).
--force re-checks entities that already have a portrait.
"""
import argparse, getpass, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
import build_site as bs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBJECTS_DIR = os.path.join(ROOT, "subjects")
UA = "biograph-portrait-finder/1.0 (https://github.com/sciknoworg/biograph)"
CANDIDATE_LIMIT = 3  # top N Wikidata search results considered per person


def http_get_json(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"      (request to {url} failed: {e} — skipping)")
        return None


def wikidata_search(name):
    data = http_get_json("https://www.wikidata.org/w/api.php", {
        "action": "wbsearchentities", "search": name, "language": "en",
        "format": "json", "type": "item", "limit": CANDIDATE_LIMIT})
    return (data or {}).get("search", [])


def wikidata_entity(qid):
    data = http_get_json("https://www.wikidata.org/w/api.php", {
        "action": "wbgetentities", "ids": qid, "format": "json", "props": "claims|descriptions"})
    if not data or qid not in data.get("entities", {}):
        return None
    claims = data["entities"][qid].get("claims", {})

    def claim_value(prop):
        c = claims.get(prop)
        if not c or "datavalue" not in c[0]["mainsnak"]:
            return None
        return c[0]["mainsnak"]["datavalue"]["value"]

    birth, birth_year = claim_value("P569"), None
    if isinstance(birth, dict) and birth.get("time"):
        m = re.match(r"[+-](\d{4})", birth["time"])
        birth_year = int(m.group(1)) if m else None
    return {
        "qid": qid,
        "birth_year": birth_year,
        "image": claim_value("P18"),  # Commons filename string, or None
        "description": data["entities"][qid].get("descriptions", {}).get("en", {}).get("value", ""),
    }


def commons_imageinfo(filename):
    data = http_get_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "titles": f"File:{filename}", "prop": "imageinfo",
        "iiprop": "extmetadata", "format": "json"})
    if not data:
        return None
    page = next(iter(data["query"]["pages"].values()), {})
    meta = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})
    val = lambda k: meta.get(k, {}).get("value", "")
    return {
        "license": val("LicenseShortName") or val("License") or "unknown",
        "license_url": val("LicenseUrl"),
        "artist": re.sub(r"<[^>]+>", "", val("Artist")).strip(),
    }


def entity_birth_year(events, entity_id):
    for ev in events:
        if ev.get("event_type") == "birth" and any(p.get("entity_id") == entity_id for p in ev.get("participants", [])):
            m = re.match(r"(\d{4})", ev["date"]["sort_start"])
            if m:
                return int(m.group(1))
    return None


def judge_candidates(entity, candidates, ref_year, model, base_url, api_key):
    """Ask the model which candidate (if any) is confidently this person, not a
    namesake. The script — not the model — decides the resulting confidence
    tier, from whether a matching birth year was involved."""
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key)
    context = (f"this subject's own records give their birth year as {ref_year}, and every "
               f"candidate below already matches it — pick which one (if any) is genuinely them"
               if ref_year else
               "this subject's own records don't give a birth year to check against — judge "
               "purely by whether a candidate's description (occupation + era) is specific "
               "enough to confidently be this exact person, not a namesake")
    def candidate_line(c):
        born = f" (born {c['birth_year']})" if c["birth_year"] else ""
        return f'- qid "{c["qid"]}": "{c["description"]}"{born}'

    listing = "\n".join(candidate_line(c) for c in candidates)
    prompt = (
        f'Person: "{entity["name"]}". Summary: "{entity.get("summary", "")}". '
        f'Subtype: "{entity.get("subtype", "")}".\n\n'
        f"Wikidata candidates:\n{listing}\n\n"
        f"{context.capitalize()}. A wrong match is worse than no match — when unsure, say none "
        f'match. Reply with only this JSON: {{"qid": "<chosen qid, or null>", "reason": "one sentence"}}'
    )
    try:
        resp = client.chat.completions.create(
            model=model, temperature=0, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"})
        result = json.loads(resp.choices[0].message.content)
        return result.get("qid"), result.get("reason", "")
    except Exception as e:
        print(f"      (verification call failed: {e} — treating as no match)")
        return None, ""


def resolve_portrait(chosen, confidence):
    info = commons_imageinfo(chosen["image"])
    if not info or info["license"] == "unknown":
        return None  # never attach a photo we can't show a checkable license for
    filename = chosen["image"]
    return {
        "image_url": f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(filename)}?width=200",
        "source_url": f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(filename.replace(' ', '_'))}",
        "wikidata_qid": chosen["qid"],
        "license": info["license"],
        "license_url": info["license_url"],
        "artist": info["artist"],
        "confidence": confidence,
    }


def run(slug, base_url=None, model=None, api_key=None, no_llm=False, force=False, rebuild=True):
    sdir = os.path.join(SUBJECTS_DIR, slug)
    with open(os.path.join(sdir, "entities.json"), encoding="utf-8") as f:
        entities = json.load(f)
    with open(os.path.join(sdir, "events.json"), encoding="utf-8") as f:
        events = json.load(f)

    people = [e for e in entities if e.get("entity_type") == "person" and (force or "portrait" not in e)]
    if not people:
        print("No person entities need a portrait check (use --force to re-check existing ones).")
        return

    print(f"Checking {len(people)} people against Wikidata...")
    resolved, needs_llm = {}, {}  # entity id -> ({"chosen":..,"confidence":..} | (candidates, ref_year))
    for entity in people:
        print(f"  {entity['name']}...")
        names = [entity["name"]] + list(entity.get("aliases", []))
        raw = []
        for name in names:
            raw = wikidata_search(name)
            time.sleep(0.2)
            if raw:
                break
        if not raw:
            print("      no Wikidata match")
            continue

        candidates = []
        for r in raw:
            c = wikidata_entity(r["id"])
            time.sleep(0.2)
            if c and c["image"]:
                candidates.append(c)
        if not candidates:
            print("      no candidate has a Commons image")
            continue

        ref_year = entity_birth_year(events, entity["id"])
        matches = [c for c in candidates if ref_year and c["birth_year"] == ref_year]
        if ref_year and len(matches) == 1:
            resolved[entity["id"]] = (matches[0], "birth_year_verified", f"birth year {ref_year} matches")
        elif ref_year and not matches:
            print(f"      birth year on file ({ref_year}) doesn't match any candidate — skipping")
        elif no_llm:
            print("      needs LLM disambiguation, but --no-llm was passed — skipping")
        else:
            needs_llm[entity["id"]] = (entity, matches or candidates, ref_year)

    if needs_llm:
        if not (base_url and model and api_key):
            print(f"\n{len(needs_llm)} entit{'y needs' if len(needs_llm) == 1 else 'ies need'} an LLM "
                  f"judgment call to confirm identity:")
            base_url = base_url or bs.choose_base_url()
            model = model or bs.choose_model()
            api_key = api_key or getpass.getpass(f"API key for {base_url}: ")
        for entity_id, (entity, candidates, ref_year) in needs_llm.items():
            qid, reason = judge_candidates(entity, candidates, ref_year, model, base_url, api_key)
            if not qid:
                print(f"  {entity['name']}: no confident match ({reason or 'model found none specific enough'})")
                continue
            chosen = next((c for c in candidates if c["qid"] == qid), None)
            if not chosen:
                print(f"  {entity['name']}: model picked an unlisted qid — skipping")
                continue
            confidence = "birth_year_verified" if ref_year else "description_verified"
            resolved[entity_id] = (chosen, confidence, reason)
            print(f"  {entity['name']}: matched {qid} ({confidence}) — {reason}")

    attached = 0
    by_id = {e["id"]: e for e in entities}
    for entity_id, (chosen, confidence, why) in resolved.items():
        portrait = resolve_portrait(chosen, confidence)
        if not portrait:
            print(f"  {by_id[entity_id]['name']}: couldn't resolve Commons file info — skipping")
            continue
        by_id[entity_id]["portrait"] = portrait
        attached += 1
        if entity_id not in needs_llm:
            print(f"  {by_id[entity_id]['name']}: attached ({confidence}) — {why}")

    if attached:
        with open(os.path.join(sdir, "entities.json"), "w", encoding="utf-8") as f:
            json.dump(entities, f, indent=2, ensure_ascii=False)
            f.write("\n")
    print(f"\n{attached} portrait(s) attached, {len(people) - attached} left unverified.")

    if attached and rebuild:
        bs.build(slug)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--force", action="store_true", help="re-check entities that already have a portrait")
    ap.add_argument("--no-llm", action="store_true", help="birth-year matches only; never calls an LLM")
    ap.add_argument("--no-build", action="store_true", help="skip rebuilding dist/<slug>.html afterward")
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL"))
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"))
    ap.add_argument("--api-key", default=os.environ.get("BIOGRAPH_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    args = ap.parse_args()
    run(args.slug, base_url=args.base_url, model=args.model, api_key=args.api_key,
        no_llm=args.no_llm, force=args.force, rebuild=not args.no_build)


if __name__ == "__main__":
    main()
