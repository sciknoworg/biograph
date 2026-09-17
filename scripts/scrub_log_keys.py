#!/usr/bin/env python3
"""Redact API keys that early runs wrote into pipeline_log.txt.

run_subprocess() logs every command line it runs, and for the first two days of this project
the CORE and model API keys were passed as command-line arguments. They therefore sit in the
log in the clear. The code was changed on 2026-09-05 to pass credentials through the
environment instead -- see child_env() -- so nothing since then leaks, but the historical
lines remain.

Rotating a key is normally the right fix, because it makes every logged copy worthless and no
scrubbing is needed. That is not available for the CORE key: it is issued against an
institutional subscription with no self-service dashboard, so the value in this file stays
valid until the institution reissues it. Redaction is then the actual mitigation rather than a
substitute for one.

What it does: finds every value passed to --api-key or --core-api-key that looks like a
credential (20+ characters), and replaces every occurrence of those values throughout the file
with a marker of the same shape. Nothing else changes -- the log stays readable and every line
count, timestamp and message survives, so it remains usable as the run record the access report
is derived from.

Deliberately no backup. A backup would be a second copy of exactly what this removes.

    python scripts/scrub_log_keys.py            # report what it would redact
    python scripts/scrub_log_keys.py --apply
"""
import io
import os
import re
import sys

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "pipeline_log.txt")

#: A credential is only recognised where a flag says it is one. Scanning for "long random-looking
#: string" instead would also hit DOIs, hashes and CORE document ids, and mangling those would
#: quietly corrupt the run record this file exists to preserve.
FLAG = re.compile(r"--(?:core-|openalex-)?api-key[= ]+(\S{20,})")


def find_keys(text):
    return {m.group(1) for m in FLAG.finditer(text)}


def main():
    apply = "--apply" in sys.argv
    if not os.path.isfile(LOG):
        sys.exit("no log at %s" % LOG)

    with io.open(LOG, encoding="utf-8", errors="replace") as f:
        text = f.read()

    keys = find_keys(text)
    if not keys:
        print("no credentials found on any command line -- nothing to redact")
        return 0

    print("found %d distinct key value(s):" % len(keys))
    total = 0
    for k in sorted(keys):
        n = text.count(k)
        total += n
        print("   %s... (%d chars)  %d occurrence(s)" % (k[:3], len(k), n))

    before_lines = text.count("\n")
    scrubbed = text
    for k in sorted(keys, key=len, reverse=True):
        scrubbed = scrubbed.replace(k, "[REDACTED-%dCHARS]" % len(k))

    # Refuse to write anything that lost a line. The log is the record every access figure in
    # docs/access.md is derived from; redaction must cost the credentials and nothing else.
    after_lines = scrubbed.count("\n")
    if before_lines != after_lines:
        sys.exit("refusing to write: line count changed %d -> %d" % (before_lines, after_lines))
    if find_keys(scrubbed):
        sys.exit("refusing to write: a credential still matches after redaction")

    print("\n%d occurrence(s) across %d line(s); %d lines preserved"
          % (total, len({i for i, l in enumerate(text.split("\n"))
                         for k in keys if k in l}), after_lines))

    if not apply:
        print("dry run -- re-run with --apply")
        return 0

    tmp = LOG + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(scrubbed)
    os.replace(tmp, LOG)
    print("redacted in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
