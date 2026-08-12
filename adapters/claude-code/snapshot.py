#!/usr/bin/env python3
"""
snapshot.py — universal, dependency-free retention for the fuel/fingerprint side.

Long-horizon analytics has two halves, and only one of them needs retaining:

  * Surviving work (the numerator) lives in GIT — retained forever by everyone,
    for free. core/survival_git.py reads it directly. No archiver, no infra.
  * The fuel/fingerprint side (tokens, effort, engine) lives in the harness's
    transcripts, which rotate (~30 days for Claude Code). This script freezes the
    *derived* per-session metrics before they rotate — kilobytes a month, stored
    locally, that anyone can keep forever with zero infrastructure.

So retention in this kit is: keep git (you already do) + keep these tiny local
snapshots. That is universal. Shipping raw transcripts to a NAS/tank/S3 is an
optional advanced backend for people who want to recompute new metrics over old
windows; it is NOT required and NOT part of this kit.

Usage:
    python3 snapshot.py                       # -> ./snapshots/<date>/
    python3 snapshot.py --out ~/.agent-dyno/snapshots
Runs the sibling extractors and writes their JSONL. Stdlib only.
"""
import argparse
import datetime as _dt
import os
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(extractor, out_path):
    with open(out_path, "w") as f:
        subprocess.run([sys.executable, os.path.join(HERE, extractor)],
                       stdout=f, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "snapshots"),
                    help="local snapshot root (default ./snapshots)")
    # a date must be supplied by the caller's clock; we read it once here.
    args = ap.parse_args()
    day = _dt.date.today().isoformat()
    host = socket.gethostname()
    d = os.path.join(os.path.expanduser(args.out), f"{day}-{host}")
    os.makedirs(d, exist_ok=True)
    # model-behavior.py and model-behavior-code.py accept --out; but to stay
    # decoupled we just capture their stdout to dated files.
    for extractor, name in (("model-behavior.py", "mb"),
                            ("model-behavior-code.py", "mc")):
        try:
            subprocess.run([sys.executable, os.path.join(HERE, extractor),
                            "--out", os.path.join(d, f"{name}-{host}.jsonl")],
                           check=True)
        except subprocess.CalledProcessError as e:
            print(f"extractor {extractor} failed: {e}", file=sys.stderr)
    print(f"snapshot written: {d}")
    print("keep this directory — it is your long-horizon fuel record. "
          "Tiny, local, and all you need alongside git.")


if __name__ == "__main__":
    main()
