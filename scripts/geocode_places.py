#!/usr/bin/env python3
"""Fill in map coordinates for `place` entities, from Wikidata.

Why this is a separate pass rather than part of extraction: the frontend's map view plots only
place entities carrying numeric `attributes.lat`/`lng` (see frontend/template.html), and the
extraction model must never supply those. Coordinates recalled from training are exactly the
kind of unsourced fact RULES forbids everywhere else, and a plausible-looking wrong pin is
worse than no pin -- the same reasoning that makes portraits a verified lookup rather than a
model output (schema/README.md, "Portraits").

So coordinates come from Wikidata's P625, keyed to a specific item whose QID is recorded
alongside them. Any pin on the map can be checked by opening its item.

Identification is deliberately conservative, because "Cambridge" is a real place twice over:

  * the candidate item must itself have a P625 -- which alone discards the songs, albums,
    films and people that share a place's name;
  * its label or one of its aliases must match the entity's name exactly (case- and
    accent-insensitively) -- a substring match would accept "Maida Vale tube station"
    for "Maida Vale".

Survivors are then ranked by three rules in order, and which one decided it is recorded on the
entity as `attributes.geocode_basis`, so the weakest calls are the ones a reader can go and
audit:

  * `country` -- the entity recorded its own `attributes.country` and an item's P17 agreed.
    Strongest, and the only one that is also a filter: the extraction asserted that country
    from the document, so if nothing matches it the place is left off rather than resolved by
    a weaker rule. (An item with no P17 at all is compatible with anything, which is how
    countries themselves pass.)
  * `document` -- the winner's country is one this *same document* already places the subject
    in. Berthollet's paper names France, Savoy, Egypt and Italy, so its "Paris" is the French
    one; a paper about MIT that never mentions England would take Cambridge, Massachusetts.
    This is the disambiguator that actually matters for a biographical corpus, and it is free:
    the context comes from the extraction itself.
  * `most_linked` -- nothing in the document distinguished them, so the item with the most
    Wikipedia editions wins. That is a real guess, which is why it is labelled: "Paris" with
    no other signal should be the French one, but the label is what makes that checkable
    rather than invisible.

A place that matches nothing keeps working everywhere else -- graph, timeline, relations. It
just doesn't appear on the map, which is the honest rendering of "we don't know where".

Usage:
    python scripts/geocode_places.py                  # every subject
    python scripts/geocode_places.py --dry-run        # look up, write nothing
    python scripts/geocode_places.py --subject turing
    python scripts/geocode_places.py --domain computer_science
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

import build_site as bs

API = "https://www.wikidata.org/w/api.php"

#: Wikimedia's user-agent policy asks automated clients to identify themselves and to give a
#: contact route; requests that don't are throttled far harder, which is what a run with a
#: bare product name actually ran into (429s escalating to a 21s pace within 20 lookups).
USER_AGENT = ("biograph-geocoder/1.0 "
              "(https://github.com/sciknoworg/biograph; place coordinates for a research corpus) "
              "python-urllib")

#: Measured, not guessed: 0.35s produced a 429 within five lookups, and a fixed 1.1s still
#: 429'd on most calls -- costing three backoff sleeps *per call* because a per-call delay
#: forgets what the last call just learned. So the pace is adaptive and module-level: it rises
#: on every 429 and decays back down only after sustained success, which settles on whatever
#: rate the service is actually willing to serve instead of rediscovering the limit each time.
MIN_DELAY = 1.0
MAX_DELAY = 30.0
MAX_RETRIES = 6

_delay = MIN_DELAY
_ok_streak = 0

CACHE_PATH = os.path.join(bs.ROOT, ".geocode_cache.json")

#: Bump when a change alters what lookup_candidates() stores, so a stale cache is refetched
#: instead of quietly serving results the current rules would never have produced.
CACHE_VERSION = 2

#: Historical biography is multilingual by nature: Haber was born in Breslau, which Wikidata
#: knows as Wroclaw with "Breslau" only as its *German* label -- so an English-only name match
#: skipped the city entirely and resolved him to Breslau, Nebraska (population ~30) instead.
#: These are the languages a European history-of-science corpus actually needs, kept to a list
#: rather than fetching all ~300 so the response stays small and the match stays defensible.
NAME_LANGUAGES = ("en|de|fr|it|es|pl|ru|nl|sv|da|nb|fi|cs|hu|la|pt|el|tr|ja|zh|uk|ro|ca")


def _fold(s):
    """Casefold and strip accents, so 'Zurich' matches 'Zurich' with an umlaut."""
    flattened = "".join(c for c in unicodedata.normalize("NFKD", str(s))
                        if not unicodedata.combining(c))
    return " ".join(flattened.casefold().split())


def _get(params):
    """One API call, serialised and backing off on 429 -- Wikidata rate-limits anonymous
    clients and says so with a 429 rather than by degrading, so a retry is the correct
    response and hammering through it is not."""
    global _delay, _ok_streak
    url = API + "?" + urllib.parse.urlencode(dict(params, format="json"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
        except urllib.error.HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES - 1:
                raise
            _ok_streak = 0
            _delay = min(MAX_DELAY, max(_delay * 1.8, 2.0))
            print("    (%s from Wikidata -- pace now %.1fs/request)" % (err.code, _delay))
    raise RuntimeError("unreachable")


def _labels_of(qids, labels_cache):
    """English labels for QIDs, fetched in one call for everything not already cached."""
    missing = [q for q in dict.fromkeys(qids) if q not in labels_cache]
    for i in range(0, len(missing), 50):               # the API caps ids at 50 per call
        batch = missing[i:i + 50]
        data = _get({"action": "wbgetentities", "ids": "|".join(batch), "props": "labels",
                     "languages": "en"})
        for qid in batch:
            ent = (data.get("entities") or {}).get(qid) or {}
            labels_cache[qid] = ((ent.get("labels") or {}).get("en") or {}).get("value") or ""
    return {q: labels_cache.get(q, "") for q in qids}


#: A document writes "USA"; Wikidata's P17 label is "United States of America". Comparing those
#: as strings rejected perfectly good matches (a live run turned down Boulder for being "not in
#: USA"), so the short forms a biography actually uses are mapped onto the item labels.
#: Because the stated country is a filter, an unlisted form here costs the place its pin -- so
#: this list is worth extending when a run reports "no <place> in <country>" for a country
#: whose name simply reads differently on Wikidata.
COUNTRY_ALIASES = {
    "usa": "united states of america", "us": "united states of america",
    "u.s.": "united states of america", "u.s.a.": "united states of america",
    "united states": "united states of america", "america": "united states of america",
    "uk": "united kingdom", "u.k.": "united kingdom",
    "great britain": "united kingdom", "britain": "united kingdom",
    "england": "united kingdom", "scotland": "united kingdom", "wales": "united kingdom",
    "holland": "kingdom of the netherlands", "the netherlands": "kingdom of the netherlands",
    "netherlands": "kingdom of the netherlands",
    "west germany": "germany", "east germany": "germany", "prussia": "germany",
    "ussr": "soviet union", "u.s.s.r.": "soviet union",
    "russia": "russian federation",
    "czechoslovakia": "czech republic", "czechia": "czech republic",
}


def _country_forms(name):
    """Every folded spelling of a country name worth comparing against a P17 label."""
    folded = _fold(name)
    return {folded, COUNTRY_ALIASES.get(folded, folded)}


def split_qualified(name):
    """('Espoo, Finland') -> ('Espoo', {'finland'}).

    Extractions often name a place the way the document does, with the containing region
    attached: "Kobe, Japan", "Hoyerswerda, Silesia", "Berlin (Wilmersdorf)",
    "Leningrad (present-day St. Petersburg)". Wikidata's item is under the bare name, so an
    exact match on the whole string finds nothing -- 17 of the 46 places this pass could not
    pin had exactly this shape. The tail is not noise, though: it is the document telling us
    which Espoo it means, so it comes back as extra context for the ranking rules rather than
    being thrown away."""
    head = re.split(r"\s*[(,]", name, maxsplit=1)[0].strip()
    if not head or _fold(head) == _fold(name):
        return name, set()
    tail = name[len(head):]
    quals = set()
    for part in re.split(r"[(),]", tail):
        part = re.sub(r"\b(present-day|now|modern|today)\b", " ", part, flags=re.I).strip()
        if part:
            quals |= _country_forms(part)
    return head, quals


def _claim_qids(entity, prop):
    out = []
    for c in (entity.get("claims") or {}).get(prop, []):
        val = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        if isinstance(val, dict) and val.get("id"):
            out.append(val["id"])
    return out


def _coordinate(entity):
    for c in (entity.get("claims") or {}).get("P625", []):
        snak = c.get("mainsnak") or {}
        val = (snak.get("datavalue") or {}).get("value") or {}
        # Earth only. Wikidata really does carry lunar and Martian coordinates, and the
        # projection would happily plot one in the Atlantic.
        if val.get("globe") not in (None, "http://www.wikidata.org/entity/Q2"):
            continue
        lat, lng = val.get("latitude"), val.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return round(float(lat), 5), round(float(lng), 5)
    return None


def lookup_candidates(name, labels_cache):
    """Every Wikidata item plausibly meaning this place name, as plain dicts.

    This is the only part that touches the network, and it is deliberately context-free so one
    lookup serves every document that mentions the name. Choosing between the candidates is
    pick_candidate()'s job, and it depends on the document, so it must not be baked in here."""
    search = _get({"action": "wbsearchentities", "search": name, "language": "en",
                   "uselang": "en", "type": "item", "limit": 15})
    hits = [h["id"] for h in search.get("search") or []]
    if not hits:
        return []

    out = []
    for i in range(0, len(hits), 50):
        batch = hits[i:i + 50]
        data = _get({"action": "wbgetentities", "ids": "|".join(batch),
                     "props": "labels|aliases|claims|sitelinks", "languages": NAME_LANGUAGES})
        for qid in batch:                               # keep the search's own ranking
            ent = (data.get("entities") or {}).get(qid) or {}
            coord = _coordinate(ent)
            if not coord:
                continue                                # not a location at all
            forms = {v.get("value", "") for v in (ent.get("labels") or {}).values()}
            for alias_list in (ent.get("aliases") or {}).values():
                forms |= {a.get("value", "") for a in alias_list}
            out.append({
                "qid": qid,
                "lat": coord[0],
                "lng": coord[1],
                "forms": sorted(f for f in forms if f),
                "country_qids": _claim_qids(ent, "P17"),
                # How many Wikipedia editions have an article: the only prominence signal
                # Wikidata offers, and the last-resort tiebreak.
                "sitelinks": len(ent.get("sitelinks") or {}),
            })
    country_qids = [q for c in out for q in c["country_qids"]]
    labels = _labels_of(country_qids, labels_cache)
    for c in out:
        c["countries"] = sorted({labels.get(q, "") for q in c["country_qids"]} - {""})
        c.pop("country_qids")
    return out


