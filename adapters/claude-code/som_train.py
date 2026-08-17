#!/usr/bin/env python3
"""
som_train.py, the out-of-band Kohonen SOM trainer for the learned fingerprint
(som_train.spec.md).

The rig-space fingerprint is a trajectory in a low-dimensional latent space.
The hand-written `_embed` in the driver places sessions by prior; this tool
LEARNS the low-D organization from the data instead. It reads the per-session
shape vectors from session_features (schema vibrant/session-features@3),
trains a batch Kohonen self-organizing map with a deterministic PCA-oriented
init, and writes a som-cache.json the stdlib driver consumes deterministically.
It never runs inside the driver: this is the out-of-band inference step in the
inference -> cache -> driver-consumes seam.

Pure Python stdlib, deliberately no numpy: byte-identical determinism across
runs matters more than convenience, and a SOM is small vector arithmetic that
does not need it. Every lattice/sample iteration uses a fixed order so float
reductions reproduce byte-for-byte.

Usage:
  python3 som_train.py --features matrix.json [--rows R --cols C] [--seed S] [--out som-cache.json]
  python3 som_train.py --selftest        # runs the acceptance fixture, exits 0/1
Stdlib only.
"""
import argparse
import json
import math
import sys

SCHEMA = "vibrant/som@1"

MIN_SESSIONS = 5
MIN_SIDE = 4
MAX_SIDE = 12
EPOCHS = 20
POWER_ITERS = 100
SIGMA_FINAL = 0.7
ROUND = 6

# Below this, an eigenvalue is treated as "~0" (degenerate direction) and the
# init spread along that axis falls back to a small fixed epsilon instead of
# sqrt(eigenvalue), so nodes are not all identical.
_EIG_EPS = 1e-9
_INIT_SPREAD_EPS = 0.05


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _matvec(mat, v):
    return [sum(row[j] * v[j] for j in range(len(v))) for row in mat]


def _covariance(X, mean, D, N):
    """Population covariance (/N), row-major fixed sum order over samples."""
    centered = [[x[d] - mean[d] for d in range(D)] for x in X]
    cov = [[0.0] * D for _ in range(D)]
    for i in range(D):
        for j in range(i, D):
            s = 0.0
            for c in centered:
                s += c[i] * c[j]
            val = s / N
            cov[i][j] = val
            cov[j][i] = val
    return cov


def _power_iteration(mat, n_iters):
    """Deterministic power iteration: fixed start vector [1,0,...,0], fixed
    iteration count. Returns (unit vector, eigenvalue via Rayleigh quotient),
    with the vector's sign fixed so its largest-magnitude entry is positive."""
    D = len(mat)
    v = [0.0] * D
    v[0] = 1.0
    for _ in range(n_iters):
        w = _matvec(mat, v)
        norm = math.sqrt(sum(x * x for x in w))
        if norm < 1e-15:
            break
        v = [x / norm for x in w]
    Mv = _matvec(mat, v)
    eig = sum(v[i] * Mv[i] for i in range(D))
    max_idx = max(range(D), key=lambda i: abs(v[i]))
    if v[max_idx] < 0.0:
        v = [-x for x in v]
    return v, eig


def _deflate(mat, pc, eig, D):
    return [[mat[i][j] - eig * pc[i] * pc[j] for j in range(D)] for i in range(D)]


def _lattice_dims(n, aspect=1.5):
    """Default lattice, portrait (rows > cols, aspect ~1.5), so the rendered map reads
    as a taller oval, like a fingerprint (the 3dl marks are tall SOMs). Vesanto node
    count 5*sqrt(n), split across the aspect; each side clamped to [MIN_SIDE, MAX_SIDE]."""
    units = 5.0 * math.sqrt(n)
    rows = max(MIN_SIDE, min(MAX_SIDE, round(math.sqrt(units * aspect))))
    cols = max(MIN_SIDE, min(MAX_SIDE, round(math.sqrt(units / aspect))))
    return rows, cols


def _init_codebook(R, C, D, mean, pc1, scale1, pc2, scale2):
    a_vals = [-1.0 + 2.0 * r / (R - 1) for r in range(R)] if R > 1 else [0.0]
    b_vals = [-1.0 + 2.0 * c / (C - 1) for c in range(C)] if C > 1 else [0.0]
    codebook = []
    for r in range(R):
        row = []
        for c in range(C):
            a, b = a_vals[r], b_vals[c]
            node = [
                _clamp01(mean[d] + a * scale1 * pc1[d] + b * scale2 * pc2[d])
                for d in range(D)
            ]
            row.append(node)
        codebook.append(row)
    return codebook


