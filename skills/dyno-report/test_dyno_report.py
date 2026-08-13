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
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude-code"))
import mb_cost  # noqa: E402  (to compute expected dollars the same way the driver does)

DAY = "2026-08-01"


def sess(sid, model, engine_kw, out, intok, cr, cw, day=DAY):
    r = {"k": "session", "sess": sid, "host": "fix", "day": day,
         "model": model, "msgs": 2, "submix": {},
         "workflows": 0, "wf_agents": 0, "plain_agents": 0,
         "main_usage": {model: {"in_tok": intok, "out_tok": out,
                                "cache_w_tok": cw, "cache_r_tok": cr}},
         "sub_usage": {}}
    r.update(engine_kw)
    return r


def turn(sid, model, out, intok, cr, cw, nudge=0, interrupted=0, ends_q=0):
    return {"k": "turn", "sess": sid, "model": model, "effort": "high",
            "in_tok": intok, "out_tok": out, "cache_r_tok": cr, "cache_w_tok": cw,
            "user_chars": 3, "n_asst": 1,
            "nudge": nudge, "interrupted": interrupted, "ends_q": ends_q}


def build_snapshot(d):
    # S1 solo opus-5:      born 10240 killed 1024 -> waste 10%, survKB 9.0
    # S2 delegate opus-4-8: born 20480 killed 6144 -> waste 30%, survKB 14.0
    # S3 workflow opus-5:   born 10240 killed 8192 -> waste 80%, survKB 2.0
    # s4 mirrors s2 (delegate/high) but with a CHEAP model, so the delegate/high
    # cell has a strong+cheap tier tie -> exercises deterministic tie-breaking.
    # Every delegate ratio axis is unchanged (s4 == s2 shape); only survKB doubles.
    # week A (08-03): s1, s2   week B (08-12): s3, s4  -> a two-week timeline with
    # a fingerprint change (orchestrator opus -> fable) detectable in week B.
    sessions = [
        sess("s1", "claude-opus-5", {}, 1000, 100, 9000, 900, day="2026-08-03"),
        sess("s2", "claude-opus-4-8", {"plain_agents": 2}, 2000, 200, 18000, 1800, day="2026-08-03"),
        sess("s3", "claude-opus-5", {"workflows": 1, "wf_agents": 4}, 1500, 150, 13500, 1350, day="2026-08-12"),
        sess("s4", "claude-fable-5", {"plain_agents": 2}, 2000, 200, 18000, 1800, day="2026-08-12"),
    ]
    # 2 interventions over 4 turns -> babysitting index 50.0 per 100 turns
    turns = [
        turn("s1", "claude-opus-5", 1000, 100, 9000, 900),
        turn("s2", "claude-opus-4-8", 2000, 200, 18000, 1800, nudge=1),
        turn("s3", "claude-opus-5", 1500, 150, 13500, 1350, ends_q=1),
        turn("s4", "claude-fable-5", 2000, 200, 18000, 1800),
    ]
    with open(os.path.join(d, "mb-fix.jsonl"), "w") as f:
        for r in sessions + turns:
            f.write(json.dumps(r) + "\n")
    # code records give orchestrator out_tok for the orch_tok/survKB axis
    code = [
        {"k": "code", "sess": "s2", "orch": {"out_tok": 500}, "work": {"out_tok": 0}},
        {"k": "code", "sess": "s3", "orch": {"out_tok": 800}, "work": {"out_tok": 0}},
        {"k": "code", "sess": "s4", "orch": {"out_tok": 500}, "work": {"out_tok": 0}},
    ]
    with open(os.path.join(d, "mc-fix.jsonl"), "w") as f:
        for r in code:
            f.write(json.dumps(r) + "\n")
    surv = {"s1": {"born": 10240, "killed": 1024},
            "s2": {"born": 20480, "killed": 6144},
            "s3": {"born": 10240, "killed": 8192},
            "s4": {"born": 20480, "killed": 6144}}
    with open(os.path.join(d, "survival-cache.json"), "w") as f:
        json.dump(surv, f)
    return sessions


