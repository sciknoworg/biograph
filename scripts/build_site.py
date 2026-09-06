#!/usr/bin/env python3
"""
Build a biograph subject: optionally draft it from a PDF via an LLM, then
validate it and render dist/<slug>.html.

    python3 scripts/build_site.py <slug>                     build existing subjects/<slug>/
    python3 scripts/build_site.py --all                       build every subject
    python3 scripts/build_site.py <slug> --pdf <paper.pdf>    draft from a PDF first, then build

With --pdf: reads the PDF and asks a chat model, via an OpenAI-compatible
API (OpenRouter, KISSKI, or any other gateway speaking that format), to
draft entities/events/relations/sources against schema/*.schema.json,
embedded in the prompt verbatim so it can't drift from the data model.
Prompts for provider, model, and API key (or set
--base-url/--model/--api-key, or the matching BIOGRAPH_* env vars, to
skip the prompts). A reply that hits the token limit is automatically
continued rather than left truncated.

The same call also judges whether the document even fits this project's
scope (a biographical/historical essay about a person's life intertwined
with a technology's development, not just any paper that mentions them)
-- since the model is already reading the whole thing to extract the
graph, asking it this too is nearly free, and it's a much stronger
signal than a title/abstract guess made before download. A document
judged out of scope is not drafted: nothing is written under subjects/,
and the source PDF passed via --pdf is deleted automatically (pass
--keep-rejected to leave it in place instead) so it doesn't sit around
looking like something worth another look.

Either way, the result is validated against schema/ (structure and
referential integrity) before it's inlined into frontend/template.html.

Optional next step: python3 scripts/find_portraits.py <slug> to attach
verified Wikidata/Commons photos.

Treat an LLM-drafted subject as a first-pass draft, not ground truth —
review it against the PDF before trusting it. See extraction/EXTRACTION_GUIDE.md.
"""
import argparse, getpass, html, json, os, re, shutil, sys, time

# Windows' default console codepage (cp1252) can't encode a lot of the real names/titles this
# project deals with -- this domain is full of non-ASCII names (Kol'tsov, Ström, Niinistö, ...),
# confirmed to crash a plain print() outright with UnicodeEncodeError. UTF-8 handles all of them
# and Windows Terminal/PowerShell render it fine; reconfigure() is a no-op where UTF-8 is already
# the default. scripts that `import build_site` inherit this automatically.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(ROOT, "schema")
SUBJECTS_DIR = os.path.join(ROOT, "subjects")
DATA_DIR = os.path.join(ROOT, "data")
TEMPLATE = os.path.join(ROOT, "frontend", "template.html")
WORLD_GEOJSON = os.path.join(ROOT, "frontend", "world-countries.geo.json")
DIST_DIR = os.path.join(ROOT, "dist")
SCHEMA_FILES = ["date", "entity", "event", "relation", "source"]

# ---------------------------------------------------------------- extraction

PROVIDERS = [  # (label, base_url) -- None means "ask the user to paste one" (e.g. KISSKI)
    ("OpenRouter", "https://openrouter.ai/api/v1"),
    ("Other (paste a base URL)", None),
]

RULES = """\
Rules, non-negotiable:
- Every fact must trace to the text: no inference from general knowledge, no filling gaps.
- An event needs a date (however fuzzy), an event_type, >=1 participant, >=1 source citation --
  and every citation needs a page number (sources[].page: the source's own printed page if
  shown, else the nearest "[pdf page N]" marker). Provenance is exactly where in the text this
  came from, and it is not optional. date.display should quote the source's own wording
  ("early 1970s"); precision and sort_start/sort_end encode that same fuzziness as an ISO
  range -- never a false-precise exact date for a vague one.
- EVERY citation needs sources[].quote: the exact span of the document that states this fact,
  copied character-for-character from the text above -- not paraphrased, not tidied up, not
  re-punctuated. One sentence is usually right; a clause is fine. This is checked mechanically
  against the source afterwards, and anything whose quote isn't found verbatim is reported as
  ungrounded, so a quote you cannot copy exactly is a fact you should not be stating. If you
  cannot point at the words, leave the fact out.
- Keep entities[].summary and events[].label terse and scannable: an expert should read a
  label alone and know what happened ("Moved to Texas Instruments"), not a full sentence
  explaining why. Save extra context for description -- at most one tight sentence, and only
  if the label doesn't already say it.
- ids: snake_case derived from the name/label, unique within their file, and matching
  ^[a-z][a-z0-9_]*$ exactly -- no capitals anywhere, including inside an abbreviation
  ("nishizawa_worked_prc", never "nishizawa_worked_prC").
- Entity resolution: one entities[] object per real-world person/place/organization/artifact,
  no matter how many name forms the source uses for them (full name, surname alone, initials,
  a title, a nickname, an abbreviated org name, an alternate transliteration). Never create a
  second entity for a name variant of someone/something already listed -- record every other
  form you saw for them in that entity's aliases array instead, and use its one id everywhere
  it's referenced in participants/relations.
- entities[].summary is static facts only -- a sentence with a "when" is an event, not a summary.
- Capture connective-tissue events too (an organization founded/sold, a collaborator's
  milestone), not just the subject's own life events. Don't split one episode into many
  events, or merge distinct moments into one.
- relations[] follow the schema's fixed reading direction (e.g. worked_at always reads
  person -> organization). Add one for every event implying a durable connection, linked
  via event_id; add standalone ones (no event_id) for facts stated without a specific date.
- If nothing in an enum fits, use "other" and explain in the description.
- Output ONLY the JSON object -- no markdown fences, no commentary.
"""


def pdf_text(path, max_chars):
    from pypdf import PdfReader
    text = "".join(f"\n\n[pdf page {i}]\n{p.extract_text() or ''}"
                    for i, p in enumerate(PdfReader(path).pages, 1))
    return _truncate(text, max_chars, "PDF text")


def _truncate(text, max_chars, label):
    if len(text) > max_chars:
        print(f"  ({label} is {len(text):,} chars, truncating to {max_chars:,} "
              f"-- raise with --max-chars if your model's context allows more)")
        text = text[:max_chars]
    return text


def source_text(path, max_chars):
    """Text of one source document, whether it arrived as a PDF or as already-extracted text.

    A .txt here is normally CORE's own extracted full text, staged by
    scripts/download_sources.py -- CORE hands the whole document over through its API, so for
    those there's no PDF to fetch or parse at all (and no publisher to be blocked by). Anything
    else is read as a PDF, exactly as before."""
    if os.path.splitext(path)[1].lower() in TEXT_SUFFIXES:
        with open(path, encoding="utf-8", errors="replace") as f:
            return _truncate(f.read(), max_chars, "Source text")
    return pdf_text(path, max_chars)


TEXT_SUFFIXES = {".txt", ".text"}


SCOPE_DEFINITION = """\
This project only covers biographical or historical retrospective essays that follow a
specific person's life intertwined with a specific technology's development -- written by a
historian or domain scientist about that person, long and detailed enough to extract real
dated life events from. A tribute, obituary, festschrift, or memoir written about them by
someone else counts. Out of scope: an ordinary technical/research paper that merely credits
or cites the person, a general survey of a technology with no biographical arc, a document
that happens to share a name with the intended subject but is about someone else, or a paper
*by* the person about their own technical work with no biographical retrospective content.
"""


