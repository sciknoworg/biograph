#!/usr/bin/env python3
"""Probe every model an OpenAI-compatible endpoint offers, and report how each one behaves.

Written to hand to a provider's engineers. It uses no private data and nothing from this
project: the prompts are generated here, so anyone can re-run it and get comparable numbers.

WHY. Extracting a knowledge graph from a paper needs one model call that returns tens of
thousands of tokens of schema-valid JSON. Several models failed at that, and the failures were
not alike:

  - one produced valid, completely EMPTY JSON three times, exiting cleanly each time
  - one never finished inside 40 minutes
  - one returned content but violated a closed enum the prompt had given it
  - one streamed nothing at all for ~270s before its first token

Those need different fixes and only some of them are ours, so this separates them. Each model
gets two probes:

  SMOKE  a trivial prompt, 64 tokens out. Answers "does this model respond at all, and how
         quickly does it start?" If smoke fails, nothing else about the model matters.

  LOAD   a prompt of roughly the size we really send (~20k tokens) asking for a long, strictly
         structured JSON array. Answers "can it sustain long structured output?" -- which is the
         thing that actually broke.

WHAT IS MEASURED. Per probe: HTTP outcome, time to first token, total wall time, completion
tokens, tokens/second, finish_reason, and whether the content was empty or unparseable. Time to
first token is reported separately from total because a model that thinks for four minutes and
then streams quickly is a different problem from one that streams slowly throughout, and the
two need different answers from a provider.

CREDENTIALS come from the environment, never a command line: a key in argv lands in shell
history and in any log that echoes the command.

    export BIOGRAPH_API_KEY=...        # or pass --api-key-env SOME_OTHER_VAR
    python scripts/kisski_model_probe.py --base-url https://chat-ai.academiccloud.de/v1
    python scripts/kisski_model_probe.py --models qwen3.5-397b-a17b,glm-5.3-flash
    python scripts/kisski_model_probe.py --out report.md
"""
from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time

#: Roughly the input size this project really sends, built from filler so the probe carries no
#: private text and anyone can reproduce it. The content is deliberately dull: the point is the
#: token count and the output demand, not comprehension.
FILLER_SENTENCE = (
    "In {year}, researcher number {n} joined the institute at site {n} and published a study "
    "on topic {n}, which was later cited by colleague {n} in a review of the field. ")

SMOKE_PROMPT = "Reply with exactly the word: ready"

#: The load probe asks for a long, strictly-shaped JSON array. Structured output is the actual
#: requirement -- a model that writes fluent prose but cannot hold a shape for 10,000 tokens is
#: no use for extraction, and that distinction is invisible in a short test.
LOAD_INSTRUCTION = (
    "Read the record list above. Return a single JSON object with one key, \"records\", whose "
    "value is an array of exactly {k} objects. Each object must have exactly these four keys: "
    "\"id\" (integer, 1 to {k}), \"year\" (integer), \"topic\" (string), \"cited_by\" (string). "
    "Take the values from the corresponding line of the record list. Output only the JSON "
    "object, with no commentary before or after it.")


def build_load_input(approx_tokens: int, k: int) -> str:
    """A deterministic input of about the requested token size (~4 chars per token)."""
    target = approx_tokens * 4
    parts, n = [], 0
    while sum(len(p) for p in parts) < target:
        n += 1
        parts.append(FILLER_SENTENCE.format(year=1900 + (n % 120), n=n))
    lines = ["record %d: year %d, topic T%d, cited_by C%d" % (i, 1900 + (i % 120), i, i)
             for i in range(1, k + 1)]
    return "".join(parts) + "\n\nRecord list:\n" + "\n".join(lines)


def list_models(client) -> list[str]:
    try:
        return sorted(m.id for m in client.models.list().data)
    except Exception as e:                                        # noqa: BLE001
        raise SystemExit("could not list models from this endpoint: %s" % e)


def probe(client, model: str, system: str, user: str, max_tokens: int, timeout: float) -> dict:
    """One streamed call. Streaming is what makes time-to-first-token observable at all."""
    out = {"model": model, "max_tokens": max_tokens, "ok": False, "error": None,
           "ttft_s": None, "total_s": None, "chars": 0, "completion_tokens": None,
           "finish_reason": None, "empty": None, "tok_per_s": None,
           # Reasoning models stream their thinking in a separate field and emit no content
           # until it finishes. Counting only content makes them look mute: qwen3.5-397b-a17b
           # answered a one-word prompt for 38.9s and produced zero content chars, because a
           # 64-token budget was spent reasoning. That is a budget mistake, not a broken model,
           # and a report that conflates them would send a provider chasing the wrong thing.
           "reasoning_chars": 0, "ttft_reasoning_s": None}
    start = time.perf_counter()
    first = None
    first_reasoning = None
    chunks = []
    reasoning = []
    try:
        stream = client.chat.completions.create(
            model=model, temperature=0, max_tokens=max_tokens, stream=True,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            timeout=timeout)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                if first is None:
                    first = time.perf_counter() - start
                chunks.append(piece)
            think = (getattr(delta, "reasoning_content", None)
                     or getattr(delta, "reasoning", None))
            if think:
                if first_reasoning is None:
                    first_reasoning = time.perf_counter() - start
                reasoning.append(think)
            if chunk.choices[0].finish_reason:
                out["finish_reason"] = chunk.choices[0].finish_reason
        out["ok"] = True
    except Exception as e:                                        # noqa: BLE001
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:600])

    out["total_s"] = round(time.perf_counter() - start, 1)
    out["ttft_s"] = round(first, 1) if first is not None else None
    out["ttft_reasoning_s"] = (round(first_reasoning, 1)
                               if first_reasoning is not None else None)
    out["reasoning_chars"] = sum(len(x) for x in reasoning)
    text = "".join(chunks)
    out["text"] = text
    out["chars"] = len(text)
    out["empty"] = out["ok"] and not text.strip()
    if text and out["total_s"]:
        out["tok_per_s"] = round((len(text) / 4) / out["total_s"], 1)
    return out


