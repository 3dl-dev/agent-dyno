#!/usr/bin/env python3
# REFERENCE BUILD. Source of truth: som_merge.spec.md (what it must do)
# + test_som_merge.py (the verification). Code is a regenerable artifact:
# rebuild it from the spec and the acceptance test must still pass. See SOURCE.md.
"""
som_merge.py, the federated SOM merge.

Operators do NOT pool raw sessions. Each trains locally against a shared reference
codebook and publishes only three number-grids over that codebook's lattice: a
per-cell cost `cost` (numerator, dollars), a per-cell `surv` (denominator,
surviving KB), and a per-cell `support` (session count), plus an opaque operator
tag and the codebook version. The per-cell cost field is a RATIO, d_per_survkb;
it is never stored pre-divided, because a mean of ratios weighted by session
count is not the pooled ratio (it is biased). This module sums numerators and
denominators separately across operators (ratio of sums, not mean of ratios),
which is the only way merging a partition of one corpus reproduces the whole,
and reads a confidence-weighted gradient off the merged field. Models and
aggregates cross the boundary, never sessions, sids, repos, feature vectors,
days, or transcripts.

Five operations, no network and no policy:

  validate_contribution   tier-0 privacy floor + shape/consistency checks.
  merge                   fold contributions into one ratio-of-sums field.
  merged_gradient         confidence-weighted descent direction off a merged field.
  reference_codebook      package a trained som-cache as the publishable frame.
  contribution            producer helper: packages only the allowed keys.

Stdlib only, harness-neutral, deterministic: output is a pure function of the
inputs.

Usage (as a library):
  import som_merge as sm
  merged = sm.merge([contrib_a, contrib_b, ...])
  step = sm.merged_gradient(merged, current_cell=[r, c])

Run this file directly for a self-test:
  som_merge.py --selftest
"""
import hashlib
import json
import math
import sys

SCHEMA_CONTRIB = "vibrant/som-contribution@1"
SCHEMA_MERGED = "vibrant/som-merged@1"
SCHEMA_CODEBOOK = "vibrant/som-codebook@1"

# Raw-log leakage: any of these as a top-level key gets a contribution rejected,
# no matter what else is in it. The contribution schema never carries these.
FORBIDDEN = {"sessions", "session", "sid", "sids", "repo", "repos", "vec", "vecs",
             "vectors", "day", "days", "date", "dates", "transcript", "transcripts",
             "path", "paths", "identity", "name", "email"}

_REQUIRED = ("schema", "op", "codebook_version", "lattice", "cost", "surv", "support")


def _num_finite_nonneg(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= 0)


def _nonneg_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _grid_shape_ok(grid, rows, cols):
    return (isinstance(grid, list) and len(grid) == rows
            and all(isinstance(row, list) and len(row) == cols for row in grid))


def validate_contribution(c):
    """Tier-0 issues, sorted, empty if clean. The privacy floor: reject missing
    required keys or the wrong schema, any forbidden top-level key (raw-log
    leakage), any cost/surv/support shape mismatch, any support entry that is not
    a non-negative int, any cost/surv entry that is not a non-negative finite
    number or null, and any cell where support>0 iff cost-and-surv are present
    breaks. surv may be 0.0 with support>0 (sessions with no surviving work); only
    null is disallowed there."""
    issues = []
    if not isinstance(c, dict):
        return ["contribution is not an object"]

    for k in _REQUIRED:
        if k not in c:
            issues.append(f"missing required key '{k}'")

    if "schema" in c and c["schema"] != SCHEMA_CONTRIB:
        issues.append(f"schema must be '{SCHEMA_CONTRIB}' (got {c['schema']!r})")

    for k in sorted(FORBIDDEN & set(c.keys())):
        issues.append(f"forbidden key '{k}' present (raw-log leakage)")

    lattice = c.get("lattice")
    rows = cols = None
    if "lattice" in c:
        if (isinstance(lattice, dict) and _nonneg_int(lattice.get("rows"))
                and _nonneg_int(lattice.get("cols"))):
            rows, cols = lattice["rows"], lattice["cols"]
        else:
            issues.append("lattice must be an object with non-negative integer 'rows' and 'cols'")

    cost = c.get("cost")
    surv = c.get("surv")
    support = c.get("support")
    cost_ok = surv_ok = support_ok = False
    if rows is not None:
        if "cost" in c:
            cost_ok = _grid_shape_ok(cost, rows, cols)
            if not cost_ok:
                issues.append(f"cost shape is not {rows}x{cols}")
        if "surv" in c:
            surv_ok = _grid_shape_ok(surv, rows, cols)
            if not surv_ok:
                issues.append(f"surv shape is not {rows}x{cols}")
        if "support" in c:
            support_ok = _grid_shape_ok(support, rows, cols)
            if not support_ok:
                issues.append(f"support shape is not {rows}x{cols}")

    if cost_ok and surv_ok and support_ok:
        for r in range(rows):
            for cc in range(cols):
                s = support[r][cc]
                cst = cost[r][cc]
                srv = surv[r][cc]
                if not _nonneg_int(s):
                    issues.append(f"support[{r}][{cc}] must be a non-negative int (got {s!r})")
                    continue
                for label, val in (("cost", cst), ("surv", srv)):
                    if not (val is None or _num_finite_nonneg(val)):
                        issues.append(
                            f"{label}[{r}][{cc}] must be a non-negative finite number or null "
                            f"(got {val!r})")
                if s == 0 and (cst is not None or srv is not None):
                    issues.append(f"cell ({r},{cc}): support is 0 but cost/surv is not null")
                elif s > 0 and (cst is None or srv is None):
                    issues.append(f"cell ({r},{cc}): support is >0 but cost/surv is null")

    return sorted(issues)