def build_frontier(path, wf_cost):
    # Peg the same-shape workflow entry to ~2x the operator's own workflow/high
    # efficiency (survKB 2.0 at wf_cost dollars), so a lever is guaranteed to
    # exist regardless of the machine's real token prices.
    dps = round((wf_cost / 2.0) / 2.0, 8)  # dollars per survKB, half the operator's
    fr = {"schema": "agent-dyno/frontier@2", "axes": {}, "entries": [
        {"id": "fix-wf-high", "engine": "workflow", "effort": "high",
         "model_roles": {"orchestrator": "strong", "worker": "strong"},
         "vector": {"dollars_per_survkb": dps, "waste_pct": 30},
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
    # each line carries one decision point ("if") -> 6 surviving lines = complexity 6
    with open(p, "w") as fh:
        fh.write("\n".join(f"if line{i}:" for i in range(10)) + "\n")
    gitc(repo, "add", "f.txt")
    gitc(repo, "commit", "-q", "-m", "add ten")
    with open(p, "w") as fh:
        fh.write("\n".join(f"if line{i}:" for i in range(6)) + "\n")
    gitc(repo, "commit", "-qam", "trim to six")


def approx(a, b, tol=0.02):
    return a is not None and abs(a - b) <= tol


def run_driver(snap, repo, frontier, out, hashseed="0", baseline=None):
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    cmd = [sys.executable, os.path.join(HERE, "dyno_report.py"),
           "--harness", "claude-code", "--snapshot", snap,
           "--repos", repo, "--since", "1.day.ago",
           "--frontier", frontier, "--now", "1754006400", "--out", out]
    if baseline:
        cmd += ["--baseline", baseline]
    subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return json.load(open(os.path.join(out, "report.json")))


def main():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap"); os.makedirs(snap)
        repo = os.path.join(tmp, "repo"); os.makedirs(repo)
        frontier = os.path.join(tmp, "frontier.json")
        out1 = os.path.join(tmp, "out1"); out2 = os.path.join(tmp, "out2")

        sessions = build_snapshot(snap)
        prices = mb_cost.load_prices()
        costs = [mb_cost.session_cost(s, prices) for s in sessions]  # s1..s4
        build_frontier(frontier, costs[2])  # peg to s3 (workflow) cost
        build_repo(repo)
        rep = run_driver(snap, repo, frontier, out1)

        # ---- (1) per-engine vector equals hand-computed ----
        veng = {r["engine"]: r for r in rep["vector_by_engine"]}
        expect = {  # engine -> (survkb, waste, survkb_per_outmtok, cache_read_pct)
            "solo": (9.0, 10.0, 9000.0, 90.0),
            "delegate": (28.0, 30.0, 7000.0, 90.0),  # s2 + s4 (mirror), ratios unchanged
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
        exp_solo_d = costs[0]
        if not approx(veng["solo"]["d_per_survkb"], round(exp_solo_d / 9.0, 4), tol=0.01):
            fails.append(f"solo $/survKB {veng['solo']['d_per_survkb']} != "
                         f"{round(exp_solo_d / 9.0, 4)} (session_cost/survKB)")

        # orchestrator-tok axis on delegate: (500 + 500) orch out / 28.0 survKB
        if not approx(veng["delegate"]["orch_tok_per_survkb"], round(1000 / 28.0, 2), tol=0.1):
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
        # tier tie (delegate/high has strong s2 + cheap s4) must resolve deterministically
        deleg = ss.get(("delegate", "high"))
        if not deleg or deleg["operator_orchestrator_tier"] != "cheap":
            fails.append(f"delegate/high tier tie not broken deterministically: "
                         f"{deleg and deleg['operator_orchestrator_tier']} (expected 'cheap')")

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
        # DORA changes: fixture repo has no forge, 2 trunk commits, none are fixes
        nn = rep["numerator"]
        if nn["total_changes"] != 2 or nn["change_failure_rate"] != 0.0:
            fails.append(f"changes numerator wrong: {nn['total_changes']} changes, "
                         f"cfr {nn['change_failure_rate']}")
        if rep["numerator"]["repos"][0]["change_source"] != "git-trunk (approx)":
            fails.append("fixture change source should be the git-trunk fallback")
        # net complexity: 6 surviving lines each carry one "if" -> 6 decision points
        if nn["net_complexity"] != 6:
            fails.append(f"net_complexity should be 6, got {nn['net_complexity']}")

        # ---- (3b) topline EQ, the lever, and the surface ----
        # total surviving chars: s1 9216 + s2 14336 + s3 2048 + s4 14336 = 39936
        total_dollars = sum(costs)
        total_survkb = 39936 / 1024  # = 39.0
        eq_expected = round(total_survkb / total_dollars, 4)
        if rep["topline"]["eq"] != eq_expected:
            fails.append(f"topline EQ {rep['topline']['eq']} != {eq_expected}")

        # lever must target workflow/high (the only cell a same-shape frontier
        # entry beats), reference fix-wf-high, and predict the counterfactual EQ
        lever = rep.get("lever")
        if not lever or (lever["engine"], lever["effort"]) != ("workflow", "high"):
            fails.append(f"lever should target workflow/high, got {lever}")
        elif lever["frontier_id"] != "fix-wf-high":
            fails.append(f"lever cites wrong frontier entry: {lever['frontier_id']}")
        else:
            wf_cost = costs[2]  # s3 dollars; frontier $/survKB = (wf_cost/2)/2
            frontier_eq = 1.0 / ((wf_cost / 2.0) / 2.0)
            cf_dollars = 2.0 / frontier_eq  # cell survKB 2.0 at frontier efficiency
            new_eq = round(total_survkb / (total_dollars - wf_cost + cf_dollars), 4)
            if lever["predicted_topline_eq"] != new_eq:
                fails.append(f"lever predicted EQ {lever['predicted_topline_eq']} "
                             f"!= {new_eq}")
            if lever["predicted_delta"] <= 0:
                fails.append("lever predicted_delta should be positive")

        # babysitting index: 2 interventions (1 nudge + 1 ends_q) over 4 turns
        bs = rep.get("babysitting")
        if not bs or bs["per_100_turns"] != 50.0:
            fails.append(f"babysitting index should be 50.0/100 turns, got {bs}")

        # the surface (report.md) must be the simple coach view, not the wall
        md = open(os.path.join(out1, "report.md")).read()
        if "surviving KB per dollar" not in md:
            fails.append("surface is missing the topline number")
        if "Efficiency vector by engine" in md or "Same-shape comparison" in md:
            fails.append("surface leaked the machinery (vector/same-shape tables)")

        # ---- (3d) timeline over time, annotated with fingerprint changes ----
        tlr = [r for r in rep["timeline"] if r["eq"] is not None]
        if len(tlr) != 2:
            fails.append(f"timeline should have 2 weeks, got {len(tlr)}")
        else:
            # labels are human calendar dates (week's Monday), not ISO week numbers
            if not all(re.match(r"^[A-Z][a-z]{2} \d{1,2}$", r["week"]) for r in tlr):
                fails.append(f"week labels are not calendar dates: "
                             f"{[r['week'] for r in tlr]}")
            if tlr[0]["changes"]:
                fails.append("first week should have no change annotations")
            if not any("orchestrator" in c for c in tlr[1]["changes"]):
                fails.append(f"week 2 should annotate an orchestrator change, "
                             f"got {tlr[1]['changes']}")
        # fuel-and-work series: 2 weekly buckets; week 1 = s1+s2
        fw = (rep.get("fuel_and_work") or {}).get("series") or []
        if len(fw) != 2:
            fails.append(f"fuel_and_work should have 2 weekly buckets, got {len(fw)}")
        else:
            b0 = fw[0]
            if b0["surv_kb"] != 23.0:  # (9216 + 14336) / 1024
                fails.append(f"week1 net-code {b0['surv_kb']} != 23.0")
            if b0["output_tok"] != 3000 or b0["read_tok"] != 300:
                fails.append(f"week1 token streams wrong: {b0}")

        # the chart artifact exists and carries both charts
        htmlp = os.path.join(out1, "report.html")
        if not os.path.exists(htmlp):
            fails.append("report.html was not written")
        else:
            hh = open(htmlp).read()
            if "<svg" not in hh or "surviving KB per dollar" not in hh:
                fails.append("report.html is not the expected chart")
            if "Fuel and work over time" not in hh:
                fails.append("report.html is missing the fuel-and-work small multiples")

        # ---- (3c) the measure loop: re-run with the first report as baseline ----
        out3 = os.path.join(tmp, "out3")
        rep3 = run_driver(snap, repo, frontier, out3,
                          baseline=os.path.join(out1, "report.json"))
        m = rep3.get("measure")
        if not m or m["actual_delta"] != 0.0:
            fails.append(f"measure loop: same inputs should show 0 move, got {m}")
        elif lever and m["previously_predicted_delta"] != lever["predicted_delta"]:
            fails.append("measure loop did not carry the prior prediction")

        # ---- (4) byte-identical re-run under a DIFFERENT hash seed ----
        # (out1 ran with PYTHONHASHSEED=0; run out2 with =1 so any set-iteration
        # nondeterminism, e.g. tie-breaking, would diverge the bytes and fail.)
        run_driver(snap, repo, frontier, out2, hashseed="1")
        for name in ("report.json", "report.html"):
            b1 = open(os.path.join(out1, name), "rb").read()
            b2 = open(os.path.join(out2, name), "rb").read()
            if b1 != b2:
                fails.append(f"{name} is not byte-identical across runs / hash seeds")

    if fails:
        print("FAIL  dyno_report:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  dyno_report: vector, same-shape, provenance, determinism all hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