def check_json(raw: str, k: int) -> str:
    """Did the load probe actually return the shape it was asked for?"""
    if not raw.strip():
        return "empty"
    try:
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:                                             # noqa: BLE001
        return "unparseable"
    recs = data.get("records")
    if not isinstance(recs, list):
        return "no records array"
    if len(recs) != k:
        return "%d of %d records" % (len(recs), k)
    bad = [r for r in recs if not isinstance(r, dict)
           or set(r) != {"id", "year", "topic", "cited_by"}]
    return "ok" if not bad else "%d malformed objects" % len(bad)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("BIOGRAPH_BASE_URL"),
                    help="OpenAI-compatible endpoint (default: $BIOGRAPH_BASE_URL)")
    ap.add_argument("--api-key-env", default="BIOGRAPH_API_KEY",
                    help="NAME of the variable holding the key -- never the key itself")
    ap.add_argument("--models", help="comma-separated; default is every model the endpoint lists")
    ap.add_argument("--input-tokens", type=int, default=20000,
                    help="approximate size of the load probe's input (default 20000)")
    ap.add_argument("--records", type=int, default=400,
                    help="objects the load probe must return; drives output length (default 400)")
    ap.add_argument("--max-tokens", type=int, default=16000,
                    help="reply budget for the load probe")
    ap.add_argument("--smoke-tokens", type=int, default=768,
                    help="reply budget for the smoke probe (default 768). Not 64: a reasoning "
                         "model spends its budget thinking before it emits any content, so a "
                         "small budget makes it look mute")
    ap.add_argument("--timeout", type=float, default=900, help="seconds per request")
    ap.add_argument("--skip-load", action="store_true", help="smoke probe only")
    ap.add_argument("--out", default="kisski_model_probe_report.md")
    args = ap.parse_args(argv)

    if len(args.api_key_env) > 64 or any(c in args.api_key_env for c in "-.:/"):
        raise SystemExit("--api-key-env takes the NAME of an environment variable, not the key. "
                         "The value passed has not been echoed.")
    key = os.environ.get(args.api_key_env)
    if not (args.base_url and key):
        raise SystemExit("need --base-url and a key in $%s" % args.api_key_env)

    from openai import OpenAI
    client = OpenAI(base_url=args.base_url, api_key=key)

    models = ([m.strip() for m in args.models.split(",") if m.strip()] if args.models
              else list_models(client))
    print("endpoint: %s" % args.base_url)
    print("models  : %d" % len(models))
    print("load    : ~%d tokens in, %d records out, max_tokens %d, timeout %ds\n"
          % (args.input_tokens, args.records, args.max_tokens, args.timeout))

    load_user = build_load_input(args.input_tokens, args.records)
    load_system = LOAD_INSTRUCTION.format(k=args.records)
    rows = []

    for i, model in enumerate(models, 1):
        print("[%d/%d] %-34s" % (i, len(models), model), end=" ", flush=True)
        smoke = probe(client, model, "You are a helpful assistant.", SMOKE_PROMPT,
                      args.smoke_tokens, args.timeout)
        row = {"model": model, "smoke": smoke, "load": None, "shape": None}
        if not smoke["ok"]:
            print("smoke FAILED (%s)" % (smoke["error"] or "")[:60])
            rows.append(row)
            continue
        think = (" +%dc reasoning" % smoke["reasoning_chars"]
                 if smoke.get("reasoning_chars") else "")
        print("smoke %.1fs%s" % (smoke["total_s"], think), end=" ", flush=True)

        if args.skip_load:
            print()
            rows.append(row)
            continue

        load = probe(client, model, load_system, load_user, args.max_tokens, args.timeout)
        row["load"] = load
        if load["ok"]:
            row["shape"] = check_json(load.get("text") or "", args.records)
            print("| load %.0fs ttft %s %s shape=%s"
                  % (load["total_s"], load["ttft_s"], load["finish_reason"] or "",
                     row["shape"]))
        else:
            print("| load FAILED (%s)" % (load["error"] or "")[:60])
        for probe_result in (row["smoke"], row["load"]):
            if probe_result:
                probe_result.pop("text", None)   # keep the report small
        rows.append(row)

    write_report(args, rows)
    print("\nreport -> %s" % args.out)
    return 0


