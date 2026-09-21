"""Fetch the scope-probe corpus: Wikipedia biographies across professions.

The question this corpus exists to answer is narrow: does SCOPE_DEFINITION admit a
biography of a *named person* who is not a technologist? PMOA-TTS could not answer it,
because clinical case reports fail two independent clauses at once (no named subject AND
wrong genre), so a refusal there says nothing about which clause bites.

Design: source and format are held constant -- every document is the plain-text lead and
body of an English Wikipedia biography, truncated to the same length band -- so the only
variable across documents is the subject's field. Benchmark 1 (Biographical) is itself
Wikipedia-derived, so this is a faithful proxy for its genre without touching a dataset
whose licence is still unresolved.

The list is a gradient, not a sample. It runs from "no technology anywhere near this
life" to "this person is why the technology exists", because the interesting result is
not pass/fail but *where* the boundary sits.

Nothing here is redistributed: corpora/ is gitignored and these are fetched on demand.
Wikipedia text is CC BY-SA 4.0.

    python experiments/corpora/fetch_scope_pilot.py
"""
import io
import json
import os
import time
import urllib.parse
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scope_pilot")

#: Wikimedia asks automated clients to identify themselves and give a contact route.
UA = ("biograph-scope-probe/1.0 "
      "(https://github.com/sciknoworg/biograph; research corpus scope evaluation) "
      "python-urllib")

#: (slug, --name, Wikipedia title, field, expected distance from the scope definition)
SUBJECTS = [
    ("woolf",      "Virginia Woolf",   "Virginia Woolf",   "literature",  "far"),
    ("kahlo",      "Frida Kahlo",      "Frida Kahlo",      "art",         "far"),
    ("owens",      "Jesse Owens",      "Jesse Owens",      "sport",       "far"),
    ("ellington",  "Duke Ellington",   "Duke Ellington",   "music",       "far"),
    ("churchill",  "Winston Churchill", "Winston Churchill", "politics",  "far"),
    ("earhart",    "Amelia Earhart",   "Amelia Earhart",   "aviation",    "adjacent"),
    ("nightingale", "Florence Nightingale", "Florence Nightingale", "nursing/statistics", "adjacent"),
    ("turing",     "Alan Turing",      "Alan Turing",      "computing",   "control (should pass)"),
]

#: Long enough to read as a document rather than a stub, short enough to keep the
#: extraction call cheap and comparable across subjects.
MAX_CHARS = 12000


def fetch(title):
    params = {"action": "query", "prop": "extracts", "explaintext": "1",
              "redirects": "1", "format": "json", "titles": title}
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    return page.get("extract") or ""


def main():
    os.makedirs(OUT, exist_ok=True)
    index = []
    for slug, name, title, field, expectation in SUBJECTS:
        text = fetch(title)
        if not text:
            print("  !! no extract for %s" % title)
            continue
        text = text[:MAX_CHARS]
        path = os.path.join(OUT, slug + ".txt")
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        index.append({"slug": slug, "name": name, "title": title, "field": field,
                      "expectation": expectation, "chars": len(text),
                      "source_url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                      "licence": "CC BY-SA 4.0"})
        print("  %-12s %-22s %6d chars  (%s)" % (slug, field, len(text), expectation))
        time.sleep(1.0)

    with io.open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("\n%d documents -> %s" % (len(index), OUT))


if __name__ == "__main__":
    main()
