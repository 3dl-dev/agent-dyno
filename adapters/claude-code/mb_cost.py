#!/usr/bin/env python3
"""
Full-cost accounting for the model-behavior telemetry toolkit.

Prices live in prices.json alongside this file: per-model $/MTok rates
(input, output, cache_write, cache_read) with an effective date range, so a
session's day picks the date-appropriate row (e.g. Sonnet 5's 2026-08-31
intro-price cutover).

Module use:
    from mb_cost import price_tokens, session_cost, load_prices

    price_tokens("claude-opus-5", {"input_tokens": 1000, "output_tokens": 500,
                                    "cache_creation_input_tokens": 2000,
                                    "cache_read_input_tokens": 50000},
                 date="2026-08-08")
    # -> dollars

    session_cost(record)  # record is a 'session' or 'code' record emitted by
                           # model-behavior.py / model-behavior-code.py

CLI use (sanity-check cost-per-edit against a published figure):
    python3 mb_cost.py /tmp/mc.jsonl
    python3 mb_cost.py /tmp/mc.jsonl --models claude-opus-5 claude-opus-4-8 claude-fable-5

Reads model-behavior-code.py's "code" records (orch/work + *_by_model usage
breakdowns) and prints dollars-per-edit per model, aggregated as
sum(dollars)/sum(edits) across all matching sessions (not a mean of ratios,
which would let a single low-edit session skew the result).
"""
import argparse
import json
import os
import re

_DEFAULT_PRICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")

_MODEL_SUFFIX_RX = re.compile(r"\[1m\]$")

# Accept both the raw message.usage field names and the compact field names
# used internally by model-behavior.py / model-behavior-code.py (in_tok,
# cache_w_tok, cache_r_tok, out_tok) or the nested-dict short names
# (in, cache_w, cache_r, out) used in session-level main_usage/sub_usage /
# orch_by_model/work_by_model dicts.
_USAGE_ALIASES = {
    "in": ("input_tokens", "in_tok", "in"),
    "out": ("output_tokens", "out_tok", "out"),
    "cache_w": ("cache_creation_input_tokens", "cache_w_tok", "cache_w"),
    "cache_r": ("cache_read_input_tokens", "cache_r_tok", "cache_r"),
}

# Record keys that hold a {model: usage_dict} breakdown — used by session_cost
# to walk every model bucket in a 'session' or 'code' record.
_BY_MODEL_KEYS = ("main_usage", "sub_usage", "orch_by_model", "work_by_model")


def load_prices(path=None):
    """Load the prices.json table. Returns {model: [ {from,to,in,out,cache_write,cache_read}, ... ]}."""
    path = path or _DEFAULT_PRICES_PATH
    with open(path) as f:
        return json.load(f)


def _strip_suffix(model):
    """Strip a trailing '[1m]' context-window suffix before matching a price row."""
    return _MODEL_SUFFIX_RX.sub("", model or "")


def _usage_field(usage, kind):
    for k in _USAGE_ALIASES[kind]:
        if k in usage:
            return usage.get(k) or 0
    return 0


def price_row(model, date=None, prices=None):
    """Return the price row for `model` effective on `date` (YYYY-MM-DD), or None.

    If `date` is None, returns the open-ended (to == null) row, i.e. the
    current rate, falling back to the last row in the list.
    """
    prices = prices if prices is not None else load_prices()
    model = _strip_suffix(model)
    rows = prices.get(model)
    if not rows:
        return None
    if date is None:
        for r in rows:
            if r.get("to") is None:
                return r
        return rows[-1]
    for r in rows:
        frm, to = r.get("from"), r.get("to")
        if frm and date < frm:
            continue
        if to and date > to:
            continue
        return r
    return None