def merge(contributions):
    """Validate every contribution and refuse (ValueError, issues joined into the
    message) if any fails, or if lattices/codebook_versions differ across the set.
    Otherwise fold them, per cell, over the operators with support>0 there:
    cost_sum and surv_sum are pooled separately (ratio of sums, not mean of
    ratios), field = cost_sum/surv_sum, weight = surv_sum (the surviving work
    behind the cell), support = summed session count, contributors = operator
    count, spread = peer disagreement (max-min of cost_op/surv_op across
    operators with surv_op>0). Contributions are sorted by `op` before reduction
    so merge([A, B]) == merge([B, A])."""
    if not contributions:
        raise ValueError("merge requires at least one contribution")

    all_issues = []
    for c in contributions:
        for i in validate_contribution(c):
            op = c.get("op") if isinstance(c, dict) else "<invalid>"
            all_issues.append(f"{op}: {i}")

    lattices = {json.dumps(c.get("lattice"), sort_keys=True) for c in contributions}
    versions = {c.get("codebook_version") for c in contributions}
    if len(lattices) > 1:
        all_issues.append("contributions do not share the same lattice")
    if len(versions) > 1:
        all_issues.append("contributions do not share the same codebook_version")

    if all_issues:
        raise ValueError("; ".join(sorted(all_issues)))

    ordered = sorted(contributions, key=lambda c: c["op"])
    lattice = ordered[0]["lattice"]
    rows, cols = lattice["rows"], lattice["cols"]
    version = ordered[0]["codebook_version"]

    field = [[None] * cols for _ in range(rows)]
    weight = [[0.0] * cols for _ in range(rows)]
    support = [[0] * cols for _ in range(rows)]
    contributors = [[0] * cols for _ in range(rows)]
    spread = [[None] * cols for _ in range(rows)]

    for r in range(rows):
        for cc in range(cols):
            cost_sum = 0.0
            surv_sum = 0.0
            support_sum = 0
            contrib_count = 0
            field_ops = []
            for c in ordered:
                s = c["support"][r][cc]
                if s > 0:
                    cost_sum += c["cost"][r][cc]
                    surv_sum += c["surv"][r][cc]
                    support_sum += s
                    contrib_count += 1
                    srv = c["surv"][r][cc]
                    if srv > 0:
                        field_ops.append(c["cost"][r][cc] / srv)

            support[r][cc] = support_sum
            contributors[r][cc] = contrib_count
            if support_sum > 0:
                weight[r][cc] = round(surv_sum, 4)
                if surv_sum > 0:
                    field[r][cc] = round(cost_sum / surv_sum, 4)
            if len(field_ops) >= 2:
                spread[r][cc] = round(max(field_ops) - min(field_ops), 4)

    return {
        "schema": SCHEMA_MERGED,
        "codebook_version": version,
        "lattice": {"rows": rows, "cols": cols},
        "field_metric": "d_per_survkb",
        "field_lower_is_better": True,
        "operators": sorted(c["op"] for c in ordered),
        "field": field,
        "weight": weight,
        "support": support,
        "contributors": contributors,
        "spread": spread,
    }


def merged_gradient(merged, current_cell, radius=2, min_confidence=3):
    """From current_cell, consider cells within Euclidean lattice distance radius
    (inclusive) whose session-count `support` >= min_confidence and whose field is
    not null. Pick the min-field cell (ties: lowest (r, c) row-major). Return the
    descent when it beats the current cell's field, or when the current cell has
    no field. None when nothing qualifies or nothing beats where you already are."""
    rows, cols = merged["lattice"]["rows"], merged["lattice"]["cols"]
    field = merged["field"]
    support = merged["support"]
    weight = merged["weight"]
    contributors = merged["contributors"]
    cr, cc0 = current_cell
    current_field = field[cr][cc0] if 0 <= cr < rows and 0 <= cc0 < cols else None

    best = None
    for r in range(rows):
        for c in range(cols):
            if math.hypot(r - cr, c - cc0) > radius + 1e-9:
                continue
            if support[r][c] < min_confidence:
                continue
            if field[r][c] is None:
                continue
            candidate = (field[r][c], r, c)
            if best is None or candidate < best:
                best = candidate

    if best is None:
        return None
    bf, br, bc = best
    if current_field is not None and not (bf < current_field):
        return None

    delta = round(current_field - bf, 4) if current_field is not None else None
    return {
        "target_cell": [br, bc],
        "vector": [br - cr, bc - cc0],
        "support": support[br][bc],
        "weight": weight[br][bc],
        "contributors": contributors[br][bc],
        "delta": delta,
    }


def reference_codebook(som_cache, version):
    """Package a trained som-cache (lattice, names, codebook) as the publishable
    reference frame v1. Deterministic: hash is derived from the codebook so a
    changed frame is detectable, version is caller-supplied."""
    codebook = som_cache["codebook"]
    digest = hashlib.sha256(json.dumps(codebook, sort_keys=True).encode()).hexdigest()
    return {
        "schema": SCHEMA_CODEBOOK,
        "version": version,
        "lattice": som_cache["lattice"],
        "names": som_cache["names"],
        "codebook": codebook,
        "hash": digest[:16],
    }


def contribution(cost, surv, support, codebook_version, lattice, op):
    """The producer helper: packages ONLY the allowed keys, so a producer cannot
    leak by accident."""
    return {
        "schema": SCHEMA_CONTRIB,
        "op": op,
        "codebook_version": codebook_version,
        "lattice": lattice,
        "cost": cost,
        "surv": surv,
        "support": support,
    }


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if "--selftest" in argv:
        import test_som_merge as t
        return t.main()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