def write_report(args, rows) -> None:
    def cell(d, key, dash="-"):
        if not d or d.get(key) is None:
            return dash
        return str(d[key])

    lines = [
        "# Model probe report",
        "",
        "Endpoint: `%s`  " % args.base_url,
        "Generated: %s  " % time.strftime("%Y-%m-%d %H:%M:%S"),
        "Load probe: ~%d input tokens, %d records requested, `max_tokens=%d`, "
        "`temperature=0`, streamed, %ds timeout" % (args.input_tokens, args.records,
                                                    args.max_tokens, args.timeout),
        "",
        "Every prompt is generated by the script itself, so this is reproducible with no data "
        "from our side. `scripts/kisski_model_probe.py` in the repository.",
        "",
        "## What the two probes ask",
        "",
        "- **smoke** - trivial prompt, 64 tokens out. Does the model respond at all?",
        "- **load** - an input of about the size we really send, asking for a long strictly "
        "shaped JSON array. Can it sustain long structured output?",
        "",
        "TTFT is time to first streamed token, reported apart from total time: a model that "
        "thinks for minutes and then streams quickly is a different problem from one that "
        "streams slowly throughout.",
        "",
        "## Results",
        "",
        "| model | smoke | smoke TTFT | smoke reasoning | load | load TTFT | load total | "
        "chars out | reasoning out | tok/s | finish_reason | note |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        s, l = r["smoke"], r["load"]
        smoke_state = "ok" if s and s["ok"] else "**FAIL**"
        if l is None:
            load_state, note = "-", (s.get("error") or "")[:400] if s and s.get("error") else ""
        elif not l["ok"]:
            load_state, note = "**FAIL**", (l.get("error") or "")[:400]
        elif l["empty"]:
            load_state, note = "**EMPTY**", "returned no content"
        elif r.get("shape") not in (None, "ok"):
            load_state, note = "**SHAPE**", r.get("shape") or ""
        else:
            load_state, note = "ok", "correct shape"
        lines.append("| `%s` | %s | %ss | %s | %s | %ss | %ss | %s | %s | %s | %s | %s |" % (
            r["model"], smoke_state, cell(s, "ttft_s"), cell(s, "reasoning_chars", "0"),
            load_state, cell(l, "ttft_s"), cell(l, "total_s"), cell(l, "chars"),
            cell(l, "reasoning_chars", "0"), cell(l, "tok_per_s"),
            cell(l, "finish_reason"), note.replace("|", "/")))

    oks = [r["load"] for r in rows if r["load"] and r["load"]["ok"] and not r["load"]["empty"]]
    fails = [r for r in rows if not (r["smoke"] and r["smoke"]["ok"])]
    empties = [r for r in rows if r["load"] and r["load"]["ok"] and r["load"]["empty"]]
    load_fails = [r for r in rows if r["load"] and not r["load"]["ok"]]

    lines += [
        "",
        "## Summary",
        "",
        "- models probed: **%d**" % len(rows),
        "- smoke failed: **%d**%s" % (len(fails),
                                      (" (" + ", ".join("`%s`" % r["model"] for r in fails) + ")")
                                      if fails else ""),
        "- load returned empty content: **%d**%s" % (
            len(empties), (" (" + ", ".join("`%s`" % r["model"] for r in empties) + ")")
            if empties else ""),
        "- load errored or timed out: **%d**%s" % (
            len(load_fails), (" (" + ", ".join("`%s`" % r["model"] for r in load_fails) + ")")
            if load_fails else ""),
        "- load completed with content: **%d**" % len(oks),
    ]
    if oks:
        lines += [
            "- median load TTFT: **%.1fs**" % statistics.median(
                [o["ttft_s"] for o in oks if o["ttft_s"] is not None] or [0]),
            "- median load total: **%.0fs**" % statistics.median([o["total_s"] for o in oks]),
        ]
    lines += [
        "",
        "## Questions for the provider",
        "",
        "1. For models whose **load** probe returns empty content while exiting cleanly: is the "
        "request being truncated, dropped or rejected somewhere in the serving stack? A clean "
        "200 with no content is indistinguishable from a successful empty answer on our side.",
        "2. For models with a very high **TTFT** on the load probe but a normal smoke TTFT: is "
        "there a queue or prefill cost that scales with input length, and is there a documented "
        "limit we are crossing?",
        "3. Are there per-model caps on `max_tokens`, output length, or request duration that "
        "differ from the advertised context window?",
        "4. Which of the listed models are expected to sustain ~16k tokens of structured JSON "
        "output in a single response?",
        "5. Which models emit reasoning tokens before content, and do those count against "
        "`max_tokens`? A model that reasons past the budget returns `finish_reason: length` "
        "with empty content, which is indistinguishable from a model that simply said nothing.",
        "",
    ]
    with io.open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