def bmu(codebook, vec):
    """Best matching unit: argmin squared Euclidean distance over the R x C
    lattice, ties broken by lowest (r, c) in row-major order. Pure."""
    best = None
    best_d = None
    for r, row in enumerate(codebook):
        for c, node in enumerate(row):
            d = 0.0
            for i in range(len(vec)):
                diff = vec[i] - node[i]
                d += diff * diff
            if best_d is None or d < best_d:
                best_d = d
                best = (r, c)
    return best


def _update_codebook(codebook, X, bmus, R, C, sigma):
    D = len(codebook[0][0])
    two_sigma2 = 2.0 * sigma * sigma
    sum_w = [[0.0] * C for _ in range(R)]
    sum_wx = [[[0.0] * D for _ in range(C)] for _ in range(R)]
    for x, (br, bc) in zip(X, bmus):
        for r in range(R):
            dr2 = (r - br) * (r - br)
            for c in range(C):
                d2 = dr2 + (c - bc) * (c - bc)
                h = math.exp(-d2 / two_sigma2)
                sum_w[r][c] += h
                acc = sum_wx[r][c]
                for d in range(D):
                    acc[d] += h * x[d]
    new_codebook = []
    for r in range(R):
        row = []
        for c in range(C):
            total = sum_w[r][c]
            if total > 0.0:
                row.append([sum_wx[r][c][d] / total for d in range(D)])
            else:
                row.append(list(codebook[r][c]))
        new_codebook.append(row)
    return new_codebook


def train(matrix, rows=None, cols=None, seed=0):
    """Pure trainer: deterministic given (matrix, rows, cols, seed). Returns
    the som-cache.json object."""
    names = matrix["names"]
    in_rows = matrix["rows"]
    N = len(in_rows)
    if N < MIN_SESSIONS:
        raise ValueError(f"need at least {MIN_SESSIONS} sessions, got {N}")
    D = len(names)
    X = [r["vec"] for r in in_rows]

    if rows is not None and cols is not None:
        R, C = rows, cols
    else:
        R, C = _lattice_dims(N)

    mean = [sum(x[d] for x in X) / N for d in range(D)]
    cov = _covariance(X, mean, D, N)
    pc1, eig1 = _power_iteration(cov, POWER_ITERS)
    cov2 = _deflate(cov, pc1, eig1, D)
    pc2, eig2 = _power_iteration(cov2, POWER_ITERS)

    scale1 = math.sqrt(eig1) if eig1 > _EIG_EPS else _INIT_SPREAD_EPS
    scale2 = math.sqrt(eig2) if eig2 > _EIG_EPS else _INIT_SPREAD_EPS

    codebook = _init_codebook(R, C, D, mean, pc1, scale1, pc2, scale2)

    sigma0 = max(R, C) / 2.0
    for t in range(EPOCHS):
        if EPOCHS > 1:
            sigma = sigma0 * (SIGMA_FINAL / sigma0) ** (t / (EPOCHS - 1))
        else:
            sigma = SIGMA_FINAL
        bmus = [bmu(codebook, x) for x in X]
        codebook = _update_codebook(codebook, X, bmus, R, C, sigma)

    sessions_out = []
    qes = []
    for row, x in zip(in_rows, X):
        r, c = bmu(codebook, x)
        w = codebook[r][c]
        qe = math.sqrt(sum((x[d] - w[d]) ** 2 for d in range(D)))
        sessions_out.append({
            "sid": row["sid"],
            "day": row.get("day"),
            "bmu": [r, c],
            "qe": round(qe, ROUND),
        })
        qes.append(qe)

    mean_qe = sum(qes) / len(qes) if qes else 0.0

    return {
        "schema": SCHEMA,
        "feature_schema": matrix.get("schema"),
        "names": names,
        "lattice": {"rows": R, "cols": C},
        "params": {
            "epochs": EPOCHS,
            "sigma0": round(sigma0, ROUND),
            "sigma_final": SIGMA_FINAL,
            "seed": seed,
            "power_iters": POWER_ITERS,
            "min_sessions": MIN_SESSIONS,
        },
        "codebook": [
            [[round(v, ROUND) for v in node] for node in row] for row in codebook
        ],
        "sessions": sessions_out,
        "quantization_error": round(mean_qe, ROUND),
    }


def selftest():
    import test_som_train as t
    return t.main()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", help="session_features matrix JSON")
    ap.add_argument("--rows", type=int, default=None, help="pin lattice rows")
    ap.add_argument("--cols", type=int, default=None, help="pin lattice cols")
    ap.add_argument("--seed", type=int, default=0, help="recorded, not consumed by batch training")
    ap.add_argument("--out", default=None, help="write som-cache JSON here (else stdout)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.features:
        ap.error("--features is required (or use --selftest)")
    with open(args.features) as f:
        matrix = json.load(f)
    out = train(matrix, rows=args.rows, cols=args.cols, seed=args.seed)
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"som written: {args.out} ({out['lattice']['rows']}x{out['lattice']['cols']} lattice, "
              f"{len(out['sessions'])} sessions)")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
