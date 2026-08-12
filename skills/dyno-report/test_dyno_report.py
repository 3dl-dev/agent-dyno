#!/usr/bin/env python3
"""
Acceptance test for dyno_report (the spec made executable).

Builds a fixture snapshot (three sessions, one per engine, known tokens and
known born/killed chars), a throwaway git repo with a known survival answer, and
a fixture frontier with one same-shape and one different-shape entry. Runs the
driver and asserts the vector, the same-shape logic, provenance + governance
stamp, and byte-identical re-runs. Regenerate dyno_report.py from
dyno_report.spec.md and this test must still pass.

    python3 skills/dyno-report/test_dyno_report.py    # exits 0 on pass, 1 on fail
Stdlib only. Needs git on PATH.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude-code"))
import mb_cost  # noqa: E402  (to compute expected dollars the same way the driver does)

DAY = "2026-08-01"


def sess(sid, model, engine_kw, out, intok, cr, cw):
    r = {"k": "session", "sess": sid, "host": "fix", "day": DAY,
         "model": model, "msgs": 2, "submix": {},
         "workflows": 0, "wf_agents": 0, "plain_agents": 0,
         "main_usage": {model: {"in_tok": intok, "out_tok": out,
                                "cache_w_tok": cw, "cache_r_tok": cr}},
         "sub_usage": {}}
    r.update(engine_kw)
    return r


def turn(sid, model, out, intok, cr, cw):
    return {"k": "turn", "sess": sid, "model": model, "effort": "high",
            "in_tok": intok, "out_tok": out, "cache_r_tok": cr, "cache_w_tok": cw,
            "user_chars": 3, "n_asst": 1}


def build_snapshot(d):
    # S1 solo opus-5:      born 10240 killed 1024 -> waste 10%, survKB 9.0
    # S2 delegate opus-4-8: born 20480 killed 6144 -> waste 30%, survKB 14.0
    # S3 workflow opus-5:   born 10240 killed 8192 -> waste 80%, survKB 2.0
    sessions = [
        sess("s1", "claude-opus-5", {}, 1000, 100, 9000, 900),
        sess("s2", "claude-opus-4-8", {"plain_agents": 2}, 2000, 200, 18000, 1800),
        sess("s3", "claude-opus-5", {"workflows": 1, "wf_agents": 4}, 1500, 150, 13500, 1350),
    ]
    turns = [
        turn("s1", "claude-opus-5", 1000, 100, 9000, 900),
        turn("s2", "claude-opus-4-8", 2000, 200, 18000, 1800),
        turn("s3", "claude-opus-5", 1500, 150, 13500, 1350),
    ]
    with open(os.path.join(d, "mb-fix.jsonl"), "w") as f:
        for r in sessions + turns:
            f.write(json.dumps(r) + "\n")
    # code records give orchestrator out_tok for the orch_tok/survKB axis
    code = [
        {"k": "code", "sess": "s2", "orch": {"out_tok": 500}, "work": {"out_tok": 0}},
        {"k": "code", "sess": "s3", "orch": {"out_tok": 800}, "work": {"out_tok": 0}},
    ]
    with open(os.path.join(d, "mc-fix.jsonl"), "w") as f:
        for r in code:
            f.write(json.dumps(r) + "\n")
    surv = {"s1": {"born": 10240, "killed": 1024},
            "s2": {"born": 20480, "killed": 6144},
            "s3": {"born": 10240, "killed": 8192}}
    with open(os.path.join(d, "survival-cache.json"), "w") as f:
        json.dump(surv, f)
    return sessions


def build_frontier(path):
    fr = {"schema": "agent-dyno/frontier@2", "axes": {}, "entries": [
        {"id": "fix-wf-high", "engine": "workflow", "effort": "high",
         "model_roles": {"orchestrator": "strong", "worker": "strong"},
         "vector": {"dollars_per_survkb": 1.15, "waste_pct": 30},
         "technique": "review pass behind fan-out", "proof": "tier-1-self-report"},
        {"id": "fix-solo-low", "engine": "solo", "effort": "low",
         "model_roles": {"orchestrator": "strong", "worker": None},
         "vector": {"dollars_per_survkb": 2.0, "waste_pct": 5},
         "technique": "low-effort solo", "proof": "tier-1-self-report"},
    ]}
    with open(path, "w") as f:
        json.dump(fr, f)


def gitc(repo, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", repo, *a], env=env,
                          capture_output=True, text=True, check=True).stdout


def build_repo(repo):
    gitc(repo, "init", "-q")
    p = os.path.join(repo, "f.txt")
    with open(p, "w") as fh:
        fh.write("\n".join(f"line{i}" for i in range(10)) + "\n")
    gitc(repo, "add", "f.txt")
    gitc(repo, "commit", "-q", "-m", "add ten")
    with open(p, "w") as fh:
        fh.write("\n".join(f"line{i}" for i in range(6)) + "\n")
    gitc(repo, "commit", "-qam", "trim to six")


def approx(a, b, tol=0.02):
    return a is not None and abs(a - b) <= tol


def run_driver(snap, repo, frontier, out):
    subprocess.run([sys.executable, os.path.join(HERE, "dyno_report.py"),
                    "--harness", "claude-code", "--snapshot", snap,
                    "--repos", repo, "--since", "1.day.ago",
                    "--frontier", frontier, "--now", "1754006400", "--out", out],
                   check=True, capture_output=True, text=True)
    return json.load(open(os.path.join(out, "report.json")))


def main():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap"); os.makedirs(snap)
        repo = os.path.join(tmp, "repo"); os.makedirs(repo)
        frontier = os.path.join(tmp, "frontier.json")
        out1 = os.path.join(tmp, "out1"); out2 = os.path.join(tmp, "out2")

        sessions = build_snapshot(snap)
        build_frontier(frontier)
        build_repo(repo)
        rep = run_driver(snap, repo, frontier, out1)

        # ---- (1) per-engine vector equals hand-computed ----
        veng = {r["engine"]: r for r in rep["vector_by_engine"]}
        expect = {  # engine -> (survkb, waste, survkb_per_outmtok, cache_read_pct)
            "solo": (9.0, 10.0, 9000.0, 90.0),
            "delegate": (14.0, 30.0, 7000.0, 90.0),
            "workflow": (2.0, 80.0, 1333.33, 90.0),
        }
        for e, (skb, waste, spm, crd) in expect.items():
            v = veng.get(e)
            if not v:
                fails.append(f"missing engine {e}"); continue
            if not approx(v["surv_kb"], skb):
                fails.append(f"{e} survKB {v['surv_kb']} != {skb}")
            if not approx(v["waste_pct"], waste):
                fails.append(f"{e} waste {v['waste_pct']} != {waste}")
            if not approx(v["survkb_per_outmtok"], spm, tol=1.0):
                fails.append(f"{e} survKB/Mtok {v['survkb_per_outmtok']} != {spm}")
            if not approx(v["cache_read_pct"], crd):
                fails.append(f"{e} cacheRd {v['cache_read_pct']} != {crd}")

        # dollars axis: driver must equal session_cost/survKB (wired, not invented)
        prices = mb_cost.load_prices()
        exp_solo_d = mb_cost.session_cost(sessions[0], prices)
        if not approx(veng["solo"]["d_per_survkb"], round(exp_solo_d / 9.0, 4), tol=0.01):
            fails.append(f"solo $/survKB {veng['solo']['d_per_survkb']} != "
                         f"{round(exp_solo_d / 9.0, 4)} (session_cost/survKB)")

        # orchestrator-tok axis on delegate: 500 / 14.0
        if not approx(veng["delegate"]["orch_tok_per_survkb"], round(500 / 14.0, 2), tol=0.1):
            fails.append(f"delegate orch_tok/survKB wrong: "
                         f"{veng['delegate']['orch_tok_per_survkb']}")

        # ---- (2) same-shape: only same (engine,effort) matches; else stated ----
        ss = {(s["engine"], s["effort"]): s for s in rep["same_shape"]}
        wf = ss.get(("workflow", "high"))
        if not wf or wf["status"] != "matched":
            fails.append("workflow/high should match a same-shape frontier entry")
        elif [m["id"] for m in wf["frontier_matches"]] != ["fix-wf-high"]:
            fails.append(f"workflow/high matched wrong entries: {wf['frontier_matches']}")
        solo = ss.get(("solo", "high"))
        if not solo or solo["status"] != "no-same-shape-entry":
            fails.append("solo/high should be no-same-shape-entry (frontier solo is effort=low)")

        # ---- (3) provenance + governance stamp ----
        prov = rep["provenance"]
        if not prov.get("frontier_sha256") or prov.get("driver") != "dyno_report/1":
            fails.append("provenance incomplete")
        if not prov["repos"] or not prov["repos"][0].get("head"):
            fails.append("provenance missing repo HEAD")
        if rep["governance"].get("clean") is not True:
            fails.append("governance not stamped clean")
        # numerator sanity: 10 added, 4 deleted -> 60%
        if not approx(rep["numerator"]["pct"], 60.0, tol=0.5):
            fails.append(f"numerator pct {rep['numerator']['pct']} != 60")

        # ---- (4) byte-identical re-run ----
        run_driver(snap, repo, frontier, out2)
        b1 = open(os.path.join(out1, "report.json"), "rb").read()
        b2 = open(os.path.join(out2, "report.json"), "rb").read()
        if b1 != b2:
            fails.append("report.json is not byte-identical across runs")

    if fails:
        print("FAIL  dyno_report:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  dyno_report: vector, same-shape, provenance, determinism all hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
