"""PMOA-TTS's own evaluation, reimplemented in Python from the authors' reference code.

The reference implementation is R (`TTS_evaluation/comparer.R`,
`TTS_evaluation/compare_with_manual.R`) with a Python helper for the embeddings
(`TTS_evaluation/distance_helper.py`), in jcweiss2/pmoa_tts. This module follows it
rather than inventing a metric, and each function names the reference it follows. Where
the reference leaves something to the caller, the choice is a documented parameter with
their published setting as the default -- never a silent decision.

What the reference does, and what is reproduced here:

  embeddings     `pritamdeka/S-PubMedBert-MS-MARCO`, mean-pooled over tokens, L2
                 normalized. (distance_helper.py)
  distance       `pairwise_distances(..., metric='cosine')` -- cosine DISTANCE, not
                 similarity. This is worth stating plainly because the papers say
                 "cosine similarity threshold of 0.1", which read as a similarity would
                 match almost every pair of clinical findings. The code settles it: it
                 is a distance, and a match is `error.rate < threshold`.
                 (compare_with_manual.R: `filter(error.rate < flags$distance.threshold)`)
  threshold      0.1 for embedding distance. The reference's non-embedding default is
                 Levenshtein with threshold 0.6, which is offered here as `lev` so the
                 scorer runs without torch -- their fallback, not ours.
  matching       `recursive_match()`: greedy one-to-one. Each round takes every unmatched
                 gold row's minimum distance, resolves column collisions in favour of the
                 smaller distance, removes the matched row and column, repeats.
  event recall   matched gold events / gold events.
  concordance    `1 - Cindex(pred = time.pilot, y = Surv(time, all uncensored))` over
                 matched pairs.
  AULTC          area under the empirical CDF of log(1 + |t_pred - t_gold|), normalized
                 by the value range; unmatched gold events are charged `max(ae) + 1`.

One thing the reference never had to handle, and this harness does: biograph's dates are
ISO calendar dates with a precision floor of one day (schema/date.schema.json), while
PMOA-TTS timestamps are hours. Two events the pipeline places on the same day are tied
in the prediction even when the gold orders them hours apart. Ties are scored at 0.5,
Harrell's convention, and `ties_from_day_precision` reports how many comparable pairs
were affected -- because a concordance that looks mediocre because the schema cannot
resolve hours is a different finding from one that looks mediocre because the ordering
is wrong, and the table has to be able to tell them apart.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

Timeline = Sequence[tuple[str, float]]     # (event text, hours from presentation)

EMBED_MODEL = "pritamdeka/S-PubMedBert-MS-MARCO"
EMBED_THRESHOLD = 0.1       # cosine distance; compare_with_manual.R
LEV_THRESHOLD = 0.6         # normalized Levenshtein; comparer.R's get_match_table default


# --------------------------------------------------------------------- distances

def _normalized_levenshtein(a: str, b: str) -> float:
    """Distance in [0, 1]. comparer.R uses stringdist's method='lv' over raw strings and
    calls the result an error rate, which only sits on the same scale as a cosine
    distance once it is divided by the longer string."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a and not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(len(a), len(b))


def levenshtein_matrix(gold: Sequence[str], pred: Sequence[str]) -> list[list[float]]:
    return [[_normalized_levenshtein(g, p) for p in pred] for g in gold]


