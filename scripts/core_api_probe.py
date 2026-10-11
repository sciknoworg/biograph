#!/usr/bin/env python3
"""Check whether this machine can use the CORE API (api.core.ac.uk) with the key it holds.

Run it on each machine that should work and compare the reports. Standard library only, so it
runs anywhere Python 3.8+ does, with nothing to install.

WHY. "The key doesn't work" has at least five causes, and from inside a failing tool they look
the same:

  - the machine cannot reach api.core.ac.uk at all (firewall, no outbound internet on compute
    nodes, a proxy that is required but not configured)
  - CORE's Cloudflare front blocks this machine's IP address
  - the variable is not set in the process that makes the call (not exported, a non-interactive
    shell that skips .bashrc, sudo or cron stripping the environment)
  - the variable is set but holds something else: an old key, or the right key with a trailing
    newline, carriage return or quotes copied in with it
  - the call itself is wrong: $VAR written in cmd.exe, which sends the literal text "$VAR" as
    the key, or the URL missing its trailing slash, which returns a 301 HTML page, not JSON

So the probe sends the same search four ways and compares them:

  NO KEY     should return 200 with a rate limit of 10. Proves the network path and CORE work,
             independent of any key.
  FAKE KEY   should return 401. Proves CORE checks keys for requests from this machine.
  YOUR KEY   should return 200 with a rate limit of 500. The actual question.
  NO SLASH   your key, URL without the trailing slash. Should return 301; shows the pitfall.

CREDENTIALS come from the environment, never a command line. The report shows the key's length
and a sha256 prefix, never the key: compare the prefix with a machine where it works.

    export BIOGRAPH_CORE_API_KEY=...         # or pass --key-env SOME_OTHER_VAR
    python3 scripts/core_api_probe.py
    python3 scripts/core_api_probe.py --out core_probe_server.md
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.core.ac.uk/v3/search/works"
QUERY = "?q=transistor&limit=1"
#: Same length as a real key, so a 401 for it is a statement about keys, not about format.
FAKE_KEY = "0" * 32
PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface a 301 as a 301. Following it would hide the missing-slash pitfall."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12] if key else "-"


def key_problems(key: str) -> list[str]:
    """Things that make a correct key fail. Each was a real way a key arrived broken."""
    problems = []
    if key != key.strip():
        problems.append("leading or trailing whitespace (often a newline from `echo` or a file)")
    if "\r" in key:
        problems.append("contains a carriage return (copied from a Windows file?)")
    if key[:1] in "\"'" or key[-1:] in "\"'":
        problems.append("wrapped in quotes, which are being sent as part of the key")
    if key.lower().startswith("bearer"):
        problems.append("starts with 'Bearer'; the variable should hold the key alone")
    if key.startswith("$") or key.startswith("%"):
        problems.append("looks like an unexpanded variable name, not a key")
    return problems


def call(url: str, key: str | None, timeout: float) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "biograph-core-probe/1"}
    if key is not None:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, headers=headers)
    t0 = time.monotonic()
    try:
        resp = _OPENER.open(req, timeout=timeout)
        status, hdrs, body = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        status, hdrs, body = e.code, e.headers, e.read()
    except urllib.error.URLError as e:
        return {"status": None, "error": "network: %s" % (e.reason,),
                "secs": time.monotonic() - t0}
    except (socket.timeout, TimeoutError):
        return {"status": None, "error": "network: timed out after %ss" % timeout,
                "secs": time.monotonic() - t0}
    except ValueError:
        # http.client refuses a header holding CR or LF, and its message quotes the header,
        # which here is the key. Report the cause, never the exception text.
        return {"status": None, "secs": time.monotonic() - t0,
                "error": "not sent: the key contains a newline or carriage return"}
    except Exception as e:
        text = str(e).replace(key, "<key>") if key else str(e)
        return {"status": None, "error": "%s: %s" % (type(e).__name__, text),
                "secs": time.monotonic() - t0}
    row = {"status": status, "secs": time.monotonic() - t0,
           "limit": hdrs.get("x-ratelimit-limit"),
           "remaining": hdrs.get("x-ratelimit-remaining"),
           "type": (hdrs.get("content-type") or "").split(";")[0],
           "server": hdrs.get("server"),
           "location": hdrs.get("location")}
    text = body.decode("utf-8", "replace")
    try:
        data = json.loads(text)
        row["hits"] = data.get("totalHits")
        row["message"] = data.get("message")
    except ValueError:
        row["message"] = " ".join(text.split())[:120] or None
    return row


def diagnose(key: str | None, rows: dict, problems: list[str]) -> list[str]:
    nokey, fake, mine = rows["no key"], rows["fake key"], rows.get("your key")
    if nokey["status"] is None:
        return ["This machine cannot reach api.core.ac.uk (%s). Nothing about the key has been "
                "tested. Check outbound HTTPS from this host: compute nodes on clusters often have "
                "none, and some networks need HTTPS_PROXY set." % nokey["error"]]
    if nokey["status"] in (403, 503) or "cloudflare" in (nokey.get("message") or "").lower():
        return ["CORE's front end refused this machine before any key was checked (HTTP %s). "
                "Its IP address is probably blocked; a key will not fix that. Ask CORE "
                "(theteam@core.ac.uk) or run from another network." % nokey["status"]]
    if nokey["status"] == 429:
        return ["This machine's IP address is rate-limited right now (429). Wait and re-run."]
    out = []
    if key is None:
        out.append("The key variable is not set in this process. Set and export it in the shell "
                   "that runs the job; sudo, cron and non-interactive ssh sessions often start "
                   "without your shell's variables.")
        return out
    if problems:
        out.append("The key has a formatting problem: " + "; ".join(problems) + ".")
    if mine and mine["status"] == 200 and mine.get("limit") == "500":
        out.append("The key works from this machine. If a tool still fails here, the tool is "
                   "sending the request differently: check its shell syntax for the variable, "
                   "the URL's trailing slash, and that the variable reaches its process.")
    elif mine and mine["status"] == 401:
        if fake["status"] == 401:
            out.append("CORE rejects this key. Compare its sha256 prefix with one from a machine "
                       "where the key works: if they differ, this machine holds a different or "
                       "corrupted key; if they match, the key itself was revoked.")
        else:
            out.append("Unexpected: your key got 401 but the fake key got %s." % fake["status"])
    elif mine and mine["status"] is None:
        out.append("The request with your key failed: %s." % mine["error"])
    elif mine:
        out.append("Unexpected response to your key: HTTP %s, limit %s, %s."
                   % (mine["status"], mine.get("limit"), mine.get("message")))
    return out


def write_report(path: str, meta: dict, rows: dict, findings: list[str]) -> str:
    lines = ["# CORE API probe report", "",
             "Host: `%s` (%s)  " % (meta["host"], meta["platform"]),
             "Python: %s  " % meta["python"],
             "Generated: %s UTC  " % meta["when"],
             "Endpoint: `%s/%s`" % (BASE, QUERY), "",
             "## Key", "",
             "- variable: `%s`" % meta["key_env"],
             "- set in this process: **%s**" % ("yes" if meta["key_set"] else "NO"),
             "- length: %s" % meta["key_len"],
             "- sha256 prefix: `%s` (compare with a machine where it works)" % meta["key_fp"],
             "- format problems: %s" % ("; ".join(meta["problems"]) or "none"),
             "- proxy variables set: %s" % (", ".join(meta["proxies"]) or "none"),
             "", "## Requests", "",
             "| request | expected | HTTP | rate limit | remaining | hits | content type | time | message |",
             "|---|---|---|---|---|---|---|---|---|"]
    expected = {"no key": "200, limit 10", "fake key": "401",
                "your key": "200, limit 500", "no slash": "301"}
    for name, r in rows.items():
        msg = r.get("error") or r.get("message") or ""
        if r.get("location"):
            msg = "redirect to " + r["location"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %.2fs | %s |" % (
            name, expected[name], r.get("status") or "-", r.get("limit") or "-",
            r.get("remaining") or "-", r.get("hits") if r.get("hits") is not None else "-",
            r.get("type") or "-", r["secs"], msg.replace("|", "/")[:120]))
    lines += ["", "## Diagnosis", ""] + ["- " + f for f in findings] + [""]
    text = "\n".join(lines)
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key-env", default="BIOGRAPH_CORE_API_KEY",
                    help="environment variable holding the key (default: %(default)s)")
    ap.add_argument("--timeout", type=float, default=30, help="seconds per request")
    ap.add_argument("--out", default="core_api_probe_report.md")
    args = ap.parse_args(argv)

    key = os.environ.get(args.key_env)
    problems = key_problems(key) if key else []
    meta = {"host": socket.gethostname(), "platform": platform.platform(),
            "python": platform.python_version(),
            "when": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "key_env": args.key_env, "key_set": key is not None,
            "key_len": len(key) if key else 0, "key_fp": fingerprint(key or ""),
            "problems": problems, "proxies": [v for v in PROXY_VARS if os.environ.get(v)]}

    rows = {"no key": call(BASE + "/" + QUERY, None, args.timeout),
            "fake key": call(BASE + "/" + QUERY, FAKE_KEY, args.timeout)}
    if key is not None:
        rows["your key"] = call(BASE + "/" + QUERY, key, args.timeout)
        rows["no slash"] = call(BASE + QUERY, key, args.timeout)

    findings = diagnose(key, rows, problems)
    print(write_report(args.out, meta, rows, findings))
    print("written to %s" % args.out, file=sys.stderr)
    mine = rows.get("your key") or {}
    return 0 if mine.get("status") == 200 and mine.get("limit") == "500" else 1


if __name__ == "__main__":
    sys.exit(main())