STRICT_SCOPE_RULES = """\
Four additional requirements, for this automated collection. Reject (fits: false) if ANY fails:

1. English. Judge from the actual text, not from metadata.

2. ONE central figure. The document must trace the life and work of a single named person, with
that one person as its subject throughout. It will naturally discuss colleagues, students and
rivals -- expected and fine, so long as they appear in relation to the one central figure.
Reject a document whose subject is two or more people given comparable weight (parallel or joint
biographies, a family, a research group, a company's founders), and reject a history of a field,
technology, institution or prize in which many contributors are surveyed and no single life is
followed. The test: could you write one person's dated life timeline from this document, and is
that person unambiguously who it is about?

3. Substantial. That person must be a genuinely prolific, significant contributor, and the
document detailed enough to draw a real dated timeline from -- not merely someone with a write-up.

4. Materials science, or an immediately adjacent physical science or engineering field. Their
significant contribution must be to the creation, processing, characterisation or understanding
of materials and the devices built from them -- metallurgy, ceramics, glass, polymers,
semiconductors and electronics, crystallography and crystal growth, thin films and deposition,
composites, magnetic/superconducting/electronic materials, corrosion, fracture and mechanical
behaviour, or the instruments used to study these. Reject anyone whose significance lies outside
that: medicine and clinical practice, surgery and anatomy, biology, pharmacology, geology and
earth science, palaeontology, archaeology, architecture, mathematics, economics, philosophy,
literature, politics and rulers, general history. Judge this from what the DOCUMENT says their
work was, not from what you happen to know about the name -- a person is not in scope merely
because their work involved some technique or apparatus. Ask what field their reputation is IN:
a metallurgist who studied steel is in scope; a surgeon who wrote an anatomy textbook, a monarch,
a glaciologist, a mathematician and a physician who discovered a drug are not, however
distinguished.

"""


def build_prompt(slug, name, text, strict_scope=None):
    schemas = {fn: json.load(open(os.path.join(SCHEMA_DIR, f"{fn}.schema.json"), encoding="utf-8"))
               for fn in SCHEMA_FILES}
    system = (
        "You are extracting a biographical knowledge graph from a source document.\n\n"
        "First, judge whether the document itself fits this project's scope:\n\n"
        + SCOPE_DEFINITION + "\n"
        + (strict_scope or "")
        + "Output a single JSON object with exactly seven top-level keys: scope, subject, "
        'entities, events, relations, sources, related_fields. scope is {"fits": <bool>, '
        '"reason": "<one short sentence>", "subject_name": "<the person the document is '
        'principally about, in the fullest form the document gives, or null if there is no '
        'single such person>"} -- fits must be a real JSON boolean, not a string. Judge scope '
        "from the document text above and nothing else: not from what you already know about "
        "the person, and not from whether the name you were given sounds significant. If "
        "scope.fits is false, the other six keys are not used and may be left empty. "
        "Every object in entities/events/relations/sources must validate against the "
        "matching JSON Schema below (draft 2020-12). related_fields is a plain array of short "
        "strings: other distinct materials-science-history subfields or technology areas this "
        "document discusses as context -- e.g. a related technique it compares against, a "
        "field a mentioned colleague worked in -- beyond the main subject's own field. Empty "
        "array if there's nothing like that. Not validated against a schema; a best-effort list, "
        "used only to help this project notice adjacent subfields worth covering later.\n\n"
        + "\n\n".join(f"{fn}.schema.json:\n{json.dumps(schemas[fn])}" for fn in SCHEMA_FILES)
        + "\n\n" + RULES
    )
    user = (f'subject.json: {{"slug": "{slug}", "name": "{name}", "summary": "<one line>"}}\n\n'
            "Source document text (page markers inserted as [pdf page N]):\n\n" + text)
    return system, user


LLM_RETRY_DELAYS = [10, 30, 90]  # backoff schedule (seconds) for a transient request failure --
                                   # timeout, dropped connection, rate limit, 5xx from an
                                   # overloaded/restarting server (e.g. KISSKI under load). Not
                                   # for malformed JSON -- that's max_json_retries' job below.

READ_TIMEOUT = 360  # seconds of silence (no new chunk) before a streaming request is considered
                     # dead, not just slow -- see call_llm()'s docstring for how this number was
                     # picked (above the longest observed legitimate "thinking" gap, well below
                     # an observed real hang of 800s+ with zero bytes and no error).


def _extract_json_object(text):
    """The first complete top-level JSON object in `text`, or None.

    Scans for a '{' and tracks brace depth to find its matching '}', ignoring braces inside
    string literals (and respecting backslash escapes), so a '}' inside a `reason` string can't
    end the object early. Each candidate span is parsed and returned only if it really is valid
    JSON, so a stray brace in the prose just moves the scan along rather than failing."""
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if escaped:
                escaped = False
                continue
            if ch == "\\" and in_string:
                escaped = True
            elif ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break        # not valid -- resume scanning after this '{'
                        if isinstance(parsed, dict):
                            return parsed
                        break
    return None


class EmptyReplyError(RuntimeError):
    """The model returned zero content and raised no error. Distinct from malformed JSON: an
    empty string is what json.loads() reports as "Expecting value: line 1 column 1 (char 0)",
    which reads like a formatting problem and sends you looking in entirely the wrong place --
    confirmed live, this is exactly how a 100%-failing scope check presented itself."""


def _is_permanent_llm_error(e):
    """True for an error retrying won't fix (bad credentials, bad model name, malformed request)
    -- anything else (timeout, connection drop, rate limit, 5xx, or a genuinely unrecognized
    error) is treated as retryable. Cheap to be permissive here: one extra retry costs far less
    than giving up on a paper over what might just be a momentary server hiccup. Recognizing
    specific openai SDK exception types is best-effort -- an SDK version where these names don't
    exist just means everything is treated as retryable, which is the safer failure mode anyway."""
    try:
        import openai
        return isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError,
                               openai.NotFoundError, openai.BadRequestError))
    except (ImportError, AttributeError):
        return False


