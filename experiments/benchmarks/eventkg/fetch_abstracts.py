"""Fetch the Wikipedia abstracts the EventKG benchmark's gold was derived from.

    python -m experiments.benchmarks.eventkg.fetch_abstracts \
        --data-root experiments/corpora/eventkg --limit 50

The benchmark ships relevance judgements over knowledge-graph relations and no text at
all, so the documents have to be assembled before anything can be run. They come from the
English Wikipedia API, one lead section per person, and are written to
<data-root>/abstracts/<entity_label>.txt.

WHY A REVISION CUTOFF. The judgements were produced by aligning EventKG relations against
Wikipedia abstracts as they stood when the paper was written in 2019. An abstract rewritten
since may no longer contain a fact the gold says is in it. Scoring today's text against
2019's judgements would charge seven years of editing to the extractor, so each title is
resolved to its last revision at or before --cutoff and that revision's lead section is
what gets stored. The revision id is recorded in the file's first line as a comment the
adapter strips, so a run is reproducible against an exact text.

WHY THE LEAD SECTION ONLY. BS-ENC is built from abstracts -- `section=0` is Wikipedia's own
definition of one. Fetching the whole article would hand the extractor a document the gold
was never aligned against, which would show up as extra recall from text the judgements
never saw.

This script is the only place in the harness that reaches the network, it is run by hand,
and it writes only under --data-root, which is gitignored. Nothing it fetches is
redistributed; see experiments/corpora/eventkg/README.md for the licence position.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://en.wikipedia.org/w/api.php"
UA = "biograph-benchmark-harness/1.0 (research; contact via repository)"

#: Stripped from the parsed HTML before the text is written.
_DROP = re.compile(
    r"<(script|style|sup|table)\b.*?</\1>|<!--.*?-->", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"\n{3,}")


def _get(params: dict[str, str], retries: int = 3) -> dict:
    """One API call, with a courteous retry. Returns parsed JSON."""
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as fh:
                return json.loads(fh.read().decode("utf-8"))
        except Exception as exc:                       # noqa: BLE001 - reported, not raised
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("giving up on %s: %s" % (params.get("titles") or
                                                params.get("oldid"), last))


def revision_at(title: str, cutoff: str) -> tuple[str, str] | None:
    """The id and timestamp of `title`'s last revision at or before `cutoff`."""
    data = _get({"action": "query", "prop": "revisions", "titles": title,
                 "rvlimit": "1", "rvdir": "older", "rvstart": cutoff + "T23:59:59Z",
                 "rvprop": "ids|timestamp"})
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        if "missing" in page:
            return None
        revs = page.get("revisions") or []
        if revs:
            return str(revs[0]["revid"]), str(revs[0]["timestamp"])
    return None


def lead_text(oldid: str) -> str:
    """The lead section of one revision, as plain text."""
    data = _get({"action": "parse", "oldid": oldid, "prop": "text",
                 "section": "0", "disablelimitreport": "1",
                 "disableeditsection": "1", "redirects": "1"})
    raw = ((data.get("parse") or {}).get("text") or {}).get("*") or ""
    text = _TAG.sub("", _DROP.sub(" ", raw))
    text = html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK.sub("\n\n", text).strip()


def titles_from_benchmark(tsv: str) -> list[str]:
    """Every distinct entity_label that has at least one wikipedia_score of 1.0.

    A person with no positive judgement has nothing for this benchmark to score, so
    fetching their abstract would spend a request and a model call for no measurement.
    """
    wanted: dict[str, None] = {}
    with open(tsv, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader, None)
        if not header:
            raise SystemExit("benchmark.tsv is empty")
        try:
            i_label = header.index("entity_label")
            i_score = header.index("wikipedia_score")
        except ValueError:
            raise SystemExit("benchmark.tsv header lacks entity_label/wikipedia_score: "
                             + ", ".join(header))
        for parts in reader:
            if len(parts) <= max(i_label, i_score):
                continue
            if parts[i_score].strip() in ("1", "1.0"):
                wanted.setdefault(parts[i_label], None)
    return list(wanted)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--cutoff", default="2019-05-21",
                    help="fetch each title's last revision at or before this date "
                         "(default: the paper's arXiv submission date)")
    ap.add_argument("--limit", type=int,
                    help="fetch only this many people; the benchmark has 2,760 and a "
                         "full run against all of them is not the intended use")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="seconds between requests, to stay polite to the API")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    tsv = os.path.join(args.data_root, "benchmark.tsv")
    if not os.path.isfile(tsv):
        raise SystemExit("benchmark.tsv not found at " + tsv)
    out_dir = os.path.join(args.data_root, "abstracts")
    os.makedirs(out_dir, exist_ok=True)

    titles = titles_from_benchmark(tsv)
    print("%d people carry at least one Wikipedia-attested relation" % len(titles))
    if args.limit:
        titles = titles[:args.limit]
        print("fetching %d" % len(titles))

    written = skipped = missing = failed = 0
    index_path = os.path.join(out_dir, "revisions.tsv")
    index: dict[str, str] = {}
    if os.path.isfile(index_path):
        with open(index_path, encoding="utf-8") as fh:
            for line in fh:
                bits = line.rstrip("\n").split("\t")
                if len(bits) >= 2:
                    index[bits[0]] = bits[1]

    for n, title in enumerate(titles, 1):
        dest = os.path.join(out_dir, title.replace("/", "_") + ".txt")
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        try:
            rev = revision_at(title.replace("_", " "), args.cutoff)
            if rev is None:
                missing += 1
                print("  [%d/%d] MISSING %s" % (n, len(titles), title))
                continue
            oldid, stamp = rev
            text = lead_text(oldid)
            if not text:
                missing += 1
                print("  [%d/%d] EMPTY   %s (rev %s)" % (n, len(titles), title, oldid))
                continue
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            index[title] = "%s\t%s\t%d" % (oldid, stamp, len(text))
            written += 1
            print("  [%d/%d] %-45s rev %s  %6d chars"
                  % (n, len(titles), title[:45], oldid, len(text)))
        except Exception as exc:                        # noqa: BLE001 - counted, not fatal
            failed += 1
            print("  [%d/%d] FAILED  %s: %s" % (n, len(titles), title, exc))
        time.sleep(args.sleep)

    with open(index_path, "w", encoding="utf-8") as fh:
        for title in sorted(index):
            fh.write("%s\t%s\n" % (title, index[title]))

    print("\nwritten %d, already present %d, no revision %d, failed %d"
          % (written, skipped, missing, failed))
    print("revisions recorded in %s" % os.path.relpath(index_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