def price_tokens(model, usage, date=None, prices=None):
    """Full dollar cost of one usage dict, priced at the date-appropriate row for `model`.

    `usage` may be a raw message.usage dict (input_tokens/output_tokens/
    cache_creation_input_tokens/cache_read_input_tokens) or one of this
    toolkit's compact accumulator dicts (in_tok/out_tok/cache_w_tok/cache_r_tok
    or in/out/cache_w/cache_r). Unknown/zero fields count as zero.
    """
    prices = prices if prices is not None else load_prices()
    row = price_row(model, date, prices)
    if row is None:
        return 0.0
    inp = _usage_field(usage, "in")
    out = _usage_field(usage, "out")
    cw = _usage_field(usage, "cache_w")
    cr = _usage_field(usage, "cache_r")
    return (
        inp / 1_000_000 * row["in"]
        + out / 1_000_000 * row["out"]
        + cw / 1_000_000 * row["cache_write"]
        + cr / 1_000_000 * row["cache_read"]
    )


def session_cost(record, prices=None):
    """Full dollar cost of a 'session' or 'code' record (or a 'turn' record).

    Sums every {model: usage} bucket found under main_usage/sub_usage
    (model-behavior.py session records) or orch_by_model/work_by_model
    (model-behavior-code.py code records), each priced at its own model's
    date-appropriate rate. Falls back to treating the record itself as a
    flat single-model usage dict (the 'turn' record shape: model + in_tok/
    out_tok/cache_w_tok/cache_r_tok) when none of those keys are present.
    """
    prices = prices if prices is not None else load_prices()
    date = record.get("day")
    total = 0.0
    found_by_model = False
    for key in _BY_MODEL_KEYS:
        bym = record.get(key)
        if not bym:
            continue
        found_by_model = True
        for model, usage in bym.items():
            total += price_tokens(model, usage, date, prices)
    if not found_by_model and record.get("model"):
        total += price_tokens(record["model"], record, date, prices)
    return total


def _iter_records(paths, kind=None):
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if kind is None or r.get("k") == kind:
                    yield r


def cost_per_edit_report(paths, models=None, prices=None):
    """Recompute cost-per-edit per model from model-behavior-code.py 'code' records.

    Returns a list of (model, sessions, edits, dollars, dollars_per_edit) rows,
    aggregated as sum(dollars)/sum(edits) across sessions dominated by that
    model — a weighted average, not a mean of per-session ratios.
    """
    models = models or ["claude-fable-5", "claude-opus-4-8", "claude-opus-5"]
    prices = prices if prices is not None else load_prices()
    agg = {m: {"dollars": 0.0, "edits": 0, "sessions": 0} for m in models}
    for r in _iter_records(paths, kind="code"):
        m = r.get("model")
        if m not in agg:
            continue
        edits = (r.get("orch") or {}).get("edits", 0) + (r.get("work") or {}).get("edits", 0)
        if not edits:
            continue
        dollars = session_cost(r, prices)
        a = agg[m]
        a["dollars"] += dollars
        a["edits"] += edits
        a["sessions"] += 1
    rows = []
    for m in models:
        a = agg[m]
        cpe = a["dollars"] / a["edits"] if a["edits"] else None
        rows.append((m, a["sessions"], a["edits"], a["dollars"], cpe))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("paths", nargs="+", help="model-behavior-code.py jsonl output file(s)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="model IDs to report on (default: fable-5, opus-4-8, opus-5)")
    ap.add_argument("--prices", default=None, help="override path to prices.json")
    a = ap.parse_args()
    prices = load_prices(a.prices)
    rows = cost_per_edit_report(a.paths, a.models, prices)
    print(f"{'model':<20} {'sessions':>9} {'edits':>8} {'dollars':>12} {'$/edit':>10}")
    for m, sessions, edits, dollars, cpe in rows:
        cpe_s = f"{cpe:.4f}" if cpe is not None else "n/a"
        print(f"{m:<20} {sessions:>9} {edits:>8} {dollars:>12.4f} {cpe_s:>10}")


if __name__ == "__main__":
    main()