def pick_candidate(name, candidates, country, context_countries):
    """(candidate, basis) for this place in this document, or (None, reason).

    See the module docstring for what each basis means and why the weakest one is still
    recorded rather than discarded."""
    wanted = _fold(name)
    exact = [c for c in candidates if wanted in {_fold(f) for f in c["forms"]}]
    if not exact:
        return None, "no item with a coordinate whose name is exactly %r" % name

    # A country the entity actually recorded is a filter, not a preference: the extraction
    # asserted it from the document, so a candidate somewhere else is contradicted by the data
    # and must not be silently used. Relaxing this to a preference was tried and put Arrhenius's
    # birthplace -- "Vik", recorded as Sweden -- on a Norwegian village of the same name, which
    # is exactly the plausible-looking wrong pin this whole module exists to avoid. The failure
    # that was blamed on the filter ("no Boulder in USA") was really a naming mismatch against
    # Wikidata's "United States of America", and belongs to COUNTRY_ALIASES.
    # A candidate with no P17 at all is compatible with anything -- that is how countries
    # themselves ("Egypt", "Italy") pass.
    if country:
        wanted_countries = _country_forms(country)
        matched = [c for c in exact
                   if not c["countries"]
                   or wanted_countries & {f for x in c["countries"] for f in _country_forms(x)}]
        if not matched:
            return None, "no %r in %s" % (name, country)
        return matched[0], "country"

    if context_countries:
        matched = [c for c in exact
                   if {f for x in c["countries"] for f in _country_forms(x)} & context_countries]
        if matched:
            return matched[0], "document"

    return max(exact, key=lambda c: c["sitelinks"]), "most_linked"


