#!/usr/bin/env python3
"""
demo.py, render a self-contained example report with zero external setup.

A worked example and an end-to-end test of the whole pipe. It fabricates a small
synthetic snapshot and a throwaway git repo (no harness transcripts, no network, no
real repos, no keys), runs the same deterministic driver a real report uses, and
writes report.{json,md,html}. `--selftest` asserts the artifacts render, so it
doubles as end-to-end coverage of build_report. Use it to see what a report looks
like without measuring your own setup.

It exercises the real machinery, not a stub: the git<->session join (proj-scoped
topline + per-model attribution), the fingerprint labels cache (pattern dims), the
same-shape lever against the repo's own frontier, and the fuel-and-work slicer.

Usage:
  python3 demo.py --out <dir>     # writes <dir>/report.{json,md,html}
  python3 demo.py --selftest      # render to a temp dir, assert artifacts, exit 0/1
Stdlib + git only.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import dyno_report  # noqa: E402


def _gitc(repo, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="dyno", GIT_AUTHOR_EMAIL="dyno@local",
               GIT_COMMITTER_NAME="dyno", GIT_COMMITTER_EMAIL="dyno@local")
    return subprocess.run(["git", "-C", repo, *a], env=env, check=True,
                          capture_output=True, text=True).stdout


def _iso_utc(epoch):
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).isoformat()


def _day(epoch):
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%d")


def build_demo_repo(repo):
    """A throwaway repo with decision-point-bearing code, some of it trimmed later
    so survival is below 100% (a realistic numerator)."""
    _gitc(repo, "init", "-q")
    p = os.path.join(repo, "engine.py")
    with open(p, "w") as fh:
        fh.write("\n".join(f"if branch_{i}: handle({i})" for i in range(20)) + "\n")
    _gitc(repo, "add", "engine.py")
    _gitc(repo, "commit", "-q", "-m", "add engine with twenty branches")
    with open(p, "w") as fh:  # trim to 13 surviving branches
        fh.write("\n".join(f"if branch_{i}: handle({i})" for i in range(13)) + "\n")
    _gitc(repo, "commit", "-qam", "fix: trim engine to thirteen branches")
    cts = [int(x) for x in _gitc(repo, "log", "--format=%ct").split()]
    return min(cts)


def build_snapshot(snap, repo_name, commit_lo):
    """Four sessions across engines / models / weeks, all in the demo repo, with a
    routing mix and a two-effort mix (so the report shows real slices and names its
    confounds). s4's window brackets the commits, so the join attributes the
    surviving branches to its model."""
    wk = {i: commit_lo - i * 7 * 86400 for i in (3, 2, 1, 0)}  # weeks ago -> epoch

    def usage(intok, out, cr, cw):
        return {"in_tok": intok, "out_tok": out, "cache_w_tok": cw, "cache_r_tok": cr}

    def session(sid, model, kw, submix, out, cr, epoch):
        r = {"k": "session", "sess": sid, "host": "demo", "day": _day(epoch),
             "proj": repo_name, "model": model, "msgs": 4, "submix": submix,
             "workflows": 0, "wf_agents": 0, "plain_agents": 0,
             "main_usage": {model: usage(out // 10, out, cr, cr // 10)},
             "sub_usage": {}}
        for wm, wu in submix.items():
            r["sub_usage"][wm] = wu
        r.update(kw)
        return r

    son = {"claude-sonnet-5": usage(400, 4000, 36000, 3600)}
    hai = {"claude-haiku-4-5": usage(300, 3000, 27000, 2700)}
    sessions = [
        session("d1", "claude-opus-5", {}, {}, 6000, 54000, wk[3]),
        session("d2", "claude-opus-4-8", {"plain_agents": 2}, son, 9000, 81000, wk[2]),
        session("d3", "claude-sonnet-5", {"workflows": 1, "wf_agents": 4}, hai, 7000, 63000, wk[1]),
        session("d4", "claude-opus-5", {}, {}, 5000, 45000, wk[0]),
    ]
    # turn ts: only d4's window brackets the commits (attribution -> opus-5/medium)
    turns = [
        {"k": "turn", "sess": "d1", "effort": "high", "in_tok": 600, "out_tok": 6000,
         "cache_r_tok": 54000, "cache_w_tok": 5400, "user_chars": 40, "n_asst": 4,
         "proj": repo_name, "ts": _iso_utc(wk[3]), "nudge": 0, "interrupted": 0, "ends_q": 0},
        {"k": "turn", "sess": "d2", "effort": "high", "in_tok": 900, "out_tok": 9000,
         "cache_r_tok": 81000, "cache_w_tok": 8100, "user_chars": 30, "n_asst": 4,
         "proj": repo_name, "ts": _iso_utc(wk[2]), "nudge": 1, "interrupted": 0, "ends_q": 0},
        {"k": "turn", "sess": "d3", "effort": "high", "in_tok": 700, "out_tok": 7000,
         "cache_r_tok": 63000, "cache_w_tok": 6300, "user_chars": 20, "n_asst": 4,
         "proj": repo_name, "ts": _iso_utc(wk[1]), "nudge": 0, "interrupted": 1, "ends_q": 0},
        {"k": "turn", "sess": "d4", "effort": "medium", "in_tok": 500, "out_tok": 5000,
         "cache_r_tok": 45000, "cache_w_tok": 4500, "user_chars": 25, "n_asst": 4,
         "proj": repo_name, "ts": _iso_utc(commit_lo), "nudge": 0, "interrupted": 0, "ends_q": 0},
    ]
    with open(os.path.join(snap, "mb-demo.jsonl"), "w") as f:
        for r in sessions + turns:
            f.write(json.dumps(r) + "\n")
    code = [
        {"k": "code", "sess": "d2", "orch": {"out_tok": 3000}, "work": {"out_tok": 6000}},
        {"k": "code", "sess": "d3", "orch": {"out_tok": 4000}, "work": {"out_tok": 3000}},
    ]
    with open(os.path.join(snap, "mc-demo.jsonl"), "w") as f:
        for r in code:
            f.write(json.dumps(r) + "\n")
    survival = {"d1": {"born": 12000, "killed": 1200},
                "d2": {"born": 24000, "killed": 6000},
                "d3": {"born": 16000, "killed": 12000},
                "d4": {"born": 14000, "killed": 1000}}
    with open(os.path.join(snap, "survival-cache.json"), "w") as f:
        json.dump(survival, f)
    # pattern-dimension labels for the four distinct rigs (engine/routing/effort)
    labels = {"schema": "agent-dyno/fingerprint-labels@1", "rigs": {
        "solo/none/high": {"fine_topology": "single-agent",
                           "review_regime": "spec + acceptance",
                           "knowledge_practice": "skills"},
        "solo/none/medium": {"fine_topology": "single-agent",
                             "review_regime": "automated",
                             "knowledge_practice": "skills"},
        "delegate/cross-family/high": {"fine_topology": "orchestrator-workers",
                                       "review_regime": "agentic review pass",
                                       "knowledge_practice": "skills"},
        "workflow/cross-family/high": {"fine_topology": "parallelization",
                                       "review_regime": "sweeps",
                                       "knowledge_practice": "memory"}}}
    with open(os.path.join(snap, "fingerprint-labels.json"), "w") as f:
        json.dump(labels, f)


def render(out_dir):
    """Fabricate the demo inputs under out_dir/_demo and render the report to
    out_dir. Returns the path to report.json."""
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "_demo")
    snap = os.path.join(work, "snap")
    repo = os.path.join(work, "workbench")
    os.makedirs(snap, exist_ok=True)
    os.makedirs(repo, exist_ok=True)
    commit_lo = build_demo_repo(repo)
    build_snapshot(snap, os.path.basename(repo), commit_lo)
    frontier = os.path.join(ROOT, "frontier", "reference-frontier.json")
    report = dyno_report.build_report(
        snap, [repo], "90.days.ago", frontier, "claude-code",
        commit_lo + 3600, granularity="week")
    with open(os.path.join(out_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write(dyno_report.render_md(report))
    with open(os.path.join(out_dir, "report.html"), "w") as f:
        f.write(dyno_report.render_html(report))
    return os.path.join(out_dir, "report.json")


def selftest():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out")
        render(out)
        rep = json.load(open(os.path.join(out, "report.json")))
        if rep.get("topline", {}).get("eq") is None:
            fails.append("demo report has no topline eq")
        if not rep.get("topline", {}).get("denominator_sessions"):
            fails.append("demo topline denominator not scoped (git<->session join)")
        html = open(os.path.join(out, "report.html")).read()
        if "<svg" not in html or "functionality per Mtok" not in html:
            fails.append("demo report.html is not a rendered chart")
        if "Fuel and work over time" not in html:
            fails.append("demo report.html missing the fuel-and-work slicer")
        md = open(os.path.join(out, "report.md")).read()
        if "functionality per Mtok" not in md:
            fails.append("demo report.md missing the topline surface")
    if fails:
        print("FAIL  demo:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  demo: end-to-end render (snapshot + repo -> report.{json,md,html})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="write report.{json,md,html} here")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.out:
        ap.error("--out is required (or use --selftest)")
    path = render(os.path.abspath(args.out))
    print(f"rendered demo report: {path}")
    print(f"  open {os.path.join(os.path.dirname(path), 'report.html')} in a browser")


if __name__ == "__main__":
    main()
