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
#: Wikimedia's user-agent policy asks automated clients to identify themselves and give a
#: contact route; ones that don't are throttled far harder. Same form as geocode_places.py's.
UA = ("biograph-portrait-finder/1.0 "
      "(https://github.com/sciknoworg/biograph; portraits for a research corpus) "
      "python-urllib")
CANDIDATE_LIMIT = 3  # top N Wikidata search results considered per name
MAX_CANDIDATES = 6   # ...and per person, across all their names, so aliases can't fan out

#: The pace geocode_places.py arrived at by measurement, for the same reason it needed one. A
#: fixed per-call sleep -- this file used 0.2s, and 0.35s already produced a 429 within five
#: lookups there -- forgets what the previous call just learned, so every request rediscovers
#: the limit and pays its own backoff. Wikimedia rate-limits anonymous clients with a 429
#: rather than by degrading, so the right response is to slow down and stay slow until
#: sustained success earns the pace back. One pace covers both endpoints below: the limit is
#: per-client, not per-host.
MIN_DELAY = 1.0
MAX_DELAY = 30.0
MAX_RETRIES = 6

_delay = MIN_DELAY
_ok_streak = 0


def http_get_json(url, params):
    """One Wikimedia API call at the current adaptive pace.

    Returns None rather than raising when the lookup can't be completed. No data means no
    portrait, and no portrait is this script's safe outcome -- a wrong photo is worse than
    none. Only the retryable codes are retried; anything else is a real answer, not congestion."""
    global _delay, _ok_streak
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": UA})
    for attempt in range(MAX_RETRIES):
        time.sleep(_delay)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            _ok_streak += 1
            if _ok_streak >= 10 and _delay > MIN_DELAY:      # ease back off cautiously
                _delay = max(MIN_DELAY, _delay * 0.8)
                _ok_streak = 0
            return data
        except urllib.error.HTTPError as e:                  # subclass of URLError: catch first
            if e.code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES - 1:
                print(f"      (request to {url} failed: {e} — skipping)")
                return None
            _ok_streak = 0
            _delay = min(MAX_DELAY, max(_delay * 1.8, 2.0))
            print("      (%s from Wikimedia — pace now %.1fs/request)" % (e.code, _delay))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"      (request to {url} failed: {e} — skipping)")
            return None
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
        # Reasoning models spend this budget thinking before they emit any content, and they
        # charge that thinking against max_tokens. At 300 -- enough for the answer alone -- a
        # measured run finished every single call with finish_reason "length" and empty
        # content, and the empty content was then indistinguishable from a considered "none of
        # these match". 62 people with obvious, unambiguous Wikidata items (Boyle, Priestley,
        # Perutz) were rejected that way. The same call at 2,000 answers correctly in ~880.
        resp = client.chat.completions.create(
            model=model, temperature=0, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"})
        choice = resp.choices[0]
        content = (choice.message.content or "").strip()
        if not content:
            # Never silently downgrade this to "no match": a reply that never arrived is not
            # evidence about identity, and treating it as one loses portraits invisibly.
            print(f"      (no verdict returned -- finish_reason={choice.finish_reason}"
                  f"{', raise max_tokens' if choice.finish_reason == 'length' else ''} "
                  f"-- leaving unverified)")
            return None, ""
        result = json.loads(content)
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


def run(slug, base_url=None, model=None, api_key=None, no_llm=False, force=False, rebuild=True,
        subject_only=False):
    """Attach portraits for every document folder belonging to this subject.

    A subject holds one folder per source document (see bs.subject_documents), each with its own
    entities.json, so portraits are resolved per document and written back where they were read
    -- the same person appearing in two papers gets a portrait in each, and neither file is
    rewritten from the other's data."""
    docs = bs.subject_documents(slug)
    if not docs:
        sys.exit(f"subjects/{slug}/ has no document folders to attach portraits to.")
    only = subject_identity(slug) if subject_only else None
    if subject_only and only is None:
        print(f"  ({slug} has no subject.json to identify the biographee -- checking everyone)")
    for i, (doc_key, ddir) in enumerate(docs):
        if doc_key and len(docs) > 1:
            print(f"\n-- {slug}/{doc_key} --")
        run_document(slug, ddir, base_url=base_url, model=model, api_key=api_key,
                     no_llm=no_llm, force=force, only=only,
                     rebuild=rebuild and i == len(docs) - 1)  # render once, after the last one


def _fold(s):
    return " ".join(str(s).casefold().split())


#: Titles and post-nominals, stripped before matching a subject to its own entity. subject.json
#: takes its name from whatever the source called the person, and a source may be formal where
#: the extraction is plain: Hodgkin is "Professor Sir Alan Hodgkin OM, FRS" in one and "Alan
#: Hodgkin" in the other, which is the same human by any reading but no string match at all.
NOT_NAME_TOKENS = {
    "professor", "prof", "sir", "dame", "dr", "doctor", "lord", "lady", "rev", "reverend",
    "mr", "mrs", "ms", "baron", "count", "the", "hon",
    "om", "frs", "frse", "kbe", "cbe", "obe", "mbe", "gbe", "phd", "md", "dsc", "dphil",
    "fba", "frcp", "facs", "ma", "msc", "bsc", "ba", "lld", "jr", "sr", "ii", "iii", "iv",
}


def _core_name(s):
    """A name reduced to the parts that actually identify a person."""
    tokens = [t for t in re.split(r"[\s,.]+", _fold(s)) if t and t not in NOT_NAME_TOKENS]
    return " ".join(tokens)


def _name_keys(*values):
    """Every form a name might be matched by: as written, and stripped of honorifics."""
    keys = set()
    for v in values:
        if not v:
            continue
        keys.add(_fold(v))
        core = _core_name(v)
        if core:
            keys.add(core)
    return keys


def subject_identity(slug):
    """The folded id/name/aliases of the person a subject is *about*, from subject.json.

    Needed because a document's person entities are everyone the document mentions -- mostly
    colleagues, rivals and relatives who appear once. Those are exactly the cases where a
    namesake is hardest to rule out and a wrong face does the most damage, so --subject-only
    spends lookups on the biographee alone. Returns None when subject.json is missing, which
    the caller treats as "no restriction possible" rather than "match nothing"."""
    path = os.path.join(bs.subject_dir_for(slug), "subject.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        subject = json.load(f)
    return _name_keys(subject.get("id"), subject.get("name"), *(subject.get("aliases") or []))


def run_document(slug, sdir, base_url=None, model=None, api_key=None, no_llm=False,
                 force=False, rebuild=True, only=None):
    with open(os.path.join(sdir, "entities.json"), encoding="utf-8") as f:
        entities = json.load(f)
    with open(os.path.join(sdir, "events.json"), encoding="utf-8") as f:
        events = json.load(f)

    people = [e for e in entities if e.get("entity_type") == "person" and (force or "portrait" not in e)]
    if only is not None:
        def is_the_subject(e):
            return bool(_name_keys(e.get("id"), e.get("name"), *(e.get("aliases") or [])) & only)
        people = [e for e in people if is_the_subject(e)]
    if not people:
        print("No person entities need a portrait check (use --force to re-check existing ones).")
        return

    print(f"Checking {len(people)} people against Wikidata...")
    resolved, needs_llm = {}, {}  # entity id -> ({"chosen":..,"confidence":..} | (candidates, ref_year))
    for entity in people:
        print(f"  {entity['name']}...")
        # Search every name this person is known by, not just the first one that returns
        # anything. A search can return confident-looking wrong people -- "F. A. Abel" resolves
        # to an American baseball executive -- and stopping at the first non-empty result meant
        # the alias that actually identifies them ("Sir Frederick Abel", born 1827, an exact
        # match on file) was never tried. Deduped by qid, since aliases overlap.
        seen_qids, raw = set(), []
        for name in [entity["name"]] + list(entity.get("aliases", [])):
            for r in wikidata_search(name):
                if r["id"] not in seen_qids:
                    seen_qids.add(r["id"])
                    raw.append(r)
            if len(raw) >= MAX_CANDIDATES:
                break
        raw = raw[:MAX_CANDIDATES]
        if not raw:
            print("      no Wikidata match")
            continue

        candidates = []
        for r in raw:
            c = wikidata_entity(r["id"])
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
    ap.add_argument("--subject-only", action="store_true",
                    help="check only the person this subject is about, not everyone the "
                         "documents mention")
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL"))
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"))
    ap.add_argument("--api-key", default=os.environ.get("BIOGRAPH_API_KEY"))
    args = ap.parse_args()
    run(args.slug, base_url=args.base_url, model=args.model, api_key=args.api_key,
        no_llm=args.no_llm, force=args.force, rebuild=not args.no_build,
        subject_only=args.subject_only)


if __name__ == "__main__":
    main()