def embedding_matrix(gold: Sequence[str], pred: Sequence[str],
                     model_name: str = EMBED_MODEL, batch_size: int = 32
                     ) -> list[list[float]]:
    """Cosine distance matrix, following distance_helper.py: AutoModel, mean pooling over
    the attention mask, L2 normalize, then 1 - cos."""
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as e:      # pragma: no cover - environment dependent
        raise SystemExit(
            "the embedding matcher needs torch + transformers (the benchmark's own "
            f"choice of {model_name}). Install them, or pass --matcher lev to use the "
            "reference implementation's Levenshtein fallback at threshold 0.6."
        ) from e

    tok = AutoTokenizer.from_pretrained(model_name)
    mod = AutoModel.from_pretrained(model_name)
    mod.eval()

    def embed(texts: Sequence[str]):
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = list(texts[i:i + batch_size])
            enc = tok(chunk, padding=True, truncation=True, max_length=512,
                      return_tensors="pt")
            with torch.no_grad():
                hidden = mod(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            out.append(torch.nn.functional.normalize(pooled, p=2, dim=1))
        return torch.cat(out) if out else torch.zeros((0, mod.config.hidden_size))

    g, p = embed(gold), embed(pred)
    if not len(g) or not len(p):
        return [[1.0] * len(pred) for _ in gold]
    sim = (g @ p.T).clamp(-1.0, 1.0)
    return (1.0 - sim).tolist()


MATCHERS: dict[str, tuple[Callable[..., list[list[float]]], float]] = {
    "embedding": (embedding_matrix, EMBED_THRESHOLD),
    "lev": (levenshtein_matrix, LEV_THRESHOLD),
}


# --------------------------------------------------------------------- matching

def recursive_match(dists: list[list[float]], threshold: float) -> list[tuple[int, int, float]]:
    """comparer.R's recursive_match(), one-to-one and greedy.

    Each round: every remaining gold row proposes its nearest remaining prediction; where
    two rows propose the same prediction, the smaller distance wins; the winning row and
    column are removed. The threshold is applied afterwards, exactly as the reference
    does (`mutate(keep = error.rate < threshold)`), so a gold event whose only available
    partner is too far away is left unmatched rather than stealing a better pairing."""
    rows = list(range(len(dists)))
    cols = list(range(len(dists[0]))) if dists and dists[0] else []
    pairs: list[tuple[int, int, float]] = []

    while rows and cols:
        proposals: dict[int, tuple[int, float]] = {}
        for r in rows:
            best_c, best_d = min(((c, dists[r][c]) for c in cols), key=lambda t: t[1])
            held = proposals.get(best_c)
            if held is None or best_d < held[1]:
                proposals[best_c] = (r, best_d)
        if not proposals:
            break
        for c, (r, d) in proposals.items():
            pairs.append((r, c, d))
            rows.remove(r)
            cols.remove(c)
    return [(r, c, d) for r, c, d in pairs if d < threshold]


# --------------------------------------------------------------------- metrics

def concordance(gold_times: Sequence[float], pred_times: Sequence[float]
                ) -> tuple[float | None, int, int]:
    """Harrell's c over matched pairs: the probability a randomly chosen pair of events
    is ordered the same way in the prediction as in the gold timeline.

    Returns (c, comparable_pairs, tied_predictions). Comparable pairs are those the gold
    orders strictly; a tied prediction scores 0.5. The reference gets this from
    `1 - Cindex(pred, Surv(time, uncensored))`; computing it directly keeps the tie
    accounting visible, which is the part this harness needs to report."""
    n = len(gold_times)
    concordant = comparable = ties = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            if gold_times[i] == gold_times[j]:
                continue
            comparable += 1
            gold_order = gold_times[i] < gold_times[j]
            if pred_times[i] == pred_times[j]:
                ties += 1
                concordant += 0.5
            elif (pred_times[i] < pred_times[j]) == gold_order:
                concordant += 1
    if not comparable:
        return None, 0, 0
    return concordant / comparable, int(comparable), int(ties)


def _ecdf_auc(values: Sequence[float], upper: float) -> float | None:
    """compare_with_manual.R's ecdf_auc2: area under the empirical CDF, normalized by the
    observed range, capped at `upper`. Higher is better -- errors concentrated near zero
    push the CDF up early."""
    vals = sorted(v for v in values if v is not None and not math.isnan(v))
    if not vals:
        return None
    lo, hi = vals[0], min(max(vals), upper)
    if hi <= lo:
        return 1.0
    area = 0.0
    for k, v in enumerate(vals):
        nxt = min(vals[k + 1], hi) if k + 1 < len(vals) else hi
        if nxt > v:
            area += ((k + 1) / len(vals)) * (min(nxt, hi) - min(v, hi))
    return area / (hi - lo)


def aultc(abs_errors: Sequence[float | None], upper: float = 10.0) -> float | None:
    """Area Under the Log-Time CDF. Unmatched gold events are charged max(ae) + 1, as the
    reference does (`ifelse(is.na(ae), max(ae, na.rm=T) + 1, ae + 1)`), so a timeline
    that scores well by matching only its easy events does not look good here."""
    present = [e for e in abs_errors if e is not None]
    if not present:
        return None
    penalty = max(present) + 1.0
    return _ecdf_auc([math.log1p(e if e is not None else penalty) for e in abs_errors], upper)


# --------------------------------------------------------------------- top level

@dataclass
class DocScore:
    doc_id: str
    n_gold: int
    n_pred: int
    n_matched: int
    event_recall: float | None
    concordance: float | None
    comparable_pairs: int
    tied_predictions: int
    aultc: float | None
    median_abs_error_hours: float | None
    matches: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def tie_rate(self) -> float | None:
        return self.tied_predictions / self.comparable_pairs if self.comparable_pairs else None


def score_document(doc_id: str, gold: Timeline, pred: Timeline, matcher: str = "embedding",
                   threshold: float | None = None, aultc_upper: float = 10.0) -> DocScore:
    if matcher not in MATCHERS:
        raise ValueError(f"unknown matcher {matcher!r}; choose from {sorted(MATCHERS)}")
    fn, default_threshold = MATCHERS[matcher]
    threshold = default_threshold if threshold is None else threshold

    gold_texts = [g[0] for g in gold]
    pred_texts = [p[0] for p in pred]
    if not gold_texts:
        return DocScore(doc_id, 0, len(pred), 0, None, None, 0, 0, None, None)
    if not pred_texts:
        return DocScore(doc_id, len(gold), 0, 0, 0.0, None, 0, 0,
                        aultc([None] * len(gold), aultc_upper), None)

    dists = fn(gold_texts, pred_texts)
    pairs = recursive_match(dists, threshold)

    gt = [gold[r][1] for r, _, _ in pairs]
    pt = [pred[c][1] for _, c, _ in pairs]
    c, comparable, ties = concordance(gt, pt)

    matched_rows = {r for r, _, _ in pairs}
    errors: list[float | None] = []
    for i in range(len(gold)):
        hit = next((p for p in pairs if p[0] == i), None)
        errors.append(abs(pred[hit[1]][1] - gold[i][1]) if hit else None)
    present = sorted(e for e in errors if e is not None)
    median = (present[len(present) // 2] if len(present) % 2
              else (present[len(present) // 2 - 1] + present[len(present) // 2]) / 2) \
        if present else None

    return DocScore(
        doc_id=doc_id, n_gold=len(gold), n_pred=len(pred), n_matched=len(matched_rows),
        event_recall=len(matched_rows) / len(gold), concordance=c,
        comparable_pairs=comparable, tied_predictions=ties,
        aultc=aultc(errors, aultc_upper), median_abs_error_hours=median,
        matches=[(gold_texts[r], pred_texts[c_], d) for r, c_, d in pairs],
    )


# --------------------------------------------------------------------- gold parsing

_ROW = re.compile(r"^\s*(?P<event>.+?)\s*\|\s*(?P<time>-?\d+(?:\.\d+)?)\s*$")


def parse_timeline(text: str) -> list[tuple[str, float]]:
    """PMOA-TTS's released format: one `event | hours` row per line, presentation at 0,
    negatives before it. Rows that do not parse are skipped and counted by the caller --
    a header line or a stray blank should not become an event."""
    out = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if m:
            out.append((m.group("event").strip(), float(m.group("time"))))
    return out
