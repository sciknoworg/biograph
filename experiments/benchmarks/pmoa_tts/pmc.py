"""Fetch case report text from PubMed Central, because PMOA-TTS does not ship any.

The released corpus is timelines only -- `pmc_id`, `case_report_id`, `textual_timeseries`,
demographics, diagnoses, death_info. There is no document text in any split, so the input
side of this benchmark has to be reconstructed from PMC Open Access by `case_report_id`.

Matching their preprocessing matters. `make_tts/get_pmoa_body.sh` takes the PMC OA text
package and keeps only what lies between the `==== Body` and `==== Ref` markers:

    awk '/==== Body/{a=1;next}/==== Ref/{a=0}a'

So their annotations describe the BODY of the article -- no title, no abstract, no
references. This module reproduces that boundary against the BioC full-text service,
which exposes the same structure as typed passages: everything whose section_type is not
TITLE/ABSTRACT/REF/ACK_FUND/COMP_INT/SUPPL is body. Feeding biograph the abstract as well
would hand it a summary of the whole case and inflate recall against timelines that were
never extracted from one.

Fetching is deliberately conservative. NCBI allows 3 requests/second without an API key,
and answers 429 with an HTML page rather than JSON when you exceed it -- which is how
this module learned to check the content type before parsing. Requests are throttled to
`min_interval`, retried with backoff on 429/5xx, and cached on disk so a re-run costs
nothing. Set BIOGRAPH_CONTACT_EMAIL (the project already uses it) so NCBI can identify
the caller, as their usage policy asks.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BIOC_URL = ("https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/"
            "BioC_json/{pmcid}/unicode")

#: Section types the body excludes, mirroring the ==== Body / ==== Ref boundary in
#: get_pmoa_body.sh. BioC labels these on every passage.
NON_BODY = {"TITLE", "ABSTRACT", "REF", "ACK_FUND", "COMP_INT", "SUPPL", "AUTH_CONT",
            "ABBR", "KEYWORD"}

RETRY_DELAYS = (2, 5, 15, 45)


class PmcFetchError(RuntimeError):
    pass


class PmcFetcher:
    def __init__(self, cache_dir: str, min_interval: float = 0.4,
                 contact: str | None = None, timeout: int = 60):
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.contact = contact or os.environ.get("BIOGRAPH_CONTACT_EMAIL") or ""
        self.timeout = timeout
        self._last = 0.0
        os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------------ http

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, url: str) -> str:
        headers = {"User-Agent": f"biograph-benchmark/1.0 ({self.contact})".strip()}
        last_err = None
        for attempt, delay in enumerate((0,) + RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            self._throttle()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    body = resp.read().decode("utf-8", errors="replace")
                # A 429 arrives as an HTML page with a 200-ish body in some paths, so
                # the content type is checked rather than trusted.
                if "json" not in ctype.lower() or body.lstrip().startswith("<"):
                    last_err = f"non-JSON response ({ctype})"
                    continue
                return body
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                if e.code not in (429, 500, 502, 503, 504):
                    raise PmcFetchError(f"{url}: HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(e)
        raise PmcFetchError(f"{url}: gave up after retries ({last_err})")

    # ------------------------------------------------------------------ text

    def _cache_path(self, pmcid: str) -> str:
        return os.path.join(self.cache_dir, f"{pmcid}.json")

    def raw(self, pmcid: str) -> dict:
        path = self._cache_path(pmcid)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except ValueError:
                pass
        body = self._get(BIOC_URL.format(pmcid=urllib.parse.quote(pmcid)))
        data = json.loads(body)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return data

    def body_text(self, pmcid: str) -> str:
        """The article body, as get_pmoa_body.sh would have cut it.

        Returns "" when the article is not in the OA subset or has no body passages --
        the caller counts those rather than substituting an abstract, because a timeline
        scored against a document the annotators never saw is not a measurement."""
        data = self.raw(pmcid)
        try:
            passages = data[0]["documents"][0]["passages"]
        except (KeyError, IndexError, TypeError):
            return ""

        out, seen_body = [], False
        for p in passages:
            infons = p.get("infons") or {}
            section = (infons.get("section_type") or "").upper()
            ptype = (infons.get("type") or "").lower()
            if section == "REF":
                break                      # ==== Ref: everything after is references
            if section in NON_BODY:
                continue
            text = (p.get("text") or "").strip()
            if not text:
                continue
            seen_body = True
            # A section heading is its own passage in BioC; keeping it preserves the
            # narrative structure ("Case presentation", "Discussion") the annotators saw.
            out.append(text)
        return "\n\n".join(out) if seen_body else ""