def document_countries(entities, labels_cache_unused=None):
    """The countries this document already places its subject in.

    Two sources, both already in the extraction: every `attributes.country` the model recorded,
    and the names of the place entities themselves -- a paper that has a "France" place entity
    is a paper whose "Paris" is French. Nothing here costs a request."""
    out = set()
    for e in entities:
        if e.get("entity_type") != "place":
            continue
        attrs = e.get("attributes") or {}
        for key in ("country", "state", "region", "province"):
            if attrs.get(key):
                out |= _country_forms(attrs[key])
        if e.get("name"):
            out |= _country_forms(e["name"])
    return out


def load_cache():
    if os.path.isfile(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("version") == CACHE_VERSION:
                return cache
            print("cache was written by an older version of the matching rules -- refetching")
        except (OSError, ValueError):
            pass
    return {"version": CACHE_VERSION}


def save_cache(cache):
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, CACHE_PATH)


def write_json(path, data):
    """Atomic, so a rebuild running in another process never reads a half-written file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def review(args):
    """List every place resolved by the weakest rule, so the guesses can be checked.

    `most_linked` means nothing in the document distinguished several same-named places and the
    most-written-about one won. That is usually right and occasionally wrong in a way only a
    reader can catch: Wedgwood's "Etruria" is his works in Staffordshire, but with no other
    geography in that document to go on it resolved to the ancient region in Italy. Making the
    weak calls listable is the point of recording geocode_basis at all -- a wrong pin you can
    find is a different thing from a wrong pin you cannot."""
    rows = []
    for slug, _path in _targets(args):
        for _, docdir in bs.subject_documents(slug):
            epath = os.path.join(docdir, "entities.json")
            if not os.path.isfile(epath):
                continue
            with open(epath, encoding="utf-8") as f:
                for e in json.load(f):
                    attrs = e.get("attributes") or {}
                    if e.get("entity_type") == "place" and \
                            attrs.get("geocode_basis") == "most_linked":
                        rows.append((slug, e.get("name", ""), attrs.get("wikidata_qid", ""),
                                     attrs.get("lat"), attrs.get("lng")))
    if not rows:
        print("nothing resolved by most_linked -- every place had a country or document match")
        return 0
    print("%d place(s) resolved only by 'most written-about', worth a check:\n" % len(rows))
    for slug, name, qid, lat, lng in sorted(rows):
        print("  %-22s %-28s %-11s %s  https://www.wikidata.org/wiki/%s"
              % (slug, name[:28], qid, "%9.4f,%9.4f" % (lat, lng), qid))
    print("\nTo correct one: set attributes.lat/lng/wikidata_qid on that entity by hand and "
          "change geocode_basis to \"manual\" -- re-runs leave existing coordinates alone.")
    return 0


def _targets(args):
    out = []
    for slug, path in bs.iter_subject_dirs():
        if args.subject and slug != args.subject:
            continue
        if args.domain and os.path.basename(os.path.dirname(path)) != \
                bs.domain_dir_name(args.domain):
            continue
        out.append((slug, path))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", help="only this slug")
    ap.add_argument("--domain", help="only subjects under this domain folder")
    ap.add_argument("--dry-run", action="store_true", help="look up but write nothing")
    ap.add_argument("--refresh", action="store_true",
                    help="re-resolve places that already have coordinates")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many distinct place names (0 = no limit)")
    ap.add_argument("--review", action="store_true",
                    help="don't look anything up: list the places already resolved by the "
                         "weakest rule (most_linked), for checking by hand")
    args = ap.parse_args()

    if args.review:
        return review(args)

    cache = load_cache()
    labels_cache = cache.setdefault("_labels", {})
    places = cache.setdefault("places", {})

    targets = _targets(args)
    if not targets:
        print("no matching subjects")
        return 1

    looked_up = filled = already = skipped = cleared = 0
    for slug, _path in targets:
        for _, docdir in bs.subject_documents(slug):
            epath = os.path.join(docdir, "entities.json")
            if not os.path.isfile(epath):
                continue
            with open(epath, encoding="utf-8") as f:
                entities = json.load(f)
            context = document_countries(entities)
            changed = False
            for e in entities:
                if e.get("entity_type") != "place":
                    continue
                attrs = e.setdefault("attributes", {})
                has = (isinstance(attrs.get("lat"), (int, float)) and
                       isinstance(attrs.get("lng"), (int, float)))
                if has and not args.refresh:
                    already += 1
                    continue
                name = e.get("name") or ""
                country = attrs.get("country")

                # Two bites: the name as written, then -- if that finds nothing -- the same name
                # with its qualifier stripped ("Espoo, Finland" -> "Espoo"), the qualifier
                # folded into the context so it still decides which Espoo.
                head, quals = split_qualified(name)
                pick, basis = None, ""
                for attempt, (lookup_name, extra) in enumerate(
                        [(name, set())] + ([(head, quals)] if head != name else [])):
                    key = _fold(lookup_name)
                    if key not in places:
                        if args.limit and looked_up >= args.limit:
                            break
                        try:
                            places[key] = lookup_candidates(lookup_name, labels_cache)
                        except Exception as err:    # network trouble: leave it for next time
                            print("  %s: %s -- lookup failed: %s" % (slug, name, err))
                            break
                        looked_up += 1
                        save_cache(cache)
                    pick, basis = pick_candidate(lookup_name, places.get(key) or [], country,
                                                 (context | extra) - {_fold(lookup_name)})
                    if pick:
                        if attempt:
                            print("  %s: %s -- matched as %r" % (slug, name, head))
                        break
                if not pick:
                    print("  %s: %s -- %s" % (slug, name, basis))
                    skipped += 1
                    # Under --refresh a place that no longer resolves must lose the coordinates
                    # it has, not keep them: the rules changed for a reason, and leaving the
                    # old pin behind would make the map show precisely the answer we just
                    # decided was not good enough.
                    # Every key, not any() -- which short-circuits after the first pop and
                    # leaves an entity carrying a geocode_basis for coordinates it no longer has.
                    dropped = [attrs.pop(k, None) for k in
                               ("lat", "lng", "wikidata_qid", "geocode_basis")]
                    if has and any(v is not None for v in dropped):
                        print("    (removed the coordinates it had)")
                        cleared += 1
                        changed = True
                    continue
                attrs["lat"], attrs["lng"] = pick["lat"], pick["lng"]
                attrs["wikidata_qid"] = pick["qid"]
                attrs["geocode_basis"] = basis
                filled += 1
                changed = True
                print("  %s: %s -> %s, %s  (%s, %s)"
                      % (slug, name, pick["lat"], pick["lng"], pick["qid"], basis))
            if changed and not args.dry_run:
                write_json(epath, entities)

    save_cache(cache)
    verb = "would fill" if args.dry_run else "filled"
    print("\n%s %d place entit%s; %d already had coordinates; %d left off the map; "
          "%d Wikidata lookup(s) this run"
          % (verb, filled, "y" if filled == 1 else "ies", already, skipped, looked_up))
    if not args.dry_run and filled:
        print("Rebuild the pages to see them: python scripts/build_site.py --all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
