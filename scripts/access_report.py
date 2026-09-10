#!/usr/bin/env python3
"""What happened when this project tried to read the biographical record.

Every document the pipeline has ever tried to fetch is recorded in
`.pipeline_manifest.json`, together with what came back. This script turns that
into a report: how many documents were obtained, how many were refused, by which
providers, and by what mechanism.

Why it exists as a committed script rather than a table in a paper: the claim
"publishers refuse automated access to biographical literature" is only worth
making if it can be re-derived. Run this against your own manifest and you get
your own numbers. The manifest itself is local and gitignored (it records
file paths and search history), so the script travels and the data does not.

    python scripts/access_report.py                 # the report
    python scripts/access_report.py --markdown      # same, as a Markdown table
    python scripts/access_report.py --min-attempts 10

## Reading the result honestly

The distinction between the failure kinds matters, and collapsing them into
"paywalled" would overstate a case that does not need it:

- **403 refused** -- the server actively refused an identified automated client.
  This is a policy decision about robots. It is *not* proof of a paywall: MDPI is
  fully open access and still refuses, which can only be bot-blocking.
- **HTML, not PDF** -- the server returned a web page where a PDF was
  advertised: a landing page, a paywall interstitial, or a consent wall. The
  document may well be readable by a human at that address.
- **404 missing** -- the document is not at the address the index recorded. That
  is a broken link, not a policy, and belongs in neither column.

The defensible claim is narrower than "paywalled" and still substantial: *these
documents are open to a human and closed to a machine.* A corpus cannot be built
from literature that only renders in a browser.
"""
import argparse
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, ".pipeline_manifest.json")

#: Ordered worst-to-least-interesting, which is also the order they are reported in.
KINDS = ["403 refused", "HTML, not PDF", "404 missing", "timeout", "conn reset", "other"]


def host_of(url):
    m = re.match(r"https?://([^/]+)", str(url or ""))
    return m.group(1).lower().replace("www.", "") if m else ""


def kind_of(reason):
    r = str(reason or "")
    if "403" in r:
        return "403 refused"
    if "not a PDF" in r:
        return "HTML, not PDF"
    if "404" in r:
        return "404 missing"
    if "Timeout" in r or "timed out" in r:
        return "timeout"
    if "ConnectionReset" in r or "Connection reset" in r:
        return "conn reset"
    return "other"


def load_manifest(path):
    if not os.path.isfile(path):
        sys.exit("No manifest at %s -- nothing to report on. This script reads the record left "
                 "by scripts/run_pipeline.py." % path)
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def collect(manifest):
    """(overall status counts, per-provider {kind: n} + obtained, per-domain outcomes)."""
    status = collections.Counter()
    obtained = collections.Counter()
    refused = collections.defaultdict(collections.Counter)
    domains = collections.defaultdict(collections.Counter)

    for entry in manifest.values():
        ds = entry.get("download_status") or "(never attempted)"
        status[ds] += 1
        if ds == "downloaded":
            obtained[host_of(entry.get("download_url"))] += 1
        elif str(ds).startswith("failed"):
            # A failure records the URL it failed on inside "reason"; download_url is only
            # written on success. Reading download_url alone makes every provider look perfect.
            refused[host_of(entry.get("reason"))][kind_of(entry.get("reason"))] += 1

        path = str(entry.get("download_path") or "").replace(os.sep, "/")
        m = re.search(r"_pending/([^/]+)/", path)
        if m:
            domains[m.group(1)][entry.get("extract_status") or "(unextracted)"] += 1

    return status, obtained, refused, domains


def provider_rows(obtained, refused, min_attempts):
    rows = []
    for host in set(obtained) | set(refused):
        if not host:
            continue
        got = obtained.get(host, 0)
        counts = refused.get(host, collections.Counter())
        lost = sum(counts.values())
        if got + lost < min_attempts:
            continue
        rows.append((lost, got, host, counts))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    return rows


def report(status, obtained, refused, domains, min_attempts, markdown):
    total = sum(status.values())
    attempted = total - status.get("(never attempted)", 0)
    got = status.get("downloaded", 0)

    def rule(title):
        if markdown:
            print("\n## %s\n" % title)
        else:
            print("\n" + "=" * 78 + "\n%s\n" % title + "=" * 78)

    rule("Every document the pipeline tried to fetch")
    if markdown:
        print("| outcome | documents | share |\n|---|---:|---:|")
        for k, v in status.most_common():
            print("| %s | %d | %.1f%% |" % (k, v, 100.0 * v / total))
        print("| **total** | **%d** | |" % total)
    else:
        for k, v in status.most_common():
            print("  %-26s %6d  %5.1f%%" % (k, v, 100.0 * v / total))
        print("  %-26s %6d" % ("TOTAL", total))
    if attempted:
        print("\n  Obtained %d of %d attempted (%.0f%%)." % (got, attempted, 100.0 * got / attempted))

    rule("By provider, ranked by documents refused (>= %d attempts)" % min_attempts)
    rows = provider_rows(obtained, refused, min_attempts)
    if markdown:
        print("| provider | obtained | refused | " + " | ".join(KINDS[:3]) + " |")
        print("|---|---:|---:|---:|---:|---:|")
        for lost, g, host, c in rows:
            print("| %s | %d | %d | %d | %d | %d |"
                  % (host, g, lost, c["403 refused"], c["HTML, not PDF"], c["404 missing"]))
    else:
        print("  %-30s %8s %8s %7s %7s %7s"
              % ("provider", "obtained", "refused", "403", "HTML", "404"))
        print("  " + "-" * 74)
        for lost, g, host, c in rows:
            print("  %-30s %8d %8d %7d %7d %7d"
                  % (host[:30], g, lost, c["403 refused"], c["HTML, not PDF"],
                     c["404 missing"]))

    rule("How refusals were expressed")
    tot = collections.Counter()
    for c in refused.values():
        tot.update(c)
    n = sum(tot.values()) or 1
    if markdown:
        print("| mechanism | count | share |\n|---|---:|---:|")
        for k in KINDS:
            if tot[k]:
                print("| %s | %d | %.1f%% |" % (k, tot[k], 100.0 * tot[k] / n))
    else:
        for k in KINDS:
            if tot[k]:
                print("  %-16s %6d  %5.1f%%" % (k, tot[k], 100.0 * tot[k] / n))
    print("\n  403 is a refusal of an identified robot, not proof of a paywall -- a fully "
          "open-access\n  publisher can and does return it. See this module's docstring before "
          "quoting these numbers.")

    rule("What became of documents that were obtained")
    if markdown:
        print("| domain | staged | subjects | rate |\n|---|---:|---:|---:|")
    for dom in sorted(domains):
        counts = domains[dom]
        made = counts.get("subject_created", 0)
        staged = sum(counts.values())
        pct = 100.0 * made / staged if staged else 0
        if markdown:
            print("| %s | %d | %d | %.0f%% |" % (dom, staged, made, pct))
        else:
            print("  %-28s %4d staged -> %3d subject(s)  (%.0f%%)" % (dom, staged, made, pct))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--min-attempts", type=int, default=10,
                    help="only list providers with at least this many fetch attempts")
    ap.add_argument("--markdown", action="store_true", help="emit Markdown tables")
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    status, obtained, refused, domains = collect(manifest)
    report(status, obtained, refused, domains, args.min_attempts, args.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