def call_llm(system, user, model, base_url, api_key, max_tokens, max_continuations=8, max_json_retries=5):
    """One full reply from the model, as a parsed JSON object. Three independent retry mechanisms
    here, for three independent failure modes:

    1. Transient request failure (timeout, dropped connection, rate limit, 5xx): retried with
       backoff (LLM_RETRY_DELAYS) before falling through to the json_mode=False fallback / giving
       up. A permanent error (bad key, bad model, malformed request) fails immediately instead --
       retrying an auth failure five times wastes time without ever succeeding.
    2. Truncation (finish_reason == "length"): the reply got cut off mid-JSON by max_tokens, not
       broken -- asking the model to continue exactly where it left off (up to max_continuations
       times) recovers it without wasting the tokens already generated.
    3. Malformed JSON (a COMPLETE reply that still isn't valid JSON, or whose top level isn't an
       object): sampling is nondeterministic -- temperature=0.2 still allows real variation, so a
       reply that's malformed once may well be clean on a fresh attempt. Regenerates the whole
       reply from scratch (the original system/user messages, not the broken content) up to
       max_json_retries times before giving up -- a fresh independent attempt, not a "here's what
       you got wrong" correction, since the point is a new sample, not a fix to a bad one.

    Requests are streamed rather than awaited whole, and the client uses a READ timeout (not a
    flat total-duration one): confirmed live against KISSKI, a frozen/overloaded server can hold
    a streaming connection open with zero bytes flowing for 800s+ with no error at all -- the
    openai SDK's own default never caught this, because as long as the connection itself stays
    open, nothing ever raises. A read timeout instead fires if no *new* chunk arrives within
    READ_TIMEOUT seconds, resetting on every chunk received -- so a model that's genuinely still
    thinking (confirmed up to ~290s of silence before the first token, across the slower models
    tested) isn't punished, while a truly dead connection gets caught well before someone's stuck
    watching it for 15 minutes wondering if it's alive. Once it fires, request()'s own backoff
    retry (LLM_RETRY_DELAYS above) picks it up automatically -- a read timeout isn't in
    _is_permanent_llm_error()'s block list, so it's treated as retryable, same as any other
    transient failure."""
    import httpx
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key,
                     timeout=httpx.Timeout(connect=30.0, read=READ_TIMEOUT, write=30.0, pool=30.0))

    def _delta_text(delta):
        """Visible text carried by one streaming delta. Normally delta.content -- but some
        gateway/model combinations answer a plain chat request as a *tool call* instead, putting
        the reply in delta.tool_calls[].function.arguments and leaving delta.content empty.
        Confirmed live on KISSKI: meta-llama-3.1-8b-instruct streams every reply this way,
        finish_reason="tool_calls", 0 content chars, whether or not response_format is sent --
        while the very same request non-streamed returns clean content with finish_reason="stop".
        Reading both fields costs nothing and means a reply never gets silently dropped."""
        if not delta:
            return ""
        out = delta.content or ""
        for call in (getattr(delta, "tool_calls", None) or []):
            fn = getattr(call, "function", None)
            out += (getattr(fn, "arguments", None) or "") if fn else ""
        return out

    def request_once(messages, json_mode, stream=True):
        kwargs = dict(model=model, temperature=0.2, max_tokens=max_tokens, messages=messages)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        if not stream:
            # No stall-watchdog here -- that's the whole reason streaming is preferred. Used only
            # as the last rung of one_attempt()'s ladder, for a model whose streaming path can't
            # be read (see _delta_text above); the client's own httpx timeout still applies.
            choice = client.chat.completions.create(**kwargs).choices[0]
            content = choice.message.content or ""
            for call in (getattr(choice.message, "tool_calls", None) or []):
                fn = getattr(call, "function", None)
                content += (getattr(fn, "arguments", None) or "") if fn else ""
            return content, choice.finish_reason

        kwargs["stream"] = True
        start = last_print = last_content = time.perf_counter()
        content, finish_reason = "", None
        for chunk in client.chat.completions.create(**kwargs):
            if not chunk.choices:
                continue
            now = time.perf_counter()
            piece = _delta_text(chunk.choices[0].delta)
            if piece:
                content += piece
                last_content = now
            finish_reason = chunk.choices[0].finish_reason or finish_reason
            if now - last_print >= 15:
                print(f"  ... {model} is generating -- {len(content):,} chars received so far ({now - start:.0f}s)")
                last_print = now
            if now - last_content > READ_TIMEOUT:
                # Confirmed live: some gateways (KISSKI included) keep sending non-content
                # SSE chunks (keep-alives/pings) while a model is genuinely stalled, which
                # resets httpx's own read timeout below without any real progress ever
                # happening -- observed hangs of 574s and 1000s+ with the transport-level
                # timeout never firing. This tracks time since the last chunk that actually
                # carried visible content instead, so a truly stalled stream still gets
                # caught and handed to request()'s backoff retry.
                raise TimeoutError(f"no content chunk for over {READ_TIMEOUT}s -- stream stalled")
        return content, finish_reason

    def request(messages, json_mode, stream=True):
        """One logical request: retries a transient failure with backoff, raises immediately on
        a permanent one, raises the last error once backoff is exhausted."""
        last_err = None
        for delay in [0] + LLM_RETRY_DELAYS:
            if delay:
                print(f"  (request failed ({last_err}) -- retrying in {delay}s)")
                time.sleep(delay)
            try:
                return request_once(messages, json_mode, stream=stream)
            except Exception as e:
                if _is_permanent_llm_error(e):
                    raise
                last_err = e
        raise last_err

    def request_escalating(messages, json_mode):
        """Ask once, dropping one unsupported-by-somebody feature per rung until something
        actually answers. Rungs, in the order we'd rather keep them:

        1. streaming + response_format -- the preferred shape (stall-watchdog + guaranteed JSON).
        2. streaming, no response_format -- for a model that doesn't support response_format and
           returns empty instead of erroring.
        3. non-streaming -- for a model whose *streaming* path returns nothing readable at all
           (KISSKI's meta-llama-3.1-8b-instruct answers as a tool call; see _delta_text). Costs
           the stall-watchdog, which is why it's last, and acceptable because a model that needs
           this rung has already proven it responds promptly when not streamed.

        An empty reply falls through to the next rung exactly like a raised error does -- both
        mean "this rung didn't work", and a model that silently returns nothing is no more usable
        than one that raises."""
        rungs = [(True, json_mode), (True, False), (False, False)]
        for i, (stream, jm) in enumerate(rungs):
            last = i == len(rungs) - 1
            try:
                piece, finish_reason = request(messages, json_mode=jm, stream=stream)
            except Exception as e:
                if last:
                    sys.exit(f"Request to {base_url} failed for model '{model}': {e}\n\n"
                              f"Check the model name is exactly what your provider lists for chat "
                              f"completions and that your key can access it.")
                continue
            if piece or finish_reason == "length" or last:
                if piece and i:
                    print(f"  (note: fell back to {'non-streaming' if not stream else 'no response_format'} "
                          f"-- '{model}' returned nothing on the preferred request shape)")
                return piece, finish_reason
        raise AssertionError("unreachable")  # the last rung always returns or exits

    def one_attempt():
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        full, rounds = "", 0
        while True:
            # json_mode only on the first round -- a mid-JSON continuation isn't valid JSON on
            # its own, so response_format would reject it.
            piece, finish_reason = request_escalating(messages, json_mode=(rounds == 0))
            if not piece and finish_reason != "length":
                # Every rung came back empty. Say so plainly instead of letting "" fall through
                # to json.loads() and be misreported as malformed JSON.
                raise EmptyReplyError(
                    f"model returned an empty reply (finish_reason={finish_reason}) on every "
                    f"request shape tried: streaming, streaming without response_format, "
                    f"and non-streaming")
            full += piece
            if finish_reason != "length":
                break
            rounds += 1
            if rounds > max_continuations:
                sys.exit(f"Reply hit the {max_tokens}-token limit {max_continuations} times in a row "
                          f"and still isn't finished. Try a smaller --max-chars or larger --max-tokens.")
            print(f"  (reply hit the {max_tokens}-token limit -- asking the model to continue, part {rounds + 1})")
            messages = messages + [{"role": "assistant", "content": piece},
                                    {"role": "user", "content": "Continue the JSON exactly where you left "
                                     "off, character for character -- no repetition, no restarting, "
                                     "no markdown fences, no commentary."}]
        return full

    for attempt in range(1, max_json_retries + 1):
        try:
            full = one_attempt()
        except EmptyReplyError as e:
            if attempt < max_json_retries:
                print(f"  (attempt {attempt}/{max_json_retries}: {e} -- retrying with a fresh sample)")
                continue
            sys.exit(f"Model '{model}' returned an empty reply on every one of "
                      f"{max_json_retries} attempt(s), with and without "
                      f"response_format=json_object, and raised no error either way.\n\n"
                      f"This is the model/endpoint refusing to answer, not a formatting problem. "
                      f"Most likely: '{model}' can't handle a prompt this size ({len(user):,} "
                      f"chars) at {base_url}, or it isn't served for this kind of request. Try a "
                      f"smaller --max-chars, or a different model.")
        content = re.sub(r"^```(json)?|```$", "", full.strip(), flags=re.M).strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # The model answered correctly but wrapped it in conversation ("Here is the JSON
            # object:" before, an explanation of its reasoning after). Confirmed live: every
            # scope check in one run produced a perfectly good verdict inside exactly this kind
            # of padding, and every one was thrown away as "not valid JSON" at character 0.
            # Instructing the model not to editorialise helps but never fully holds, so the
            # object is dug out of the surrounding prose instead of the reply being discarded.
            salvaged = _extract_json_object(content)
            if salvaged is None:
                raise
            print("  (reply had prose around the JSON -- extracted the object from it)")
            data = salvaged
        except json.JSONDecodeError as e:
            if attempt < max_json_retries:
                print(f"  (attempt {attempt}/{max_json_retries}: reply wasn't valid JSON ({e}) -- "
                      f"retrying with a fresh sample)")
                continue
            sys.exit(f"Model's reply still wasn't valid JSON after {max_json_retries} attempt(s) "
                      f"({e}). First 500 chars of the last attempt:\n{content[:500]}")
        if isinstance(data, str):  # some models double-encode: a JSON string containing JSON
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                pass
        if not isinstance(data, dict):
            if attempt < max_json_retries:
                print(f"  (attempt {attempt}/{max_json_retries}: reply's JSON wasn't an object at "
                      f"the top level (got {type(data).__name__}) -- retrying with a fresh sample)")
                continue
            sys.exit(f"Model's JSON wasn't an object at the top level (got {type(data).__name__}) "
                      f"after {max_json_retries} attempt(s).")
        break  # valid object -- done retrying

    if not isinstance(data.get("subject"), dict):
        data["subject"] = {}
    for key in ("entities", "events", "relations", "sources"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _sanitize_id(raw):
    """Coerce a model-supplied id into ^[a-z][a-z0-9_]*$, or None if nothing usable is left."""
    s = re.sub(r"[^a-z0-9_]", "_", str(raw or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if s and s[0].isdigit():
        s = "x_" + s
    return s or None


DATA_FILES = ("entities", "events", "relations", "sources")


def subject_entity(slug, entities, events=(), relations=(), name=None):
    """The entity representing the subject themselves, or None.

    Matched by name when one is given, else by slug (which slugify_name derives from a surname),
    else by whoever participates in the most events and relations -- a biography's subject is by
    definition its most connected person."""
    people = [e for e in entities if isinstance(e, dict) and e.get("entity_type") == "person"]
    if not people:
        return None

    def tokens(n):
        t = [re.sub(r"[^a-z0-9]", "", x.lower()) for x in re.split(r"\s+", n or "")]
        return [x for x in t if x]

    if name:
        want = tokens(name)
        for p in people:
            got = tokens(p.get("name", ""))
            if got and want and got[-1] == want[-1]:
                return p
    for p in people:
        t = tokens(p.get("name", ""))
        if t and t[-1] == slug:
            return p
    degree = {p.get("id"): 0 for p in people}
    for ev in events:
        for part in (ev.get("participants") or []):
            if isinstance(part, dict) and part.get("entity_id") in degree:
                degree[part["entity_id"]] += 1
    for rel in relations:
        for field in ("source", "target"):
            if rel.get(field) in degree:
                degree[rel[field]] += 1
    return max(people, key=lambda p: degree.get(p.get("id"), 0))


def backfill_subject_summary(subject, entities, events=(), relations=()):
    """Give subject.json a one-line summary when the model didn't write one, taking it from the
    subject's own entity -- which almost always has one, since entities[].summary is required to
    be a terse static description. Measured across this repo, half of all subjects were missing
    it while their own entity carried a perfectly good line. Nothing renders subject.summary, so
    this is for whoever is reading subjects/ directly; it is never invented, only copied."""
    if (subject.get("summary") or "").strip():
        return False
    self_ent = subject_entity(subject.get("slug", ""), entities, events, relations,
                              name=subject.get("name"))
    summary = (self_ent or {}).get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False
    subject["summary"] = summary.strip()
    return True


def ensure_subject_json(slug, load):
    """subjects/<slug>/subject.json -- the person-level record: canonical name and slug.

    It sits beside the document folders rather than inside one because it describes the
    *person*, not any single paper about them. That placement makes it look like a stray file
    next to a folder, and it has been deleted by hand as suspected leftover more than once -- so
    rather than failing with a traceback, it is rebuilt here from the extraction itself, which
    is where the name came from in the first place.

    The subject's own entity is identified by matching the slug (derived from a surname by
    slugify_name) against each person's name; failing that, by whoever participates in the most
    events and relations, since a biography's subject is by definition its most connected
    person."""
    path = os.path.join(SUBJECTS_DIR, slug, "subject.json")
    if os.path.isfile(path):
        return load(path)

    entities, events, relations, _ = load_subject_documents(slug, load)
    people = [e for e in entities if isinstance(e, dict) and e.get("entity_type") == "person"]
    if not people:
        sys.exit(f"subjects/{slug}/subject.json is missing and cannot be rebuilt -- no person "
                 f"entity found in this subject's document folder(s) to name it after.")

    chosen = subject_entity(slug, entities, events, relations)
    subject = {"slug": slug, "name": chosen.get("name") or slug.replace("_", " ").title()}
    backfill_subject_summary(subject, entities, events, relations)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(subject, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  (subjects/{slug}/subject.json was missing -- rebuilt it as "
          f"{subject['name']!r}. It records the person, and belongs beside the document "
          f"folder(s), not inside one.)")
    return subject


def load_subject_documents(slug, load):
    """Read every document folder of a subject and combine them into one graph.

    Reconciliation rules, chosen so a single-document subject behaves exactly as it always has:

      entities  -- a repeated id means the same person/place/thing (ids are derived from names
                   within one subject, so "tuomo_suntola" in two papers is one man). The first
                   occurrence wins and later ones only contribute aliases, so nothing a second
                   paper knew about his name forms is lost.
      events,
      relations -- never merged. Two papers describing the same episode are two separate
                   accounts, and deciding they are one claim is exactly the judgment that
                   should not be made silently. An id colliding across documents is prefixed
                   with its document key to keep them distinct and traceable.
      sources   -- concatenated; this is the plural sources.json schema/README.md describes.

    Every event/relation keeps its own sources[] citations, so which document asserted what
    survives the merge -- if two accounts disagree, both are present and attributable."""
    docs = subject_documents(slug)
    if not docs:
        sys.exit(f"subjects/{slug}/ has no document folders (and no entities.json) to build.")

    entities, events, relations, sources = [], [], [], []
    by_id = {}
    for doc_key, ddir in docs:
        d_ent = load(os.path.join(ddir, "entities.json"))
        d_ev = load(os.path.join(ddir, "events.json"))
        d_rel = load(os.path.join(ddir, "relations.json"))
        d_src = load(os.path.join(ddir, "sources.json"))

        for ent in d_ent:
            prior = by_id.get(ent.get("id"))
            if prior is None:
                by_id[ent["id"]] = ent
                entities.append(ent)
                continue
            merged = {*(prior.get("aliases") or []), *(ent.get("aliases") or [])}
            if ent.get("name") and ent["name"] != prior.get("name"):
                merged.add(ent["name"])
            if merged:
                prior["aliases"] = sorted(merged - {prior.get("name")})
            prior.setdefault("summary", ent.get("summary")) if ent.get("summary") else None

        taken = {x["id"] for x in events} | {x["id"] for x in relations}
        for bucket, items in ((events, d_ev), (relations, d_rel)):
            for item in items:
                if doc_key and item.get("id") in taken:
                    item["id"] = f"{doc_key}_{item['id']}"
                bucket.append(item)
        sources += d_src

    return entities, events, relations, sources


def document_key(data, slug):
    """Folder name for one document's extraction under its subject: the source's own citation
    key (sources[0].id, e.g. "puurunen_2014"), which every extraction already produces and a
    human can recognise. Falls back to <slug>_source if the model gave no usable id.

    Crucially, an existing folder holding the SAME document wins over a fresh key. The citation
    key is generated by the model, so re-extracting one paper can produce "nishizawa_2004_thz"
    one time and "nishizawa_2004" the next -- and that silently created a second folder for a
    single paper, whose contents then merged into a graph that double-counted every entity in
    it. Matching on DOI, else on title, makes a retry overwrite in place, which is what a retry
    should do."""
    sources = data.get("sources") or []
    src = sources[0] if sources and isinstance(sources[0], dict) else {}
    key = _sanitize_id(src.get("id")) or f"{slug}_source"

    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()

    doi, title = norm(src.get("doi")), norm(src.get("title"))
    for existing_key, ddir in subject_documents(slug):
        if not existing_key or existing_key == key:
            continue
        try:
            with open(os.path.join(ddir, "sources.json"), encoding="utf-8") as f:
                prior = (json.load(f) or [{}])[0]
        except (OSError, json.JSONDecodeError, IndexError, TypeError):
            continue
        p_doi, p_title = norm(prior.get("doi")), norm(prior.get("title"))
        if (doi and p_doi and doi == p_doi) or (title and p_title and title == p_title):
            print(f"  (this document is already filed as {slug}/{existing_key}/ "
                  f"-- replacing that extraction rather than adding a second folder)")
            return existing_key
    return key


def subject_documents(slug, subjects_dir=None):
    """Every source document folder belonging to one subject, as [(doc_key, dir_path), ...].

    A subject is one *person*; each document that person appears in gets its own folder under
    them, named by that source's citation key (sources[].id, e.g. "puurunen_2014"):

        subjects/suntola/subject.json          <- the person: canonical name, one place
        subjects/suntola/puurunen_2014/        <- one document's extraction, the four files
        subjects/suntola/aris_2019/            <- another, extracted independently

    Keeping each extraction whole and separate is deliberate: reconciling two accounts of the
    same life (same human, different entity ids, the same event described differently) is real
    work, and doing it at write time would mean a bad merge destroys good data. Here it happens
    when the subject is *read*, so a wrong reconciliation is a rendering bug you re-run, never
    lost extraction.

    The older flat layout -- the four files directly under subjects/<slug>/ -- is still read,
    returned as a single unnamed document, so nothing has to migrate before this works."""
    root = os.path.join(subjects_dir or SUBJECTS_DIR, slug)
    if os.path.isfile(os.path.join(root, "entities.json")):
        return [(None, root)]          # legacy flat layout: the subject *is* one document
    if not os.path.isdir(root):
        return []
    return [(d, os.path.join(root, d)) for d in sorted(os.listdir(root))
            if not d.startswith((".", "_")) and os.path.isdir(os.path.join(root, d))
            and os.path.isfile(os.path.join(root, d, "entities.json"))]


def normalize_extraction(data):
    """Repair the mechanical, non-semantic ways a model's JSON misses the schema, before it ever
    reaches validation. Two failures seen live, both trivially fixable and both otherwise fatal
    to an entire extraction:

      1. An id with a capital in it ("nishizawa_worked_prC" -- the model abbreviated a target
         name and kept its capital). Renaming an id is only safe if every reference to it moves
         too, so this rewrites entity references in relations[].source/target and
         events[].participants[].entity_id, and citation references in sources[].source_id.
      2. An optional string field emitted explicitly as null ("doi": null) rather than omitted.
         The schema types these as strings, so null fails where absent would have passed.

    Returns a list of human-readable notes describing what it changed."""
    notes = []

    # --- 1. ids -------------------------------------------------------------------------
    renames = {}   # (kind, old) -> new
    for kind in ("entities", "events", "relations", "sources"):
        seen = set()
        for item in data.get(kind) or []:
            if not isinstance(item, dict):
                continue
            old = item.get("id")
            if isinstance(old, str) and ID_PATTERN.match(old):
                seen.add(old)
                continue
            new = _sanitize_id(old)
            if not new:
                continue
            base, n = new, 2
            while new in seen:      # keep ids unique within their own file
                new, n = f"{base}_{n}", n + 1
            seen.add(new)
            item["id"] = new
            renames[(kind, old)] = new
            notes.append(f"id {old!r} -> {new!r} in {kind}")

    ent_map = {old: new for (kind, old), new in renames.items() if kind == "entities"}
    src_map = {old: new for (kind, old), new in renames.items() if kind == "sources"}

    if ent_map:
        for rel in data.get("relations") or []:
            if isinstance(rel, dict):
                for field in ("source", "target"):
                    if rel.get(field) in ent_map:
                        rel[field] = ent_map[rel[field]]
        for ev in data.get("events") or []:
            if isinstance(ev, dict):
                for p in ev.get("participants") or []:
                    if isinstance(p, dict) and p.get("entity_id") in ent_map:
                        p["entity_id"] = ent_map[p["entity_id"]]
    if src_map:
        for kind in ("events", "relations"):
            for item in data.get(kind) or []:
                if not isinstance(item, dict):
                    continue
                for cite in item.get("sources") or []:
                    if isinstance(cite, dict) and cite.get("source_id") in src_map:
                        cite["source_id"] = src_map[cite["source_id"]]

    # --- 2. explicit nulls where the schema wants a string (or nothing) ------------------
    dropped = 0
    for kind in ("entities", "events", "relations", "sources"):
        for item in data.get(kind) or []:
            if not isinstance(item, dict):
                continue
            for key in [k for k, v in item.items() if v is None]:
                del item[key]
                dropped += 1
    if dropped:
        notes.append(f"dropped {dropped} null-valued optional field(s)")

    return notes


def _flatten_ws(s):
    """Whitespace-insensitive, quote-insensitive form for substring comparison. PDF text
    extraction reflows lines, hyphenates across breaks and swaps quote characters, so comparing
    raw strings would report honest quotes as fabricated -- this normalises exactly the noise
    the extractor introduces, and nothing else. Word characters are left untouched, so a quote
    that names a date or a person the document never mentions still fails, which is the point."""
    s = (s or "").lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                  ("—", "-"), ("–", "-"), ("‐", "-"), ("­", ""),
                  # Typographic ligatures: pypdf hands these back as single codepoints, so a
                  # model quoting "scientific" correctly would never match a source holding
                  # "scienti<fi-ligature>c". Measured on real extractions, folding these is the
                  # single largest source of false "not in source" findings.
                  ("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl"),
                  ("ﬅ", "st"), ("ﬆ", "st"), ("æ", "ae"), ("œ", "oe")):
        s = s.replace(a, b)
    s = re.sub(r"-\s+", "", s)      # de-hyphenate across a line break
    return re.sub(r"\s+", " ", s).strip()


def _shingle_overlap(needle, haystack, n=5):
    """Fraction of the needle's n-word windows that occur in the haystack. Distinguishes a
    quote the model copied imperfectly (nearly all windows present -- one substituted word or a
    changed comma only breaks the windows spanning it) from one it composed (almost none)."""
    words = needle.split()
    if len(words) < n:
        return 1.0 if needle and needle in haystack else 0.0
    windows = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
    return sum(1 for w in windows if w in haystack) / len(windows)


def check_grounding(data, source_text):
    """Verify the model's claims actually appear in the document. Returns (report, stats).

    This is the hallucination check. It is deliberately mechanical rather than a second LLM
    call: an LLM asked to grade its own output shares the priors that produced it, whereas
    "does this string occur in the source" cannot be talked into agreeing. Two things are
    checked, both cheap:

      quotes  -- every sources[].quote must occur verbatim in the document (modulo the
                 whitespace/hyphenation noise PDF extraction introduces). A quote that isn't
                 there was composed, not copied.
      names   -- every entity name should appear in the document. Checked on the longest
                 word of the name (usually the surname) rather than the full string, since a
                 document may write "J. B. Goodenough" where the graph says "John B.
                 Goodenough" -- a missing surname, though, means the entity came from the
                 model's memory rather than the page.

    Reported, not enforced, by default: extraction is a first-pass draft that a human reviews,
    and a strict gate would throw away good work over PDF-extraction artefacts. extract()
    decides what to do with the numbers."""
    haystack = _flatten_ws(source_text)
    report, near_misses, checked_quotes, bad_quotes = [], [], 0, 0

    for kind in ("events", "relations"):
        for item in data.get(kind) or []:
            if not isinstance(item, dict):
                continue
            for cite in item.get("sources") or []:
                quote = (cite or {}).get("quote") if isinstance(cite, dict) else None
                if not (quote or "").strip():
                    continue
                checked_quotes += 1
                # A quote may legitimately elide with "..." / "[...]" / "…". Each side of the
                # ellipsis still has to be in the document -- we just don't demand they be
                # contiguous, which would report an honest abridged quote as fabricated.
                fragments = [f for f in re.split(r"\s*(?:\[\s*\.\.\.\s*\]|\.\.\.|…)\s*",
                                                  _flatten_ws(quote)) if len(f) > 12]
                if not fragments:
                    fragments = [_flatten_ws(quote)]
                if all(f in haystack for f in fragments):
                    continue
                # Not verbatim -- but "off by one word" and "invented outright" are different
                # findings, and reporting them identically makes the whole check ignorable.
                # Overlap is measured in 5-word shingles: a misquote keeps nearly all of them,
                # a fabrication shares almost none.
                overlap = _shingle_overlap(" ".join(fragments), haystack)
                bad_quotes += 1
                if overlap >= 0.5:
                    near_misses.append(f"    {kind[:-1]} {item.get('id')}: misquoted "
                                        f"({overlap:.0%} of it is in the source, but not "
                                        f"verbatim) -- {quote.strip()[:90]!r}")
                else:
                    report.append(f"    {kind[:-1]} {item.get('id')}: NOT IN SOURCE "
                                  f"({overlap:.0%} overlap) -- {quote.strip()[:90]!r}")

    missing_names = []
    for ent in data.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        name = (ent.get("name") or "").strip()
        if not name:
            continue
        # Any recorded name form counts: the schema exists precisely so a document writing "MIT"
        # or "J. B. Goodenough" still matches an entity named in full. Checking only the primary
        # name would flag correct entity resolution as if it were invention.
        forms = [name] + [a for a in (ent.get("aliases") or []) if isinstance(a, str)]
        grounded = False
        for form in forms:
            words = [w for w in re.split(r"[\s.,]+", _flatten_ws(form)) if len(w) > 2]
            anchor = max(words, key=len) if words else _flatten_ws(form)
            if anchor and anchor in haystack:
                grounded = True
                break
        if not grounded:
            missing_names.append(f"    entity {ent.get('id')}: name not in source -- {name!r}")
    report += near_misses + missing_names

    stats = {"quotes_checked": checked_quotes, "quotes_unverified": bad_quotes,
             "quotes_fabricated": len([r for r in report if "NOT IN SOURCE" in r]),
             "quotes_misquoted": len(near_misses),
             "entities_checked": len([e for e in data.get("entities") or [] if isinstance(e, dict)]),
             "entities_unverified": len(missing_names)}
    return report, stats


def parse_scope(data):
    """Normalize the model's `scope` verdict. Anything that isn't a clean
    {"fits": <real bool>, ...} -- missing, malformed, "fits" as a string -- is treated as
    unknown (None), not guessed at: deleting the user's PDF is not something to do on a shaky
    signal, so extract() fails open (proceeds) on None, same as everywhere else in this repo
    that degrades an LLM judgment rather than trusting a malformed reply."""
    if not isinstance(data, dict):
        return None
    # The verdict is asked for as {"scope": {...}}, but a smaller model routinely returns the
    # inner object on its own, or nests it under a synonym. Insisting on the exact shape means
    # a perfectly clear verdict reads as "malformed" and the caller falls open -- measured on a
    # real run, that path admitted every single document that got extracted, and the scope rules
    # were never actually consulted. So accept the verdict wherever it plainly is.
    scope = None
    for key in ("scope", "verdict", "judgment", "judgement", "result"):
        if isinstance(data.get(key), dict) and "fits" in data[key]:
            scope = data[key]
            break
    if scope is None and "fits" in data:
        scope = data                      # unwrapped: the reply *is* the verdict
    if not isinstance(scope, dict):
        return None

    fits = _as_bool(scope.get("fits"))
    if fits is None:
        return None
    return {"fits": fits, "reason": (scope.get("reason") or "").strip()}


def _as_bool(value):
    """A real bool from what a model actually emits for one: True, "true", "yes", 1 -- and the
    negatives. Anything genuinely undecidable stays None, so an ambiguous verdict is still
    treated as no verdict rather than guessed at."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().strip('."\'').lower()
        if v in ("true", "yes", "y", "1", "fits", "in scope", "in-scope"):
            return True
        if v in ("false", "no", "n", "0", "does not fit", "out of scope", "out-of-scope"):
            return False
    return None


def stage_source(pdf_path, slug, text, keep_pdf=False):
    """Archive the source under data/ and return its repo-relative path.

    What gets archived is the *extracted text*, not the PDF. That text is exactly what the model
    was shown, so it is what check_grounding() must compare against later -- and measured across
    this repo's own sources it is 3.5% of the PDF's size (531 KB against 15.2 MB). Keeping the
    PDF as well would multiply storage roughly 30x to retain bytes nothing downstream reads:
    validation, rendering and the built page never touch the source file, and re-downloading
    the PDF later is only ~29% likely to succeed anyway (publishers 403 most requests), so the
    PDF is the copy worth losing and the text is the copy worth keeping.

    The bibliographic record for re-obtaining the original lives in sources.json (DOI, title,
    authors, year, venue) and the manifest (exact download_url and provider), so nothing about
    provenance is lost by not holding the bytes.

    --keep-source-pdf archives the PDF alongside, for anyone who wants the original on hand."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if keep_pdf and os.path.isfile(pdf_path):
        ext = os.path.splitext(pdf_path)[1].lower() or ".pdf"
        dest = os.path.join(DATA_DIR, f"{slug}{ext}")
        if os.path.abspath(pdf_path) != os.path.abspath(dest):
            shutil.copyfile(pdf_path, dest)
    rel = os.path.join("data", f"{slug}.txt")
    with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
        f.write(text)
    return rel


def choose_base_url():
    print("Model provider:")
    for i, (label, _) in enumerate(PROVIDERS, 1):
        print(f"  {i}. {label}")
    choice = input(f"Choose [1-{len(PROVIDERS)}]: ").strip()
    try:
        _, url = PROVIDERS[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit(f"Invalid choice: {choice!r}")
    return url or input("Base URL: ").strip()


def choose_model():
    model = input("Model name, exactly as your provider lists it "
                   "(e.g. gpt-5.5, anthropic/claude-opus-4.6, meta-llama/llama-4-maverick): ").strip()
    return model or sys.exit("a model name is required")


def extract(pdf_path, slug, name, model, base_url, api_key, max_chars, max_tokens,
            delete_out_of_scope=True, related_fields_out=None, keep_source_pdf=False,
            strict_scope=False, scope_out=None):
    print(f"Reading {pdf_path}...")
    text = source_text(pdf_path, max_chars)
    system, user = build_prompt(slug, name, text,
                                 strict_scope=STRICT_SCOPE_RULES if strict_scope else None)
    print(f"Asking {model} to draft the graph ({len(text):,} chars of source text)...")
    start = time.perf_counter()
    data = call_llm(system, user, model, base_url, api_key, max_tokens)
    print(f"  ({time.perf_counter() - start:.1f}s)")

    scope = parse_scope(data)
    if scope_out:
        # The verdict and who the document is really about, for run_pipeline.py: it files the
        # subject under that person rather than whichever search term happened to surface the
        # document. Written on rejection too, so a caller can log why without re-reading the log.
        raw = data.get("scope") if isinstance(data.get("scope"), dict) else data
        who = raw.get("subject_name") if isinstance(raw, dict) else None
        with open(scope_out, "w", encoding="utf-8") as f:
            json.dump({"fits": (scope or {}).get("fits", True),
                       "reason": (scope or {}).get("reason", ""),
                       "subject_name": who if isinstance(who, str) and who.strip() else None},
                      f, ensure_ascii=False)
    if scope is not None and not scope["fits"]:
        print(f"\nOut of scope: {scope['reason'] or '(the model gave no reason)'}")
        if delete_out_of_scope:
            try:
                os.remove(pdf_path)
                print(f"  deleted {pdf_path} (pass --keep-rejected to leave a rejected PDF in place instead)")
            except OSError as e:
                print(f"  (couldn't delete {pdf_path}: {e})")
        else:
            print(f"  leaving {pdf_path} in place (--keep-rejected)")
        sys.exit(f"'{slug}' was not drafted -- {os.path.basename(pdf_path)} doesn't fit this "
                 f"project's scope. See SCOPE_DEFINITION in scripts/build_site.py, or "
                 f"extraction/EXTRACTION_GUIDE.md, for what does.")

    for note in normalize_extraction(data):
        print(f"  (normalized: {note})")

    # Hallucination check -- see check_grounding(). Reported, not enforced: this is a first-pass
    # draft either way, and PDF text extraction is lossy enough that a hard gate would discard
    # good work. A high unverified count is the signal to distrust this draft.
    issues, gstats = check_grounding(data, text)
    if gstats["quotes_checked"] or gstats["entities_checked"]:
        print(f"  grounding: {gstats['quotes_checked'] - gstats['quotes_unverified']}"
              f"/{gstats['quotes_checked']} quotes found verbatim in the source, "
              f"{gstats['entities_checked'] - gstats['entities_unverified']}"
              f"/{gstats['entities_checked']} entity names present")
    for line in issues[:15]:
        print(line)
    if len(issues) > 15:
        print(f"    ... and {len(issues) - 15} more")
    if gstats["quotes_checked"] == 0:
        print("  (no quotes to verify -- provenance carries no quotes, so nothing here is "
              "mechanically grounded)")

    data["subject"]["slug"] = slug
    data["subject"].setdefault("name", name)
    if backfill_subject_summary(data["subject"], data["entities"], data["events"],
                                 data["relations"]):
        print(f"  (subject.json had no summary -- took one from {name}'s own entity)")
    file_rel = stage_source(pdf_path, slug, text, keep_pdf=keep_source_pdf)
    if data["sources"]:
        data["sources"][0]["file"] = file_rel  # trust our own copy, not the model's guess

    # subject.json describes the *person* and lives at the top; this document's four files go
    # in their own folder beneath, named by its citation key (sources[0].id). A second paper
    # about the same person lands beside this one instead of overwriting it -- see
    # subject_documents() for why extractions are kept whole rather than merged on write.
    sdir = os.path.join(SUBJECTS_DIR, slug)
    doc_key = document_key(data, slug)
    ddir = os.path.join(sdir, doc_key)
    os.makedirs(ddir, exist_ok=True)
    with open(os.path.join(sdir, "subject.json"), "w", encoding="utf-8") as f:
        json.dump(data["subject"], f, indent=2, ensure_ascii=False)
        f.write("\n")
    for key in DATA_FILES:
        with open(os.path.join(ddir, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(data[key], f, indent=2, ensure_ascii=False)
            f.write("\n")
    print(f"  wrote subjects/{slug}/{doc_key}/ ({len(data['entities'])} entities, "
          f"{len(data['events'])} events, {len(data['relations'])} relations, "
          f"{len(data['sources'])} sources)")

    if related_fields_out:
        related = [f.strip() for f in data.get("related_fields") or []
                   if isinstance(f, str) and f.strip()]
        with open(related_fields_out, "w", encoding="utf-8") as f:
            json.dump(related, f, ensure_ascii=False)
        if related:
            print(f"  related fields mentioned: {', '.join(related)}")


# ---------------------------------------------------------------- validate + build

# Fixed reading direction for every relation.schema.json type: (allowed source
# entity_types, allowed target entity_types). Keep in sync with that enum --
# see schema/README.md "Extending the vocabularies".
RELATION_DIRECTIONS = {
    "born_in": (("person",), ("place",)),
    "died_in": (("person",), ("place",)),
    # "organization" as well as "place", matching "visited" below: people genuinely reside at
    # institutions -- colleges, monasteries, hospitals -- and such a building is honestly both.
    # A model that types Gresham College as an organization (correct) and says Hooke lived there
    # (correct) was producing an extraction the validator then threw away whole, which cost a
    # full heavy call per attempt and lost 12 entities and 12 events over a single relation.
    "lived_in": (("person",), ("place", "organization")),
    "visited": (("person",), ("place", "organization")),
    "relocated_to": (("person",), ("place",)),
    "worked_at": (("person",), ("organization",)),
    "employed_by": (("person",), ("organization",)),
    "founded": (("person", "organization"), ("organization",)),
    "member_of": (("person", "organization"), ("organization",)),
    "supervised_by": (("person",), ("person",)),
    "mentored": (("person",), ("person",)),
    "collaborated_with": (("person",), ("person", "organization")),
    "met": (("person",), ("person",)),
    "married_to": (("person",), ("person",)),
    "family_of": (("person",), ("person",)),
    "studied_at": (("person",), ("organization",)),
    "educated_by": (("person",), ("person",)),
    "invented": (("person", "organization"), ("artifact",)),
    "patented": (("person", "organization"), ("artifact",)),
    "published": (("person", "organization"), ("artifact",)),
    "developed": (("person", "organization"), ("artifact",)),
    "awarded": (("person", "organization"), ("artifact",)),
    "licensed_to": (("organization",), ("organization",)),
    "acquired_by": (("organization",), ("organization",)),
    "sold_to": (("organization",), ("organization",)),
    "renamed_to": (("organization",), ("organization",)),
    "corresponded_with": (("person",), ("person",)),
}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_subject(slug):
    """Validate the subject's four data files against the JSON Schemas.
    Returns (entities, events, relations, sources). Raises on any error."""
    try:
        from jsonschema import Draft202012Validator, RefResolver
    except ImportError:
        print("  (jsonschema not installed -- skipping schema validation; "
              "pip install jsonschema to enable it)")
        Draft202012Validator = None

    entities, events, relations, sources = load_subject_documents(slug, load)

    if Draft202012Validator:
        store = {}
        for fn in SCHEMA_FILES:
            schema = load(os.path.join(SCHEMA_DIR, f"{fn}.schema.json"))
            store[schema["$id"]] = schema
        errors = []

        def check(schema_name, items):
            schema = store[f"https://biograph/schema/{schema_name}.schema.json"]
            resolver = RefResolver.from_schema(schema, store=store)
            v = Draft202012Validator(schema, resolver=resolver)
            for it in items:
                for e in v.iter_errors(it):
                    errors.append(f"{schema_name} {it.get('id')}: {e.message}")

        check("entity", entities)
        check("event", events)
        check("relation", relations)
        check("source", sources)

        ent_ids = {e["id"] for e in entities}
        ent_type = {e["id"]: e["entity_type"] for e in entities}
        src_ids = {s["id"] for s in sources}
        event_ids = {e["id"] for e in events}
        for ev in events:
            for p in ev["participants"]:
                if p["entity_id"] not in ent_ids:
                    errors.append(f"event {ev['id']}: unknown participant '{p['entity_id']}'")
            if ev.get("location") and ev["location"] not in ent_ids:
                errors.append(f"event {ev['id']}: unknown location '{ev['location']}'")
            for s in ev["sources"]:
                if s["source_id"] not in src_ids:
                    errors.append(f"event {ev['id']}: unknown source '{s['source_id']}'")
        for r in relations:
            src_ok, tgt_ok = r["source"] in ent_ids, r["target"] in ent_ids
            if not src_ok:
                errors.append(f"relation {r['id']}: unknown source entity '{r['source']}'")
            if not tgt_ok:
                errors.append(f"relation {r['id']}: unknown target entity '{r['target']}'")
            if src_ok and tgt_ok:  # both resolve -- check the vocabulary's fixed reading direction
                exp_src, exp_tgt = RELATION_DIRECTIONS.get(r["type"], ((), ()))
                got_src, got_tgt = ent_type[r["source"]], ent_type[r["target"]]
                if exp_src and got_src not in exp_src:
                    errors.append(f"relation {r['id']}: '{r['type']}' expects source entity_type "
                                  f"{'/'.join(exp_src)}, but '{r['source']}' is '{got_src}'")
                if exp_tgt and got_tgt not in exp_tgt:
                    errors.append(f"relation {r['id']}: '{r['type']}' expects target entity_type "
                                  f"{'/'.join(exp_tgt)}, but '{r['target']}' is '{got_tgt}'")
            if r.get("event_id") and r["event_id"] not in event_ids:
                errors.append(f"relation {r['id']}: unknown event_id '{r['event_id']}'")
            for s in r["sources"]:
                if s["source_id"] not in src_ids:
                    errors.append(f"relation {r['id']}: unknown source '{s['source_id']}'")

        if errors:
            raise SystemExit("Validation failed for subject '%s':\n  " % slug + "\n  ".join(errors))

    return entities, events, relations, sources


def build(slug):
    print(f"Building '{slug}'...")
    subject = ensure_subject_json(slug, load)
    entities, events, relations, sources = validate_subject(slug)
    events_sorted = sorted(events, key=lambda e: (e["date"]["sort_start"], e["date"]["sort_end"]))

    payload = {"subject": subject, "entities": entities, "events": events_sorted,
               "relations": relations, "sources": sources}
    data_json_safe = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    with open(WORLD_GEOJSON, encoding="utf-8") as f:
        world_json_safe = f.read().replace("</", "<\\/")

    out = (open(TEMPLATE, encoding="utf-8").read()
           .replace("__SUBJECT_NAME__", html.escape(subject["name"]))
           .replace("__SUBJECT_SUMMARY__", html.escape(subject.get("summary", "")))
           .replace("__GRAPH_DATA_JSON__", data_json_safe)
           .replace("__WORLD_TOPOJSON_JSON__", world_json_safe))

    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"  {len(entities)} entities, {len(events)} events, {len(relations)} relations")
    print(f"  -> {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--all", action="store_true", help="build every subject under subjects/")
    ap.add_argument("--pdf", help="draft the subject from this source document before building "
                                   "(a PDF, or a .txt of already-extracted text)")
    ap.add_argument("--text", help="same as --pdf, named for clarity when the source is a .txt "
                                    "of already-extracted text (e.g. CORE's own full text)")
    ap.add_argument("--strict-scope", action="store_true",
                     help="apply this collection's extra scope rules on top of SCOPE_DEFINITION: "
                          "English, one central figure, substantial, and materials science or an "
                          "adjacent field. For automated bulk collection -- a person choosing one "
                          "document by hand is not second-guessed by them")
    ap.add_argument("--scope-out",
                     help="write the scope verdict as JSON to this path: {fits, reason, "
                          "subject_name}. subject_name is who the document is actually about, "
                          "which is not always who you searched for")
    ap.add_argument("--keep-source-pdf", action="store_true",
                     help="also archive the source PDF under data/, alongside the extracted "
                          "text. Off by default: the text is what the model actually read and "
                          "what --check-grounding verifies against, at ~3.5% of the PDF's size, "
                          "and sources.json/the manifest already record DOI, url and provider "
                          "for re-obtaining the original")
    ap.add_argument("--check-grounding", action="store_true",
                     help="audit an existing subject against its own source document: report "
                          "which sources[].quote values actually occur in it and which entity "
                          "names appear, then exit. The hallucination check, re-runnable after "
                          "the fact -- it also runs automatically during --pdf extraction")
    ap.add_argument("--name", help="display name for --pdf (default: slug, title-cased)")
    ap.add_argument("--model", default=os.environ.get("BIOGRAPH_MODEL"), help="for --pdf; prompted if unset")
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"), help="for --pdf; prompted if unset")
    ap.add_argument("--api-key", default=os.environ.get("BIOGRAPH_API_KEY"))
    ap.add_argument("--max-chars", type=int, default=180_000, help="for --pdf: truncate source text beyond this")
    ap.add_argument("--max-tokens", type=int, default=32_000, help="for --pdf: reply budget per request")
    ap.add_argument("--keep-rejected", action="store_true",
                     help="for --pdf: don't delete the source PDF when the model judges it out of "
                          "scope -- leave it in place for a closer look instead")
    ap.add_argument("--related-fields-out",
                     help="for --pdf: write the model's related_fields list (subfields/tech areas "
                          "mentioned in the document beyond its main subject) to this path as JSON "
                          "-- opt-in, for run_pipeline.py's taxonomy growth; not written otherwise")
    args = ap.parse_args()

    if args.all:
        slugs = sorted(d for d in os.listdir(SUBJECTS_DIR)
                        if os.path.isdir(os.path.join(SUBJECTS_DIR, d)) and not d.startswith("_"))
        for slug in slugs:
            build(slug)
        return
    if not args.slug:
        ap.error("provide a subject slug, or --all")

    if args.check_grounding:
        ents, evs, rels, srcs = load_subject_documents(
            args.slug, lambda p: json.load(open(p, encoding="utf-8")))
        data = {"entities": ents, "events": evs, "relations": rels, "sources": srcs}
        files = [s.get("file") for s in data["sources"] if isinstance(s, dict) and s.get("file")]
        if not files:
            sys.exit(f"subjects/{args.slug}/sources.json records no source file to check against.")
        text = ""
        for rel in files:
            path = os.path.join(ROOT, rel.replace("\\", os.sep).replace("/", os.sep))
            if not os.path.isfile(path):
                print(f"  (source file missing, skipped: {rel})")
                continue
            text += source_text(path, args.max_chars)
        if not text:
            sys.exit("None of this subject's source files are present -- nothing to check against.")
        issues, stats = check_grounding(data, text)
        print(f"{args.slug}: {stats['quotes_checked'] - stats['quotes_unverified']}"
              f"/{stats['quotes_checked']} quotes verbatim, "
              f"{stats['entities_checked'] - stats['entities_unverified']}"
              f"/{stats['entities_checked']} entity names present")
        for line in issues:
            print(line)
        sys.exit(1 if issues else 0)

    if args.pdf and args.text:
        ap.error("pass --pdf or --text, not both -- they're the same argument under two names")
    source = args.pdf or args.text

    if source:
        if not re.match(r"^[a-z][a-z0-9_]*$", args.slug):
            sys.exit(f"slug must match ^[a-z][a-z0-9_]*$, got '{args.slug}'")
        base_url = args.base_url or choose_base_url()
        model = args.model or choose_model()
        api_key = args.api_key or getpass.getpass(f"API key for {base_url}: ")
        name = args.name or args.slug.replace("_", " ").title()
        try:
            extract(source, args.slug, name, model, base_url, api_key, args.max_chars, args.max_tokens,
                    delete_out_of_scope=not args.keep_rejected,
                    related_fields_out=args.related_fields_out,
                    keep_source_pdf=args.keep_source_pdf,
                    strict_scope=args.strict_scope, scope_out=args.scope_out)
        except Exception as e:  # anything not already a deliberate sys.exit() inside extract()
            sys.exit(f"Extraction failed unexpectedly ({type(e).__name__}: {e}) -- the source "
                      f"document may be corrupt, unreadable, or empty.")

    try:
        build(args.slug)
    except SystemExit as e:
        if not source:
            raise
        sys.exit(f"\n{e}\n\nThis is a first-pass draft -- fix the errors above in "
                  f"subjects/{args.slug}/*.json (or re-run) before building. "
                  f"See extraction/EXTRACTION_GUIDE.md for the data model.")

    if source:
        print(f"\nTreat this as a first-pass draft -- review subjects/{args.slug}/*.json "
              f"against {source} before trusting it.")


if __name__ == "__main__":
    main()
