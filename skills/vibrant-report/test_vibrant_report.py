#!/usr/bin/env python3
"""
Acceptance test for vibrant_report (the spec made executable).

Builds a fixture snapshot (three sessions, one per engine, known tokens and
known born/killed chars), a throwaway git repo with a known survival answer, and
a fixture frontier with one same-shape and one different-shape entry. Runs the
driver and asserts the vector, the same-shape logic, provenance + governance
stamp, and byte-identical re-runs. Regenerate vibrant_report.py from
vibrant_report.spec.md and this test must still pass.

    python3 skills/vibrant-report/test_vibrant_report.py    # exits 0 on pass, 1 on fail
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
sys.path.insert(0, HERE)
import vibrant_report  # noqa: E402  (to unit-test the pure confounds() function directly)

DAY = "2026-08-01"


def sess(sid, model, engine_kw, out, intok, cr, cw, day=DAY, proj=""):
    r = {"k": "session", "sess": sid, "host": "fix", "day": day, "proj": proj,
         "model": model, "msgs": 2, "submix": {},
         "workflows": 0, "wf_agents": 0, "plain_agents": 0,
         "main_usage": {model: {"in_tok": intok, "out_tok": out,
                                "cache_w_tok": cw, "cache_r_tok": cr}},
         "sub_usage": {}}
    r.update(engine_kw)
    return r


def turn(sid, model, out, intok, cr, cw, nudge=0, interrupted=0, ends_q=0,
         proj="", ts=None):
    return {"k": "turn", "sess": sid, "model": model, "effort": "high",
            "in_tok": intok, "out_tok": out, "cache_r_tok": cr, "cache_w_tok": cw,
            "user_chars": 3, "n_asst": 1, "proj": proj, "ts": ts,
            "nudge": nudge, "interrupted": interrupted, "ends_q": ends_q}


def iso_utc(epoch):
    """Tz-aware UTC ISO string; horizon_attribute.parse_iso resolves it to the same
    epoch a git %ct commit time carries (a naive string would be read as local)."""
    import datetime
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).isoformat()


def build_snapshot(d, commit_lo):
    # S1 solo opus-5:      born 10240 killed 1024 -> waste 10%, survKB 9.0
    # S2 delegate opus-4-8: born 20480 killed 6144 -> waste 30%, survKB 14.0
    # S3 workflow opus-5:   born 10240 killed 8192 -> waste 80%, survKB 2.0
    # s4 mirrors s2 (delegate/high) but with a CHEAP model, so the delegate/high
    # cell has a strong+cheap tier tie -> exercises deterministic tie-breaking.
    # Every delegate ratio axis is unchanged (s4 == s2 shape); only survKB doubles.
    # week A (08-03): s1, s2   week B (08-12): s3, s4  -> a two-week timeline with
    # a fingerprint change (orchestrator opus -> fable) detectable in week B.
    #
    # Join fixture (item 2): s1/s2/s3 have proj "repo" (they worked the measured
    # repo); s4 has proj "elsewhere" (its output is OUTSIDE the topline scope).
    # Turn ts places only s1's window over the fixture commits (commit_lo), so the
    # git<->session join attributes the surviving complexity to s1's model opus-5;
    # s2/s3 windows sit 30 days earlier so they are not commit candidates. (The
    # join ts axis is deliberately separate from the timeline `day` axis: commits
    # land at test-run wall-clock, the timeline is the synthetic Aug calendar.)
    far = commit_lo - 30 * 86400
    sessions = [
        sess("s1", "claude-opus-5", {}, 1000, 100, 9000, 900, day="2026-08-03", proj="repo"),
        sess("s2", "claude-opus-4-8", {"plain_agents": 2}, 2000, 200, 18000, 1800, day="2026-08-03", proj="repo"),
        sess("s3", "claude-opus-5", {"workflows": 1, "wf_agents": 4}, 1500, 150, 13500, 1350, day="2026-08-12", proj="repo"),
        sess("s4", "claude-fable-5", {"plain_agents": 2}, 2000, 200, 18000, 1800, day="2026-08-12", proj="elsewhere"),
    ]
    # 2 interventions over 4 turns -> babysitting index 50.0 per 100 turns
    turns = [
        turn("s1", "claude-opus-5", 1000, 100, 9000, 900, proj="repo", ts=iso_utc(commit_lo)),
        turn("s2", "claude-opus-4-8", 2000, 200, 18000, 1800, nudge=1, proj="repo", ts=iso_utc(far)),
        turn("s3", "claude-opus-5", 1500, 150, 13500, 1350, ends_q=1, proj="repo", ts=iso_utc(far)),
        turn("s4", "claude-fable-5", 2000, 200, 18000, 1800, proj="elsewhere", ts=iso_utc(far)),
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
    fr = {"schema": "vibrant/frontier@2", "axes": {}, "entries": [
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


def build_labels(path):
    """A fingerprint-labels cache for the fixture's three distinct rigs (all have
    empty submix -> routing 'none', all high effort). Modal review_regime across
    the four sessions is 'agentic review pass' (s2+s4 delegate); modal fine is
    'orchestrator-workers'; modal knowledge_practice is 'skills'."""
    labels = {"schema": "vibrant/fingerprint-labels@1", "rigs": {
        "solo/none/high": {"fine_topology": "single-agent",
                           "review_regime": "spec + acceptance",
                           "knowledge_practice": "skills"},
        "delegate/none/high": {"fine_topology": "orchestrator-workers",
                               "review_regime": "agentic review pass",
                               "knowledge_practice": "skills"},
        "workflow/none/high": {"fine_topology": "parallelization",
                               "review_regime": "sweeps",
                               "knowledge_practice": "memory"}}}
    with open(path, "w") as f:
        json.dump(labels, f)


def run_driver(snap, repo, frontier, out, hashseed="0", baseline=None, labels=None):
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    cmd = [sys.executable, os.path.join(HERE, "vibrant_report.py"),
           "--harness", "claude-code", "--snapshot", snap,
           "--repos", repo, "--since", "1.day.ago",
           "--frontier", frontier, "--now", "1754006400", "--out", out]
    if baseline:
        cmd += ["--baseline", baseline]
    if labels:
        cmd += ["--labels", labels]
    subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return json.load(open(os.path.join(out, "report.json")))


def check_confounds(fails):
    """(item 4) confounds() names effort mix, review-regime mix / uncontrolled, and
    non-overlapping fuel/git windows. Unit-tested directly (pure function)."""
    import datetime
    now = int(datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc).timestamp())

    def mm(effort, regime, day):
        return {"effort": effort, "review_regime": regime, "day": day}

    num = {"repos": []}
    # mixed effort + mixed regime + Jan sessions against a Jul-Aug git window
    cf = vibrant_report.confounds(
        [mm("high", "sweeps", "2026-01-05"), mm("low", "manual", "2026-01-06")],
        num, "30.days.ago", now)
    j = " || ".join(cf)
    if "Effort mix" not in j:
        fails.append(f"confounds: effort-mix not named: {cf}")
    if "Review-regime mix" not in j:
        fails.append(f"confounds: review-regime mix not named: {cf}")
    if "Window mismatch" not in j:
        fails.append(f"confounds: non-overlapping fuel/git window not named: {cf}")
    # uniform effort + all-unclassified regime + overlapping window: only the
    # 'uncontrolled review regime' confound should fire (not effort/window/mix).
    cf2 = vibrant_report.confounds(
        [mm("high", "unclassified", "2026-07-20"),
         mm("high", "unclassified", "2026-07-21")], num, "30.days.ago", now)
    j2 = " || ".join(cf2)
    if "uncontrolled" not in j2:
        fails.append(f"confounds: uncontrolled review regime not named: {cf2}")
    if "Effort mix" in j2:
        fails.append(f"confounds: effort-mix falsely named on uniform effort: {cf2}")
    if "Window mismatch" in j2:
        fails.append(f"confounds: window-mismatch falsely named on overlap: {cf2}")
    if "Empty denominator" in j2:
        fails.append(f"confounds: empty-denominator falsely named by default: {cf2}")
    # denom_empty=True names the empty-denominator confound (null-topline case)
    cf3 = vibrant_report.confounds([mm("high", "sweeps", "2026-07-20")], num,
                                "30.days.ago", now, denom_empty=True)
    if "Empty denominator" not in " || ".join(cf3):
        fails.append(f"confounds: empty-denominator not named when set: {cf3}")


def check_frontier_loading(fails):
    """(federation read side) --frontier accepts a path and a file:// URL, and
    degrades to an empty frontier when unfetchable, never raising."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "fr.json")
    payload = {"schema": "vibrant/frontier@2",
               "entries": [{"id": "x", "engine": "solo", "vector": {},
                            "date": "2026-08-01"}]}
    json.dump(payload, open(p, "w"))
    fr, raw = vibrant_report.load_frontier(p)
    if [e["id"] for e in fr.get("entries", [])] != ["x"] or not raw:
        fails.append("load_frontier: path form failed")
    fr2, raw2 = vibrant_report.load_frontier("file://" + p)
    if [e["id"] for e in fr2.get("entries", [])] != ["x"] or raw2 != raw:
        fails.append("load_frontier: file:// URL did not resolve to the same bytes")
    fr3, raw3 = vibrant_report.load_frontier(os.path.join(d, "nope.json"))
    if fr3 != {"entries": []} or raw3 != b"":
        fails.append(f"load_frontier: missing path should degrade to empty, got {fr3}")
    fr4, _ = vibrant_report.load_frontier("http://127.0.0.1:9/nope")
    if fr4 != {"entries": []}:
        fails.append("load_frontier: unfetchable URL should degrade to empty")


def check_detect_changes(fails):
    """(falsifiability) detect_changes dates a real setup change to the day it
    happened, and invents nothing on a blended dimension that never holds a
    sustained majority."""
    import datetime

    def day(i):
        return (datetime.date(2026, 8, 1) + datetime.timedelta(days=i)).isoformat()

    def mm(d, engine):
        return {"day": d, "engine": engine, "model": "opus-5", "effort": "high"}

    # a real sustained regime change: 10 days majority-solo, then 10 majority-delegate
    ms = ([mm(day(i), "solo") for i in range(10)]
          + [mm(day(i), "delegate") for i in range(10, 20)])
    eng = [c for c in vibrant_report.detect_changes(ms) if c["dim"] == "engine"]
    if not (len(eng) == 1 and eng[0]["from"] == "solo" and eng[0]["to"] == "delegate"
            and eng[0]["date"] == day(10)):
        fails.append(f"detect_changes should date one solo->delegate change to "
                     f"{day(10)}: got {eng}")
    # blended alternation: the day-majority flips daily and never sustains -> nothing
    alt = []
    for i in range(24):
        maj, minr = ("solo", "delegate") if i % 2 == 0 else ("delegate", "solo")
        alt += [mm(day(i), maj)] * 3 + [mm(day(i), minr)] * 2
    if [c for c in vibrant_report.detect_changes(alt) if c["dim"] == "engine"]:
        fails.append(f"detect_changes invented a change on blended/alternating data: "
                     f"{vibrant_report.detect_changes(alt)}")


def main():
    fails = []
    check_confounds(fails)
    check_frontier_loading(fails)
    check_detect_changes(fails)
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap"); os.makedirs(snap)
        repo = os.path.join(tmp, "repo"); os.makedirs(repo)
        frontier = os.path.join(tmp, "frontier.json")
        out1 = os.path.join(tmp, "out1"); out2 = os.path.join(tmp, "out2")

        # repo first: its commit timestamps place the join windows in the snapshot
        build_repo(repo)
        cts = [int(x) for x in gitc(repo, "log", "--format=%ct").split()]
        sessions = build_snapshot(snap, min(cts))
        prices = mb_cost.load_prices()
        costs = [mb_cost.session_cost(s, prices) for s in sessions]  # s1..s4
        build_frontier(frontier, costs[2])  # peg to s3 (workflow) cost
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

        # ---- (1b) per-engine simplicity present + matches the git-density formula ----
        att_be = rep["numerator"]["attribution"]["by_engine"]
        for e, v in veng.items():
            if "simplicity" not in v:
                fails.append(f"{e} missing per-engine simplicity"); continue
            b = att_be.get(e, {})
            exp_simp = vibrant_report._density_simplicity(
                vibrant_report._surviving_lines(b.get("net_complexity"), b.get("surviving", 0)))
            if v["simplicity"] != exp_simp:
                fails.append(f"{e} simplicity {v['simplicity']} != {exp_simp} (density formula)")

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
        if not prov.get("frontier_sha256") or prov.get("driver") != "vibrant_report/1":
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
        total_survkb = 39936 / 1024  # = 39.0 (still drives the lever math below)
        # topline eq = surviving FUNCTIONALITY (durable decision points) per Mtok OUTPUT,
        # larger better (the continuous numerator). The fixture repo has 2 non-fix commits
        # (durable_changes 2) carrying complexity 6 (durable_complexity 6); eq = 6/Mtok. The
        # change count rides alongside as change_throughput = 2/Mtok. bloat (6/2 = 3) stays a
        # change-discipline meter. The denominator scopes to sessions whose proj names the
        # repo: s1+s2+s3 (proj "repo"); s4's output (proj "elsewhere") is excluded.
        matched_out = sum(s["main_usage"][s["model"]]["out_tok"]
                          for s in sessions if "repo" in s.get("proj", ""))
        eq_expected = round(6 / (matched_out / 1e6), 1)  # durable_complexity 6 / scoped-Mtok
        if rep["topline"]["eq"] != eq_expected:
            fails.append(f"topline EQ {rep['topline']['eq']} != {eq_expected}")
        ct_expected = round(2 / (matched_out / 1e6), 2)  # change count / scoped-Mtok
        if rep["topline"].get("change_throughput") != ct_expected:
            fails.append(f"change_throughput {rep['topline'].get('change_throughput')} != {ct_expected}")
        if rep["topline"].get("bloat") != 3.0:
            fails.append(f"bloat should be 3.0 (complexity 6 / 2 changes), got "
                         f"{rep['topline'].get('bloat')}")
        if rep["topline"].get("denominator_sessions") != 3:
            fails.append(f"topline denominator should scope to 3 matched sessions, "
                         f"got {rep['topline'].get('denominator_sessions')}")
        if rep["topline"].get("larger_is_better") is not True:
            fails.append("topline should be flagged larger-is-better")

        # per-model / per-effort work units: the fixture commits attribute to s1
        # (opus-5, high), so 6 surviving decision points land there.
        attr = rep["numerator"].get("attribution") or {}
        if attr.get("matched", 0) < 1:
            fails.append(f"git<->session join matched no commits: {attr}")
        # attributed to the ORCHESTRATOR (opus-5), the EFFORT (high), and the full
        # model-ROLES config (opus-5 -> <worker>): survival is a rig property.
        if ((attr.get("by_orchestrator") or {}).get("opus-5") or {}).get("net_complexity") != 6:
            fails.append(f"attribution.by_orchestrator opus-5 net_complexity should be "
                         f"6, got {attr.get('by_orchestrator')}")
        if ((attr.get("by_effort") or {}).get("high") or {}).get("net_complexity") != 6:
            fails.append(f"attribution.by_effort high net_complexity should be 6, "
                         f"got {attr.get('by_effort')}")
        roles = attr.get("by_model_roles") or {}
        if not any(k.startswith("opus-5 ->") and v.get("net_complexity") == 6
                   for k, v in roles.items()):
            fails.append(f"attribution.by_model_roles should credit an 'opus-5 -> *' "
                         f"rig with 6 net_complexity, got {roles}")

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
            # (item 4) the lever prediction is honestly a survKB/$ engine-efficiency
            # move, NOT the topline headline: fields must say so, and the old
            # mislabeled key must be gone.
            if lever.get("predicted_efficiency") != new_eq:
                fails.append(f"lever predicted_efficiency {lever.get('predicted_efficiency')} "
                             f"!= {new_eq}")
            if lever.get("predicted_efficiency_delta", 0) <= 0:
                fails.append("lever predicted_efficiency_delta should be positive")
            if "predicted_topline_eq" in lever:
                fails.append("lever still carries the mislabeled predicted_topline_eq")
            if lever.get("unit") != "surviving-KB per dollar":
                fails.append(f"lever unit not honestly named: {lever.get('unit')}")
            if "not the topline" not in (lever.get("predicts") or ""):
                fails.append(f"lever should state it does not predict the topline: "
                             f"{lever.get('predicts')}")

        # babysitting index: 2 interventions (1 nudge + 1 ends_q) over 4 turns
        bs = rep.get("babysitting")
        if not bs or bs["per_100_turns"] != 50.0:
            fails.append(f"babysitting index should be 50.0/100 turns, got {bs}")

        # the surface (report.md) must be the simple coach view, not the wall
        md = open(os.path.join(out1, "report.md")).read()
        if "durable shipped changes per Mtok" not in md:
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
            # both fixture weeks are blended (2 distinct models, no majority), so
            # NEITHER should flag a spurious change: the honest behavior. Real-shift
            # detection is exercised in check_timeline_changes().
            if tlr[1]["changes"]:
                fails.append(f"week 2 (blended, no majority) should flag no spurious "
                             f"change, got {tlr[1]['changes']}")
        # fuel-and-work series: 2 weekly buckets; week 1 = s1+s2
        fwroot = rep.get("fuel_and_work") or {}
        fw = fwroot.get("series") or []
        if len(fw) != 2:
            fails.append(f"fuel_and_work should have 2 weekly buckets, got {len(fw)}")
        # sliced by model: opus-5 / opus-4-8 / fable-5 each get their own series
        bym = fwroot.get("by_model") or {}
        if not ({"opus-5", "opus-4-8", "fable-5"} <= set(bym)):
            fails.append(f"fuel_and_work.by_model missing model slices: {sorted(bym)}")
        if not fwroot.get("by_effort") or not fwroot.get("by_engine"):
            fails.append("fuel_and_work missing by_effort / by_engine slices")
        if not fwroot.get("by_routing"):
            fails.append("fuel_and_work missing by_routing slice (new fingerprint dim)")
        # fingerprint contract: rig placed on the taxonomy's six dimensions
        fpr = rep.get("fingerprint") or {}
        for dim in ("orchestration_topology", "model_routing", "reasoning_effort",
                    "review_regime", "knowledge_practice", "delivery_cadence"):
            if dim not in fpr:
                fails.append(f"fingerprint contract missing dimension: {dim}")
        if "pending" not in str(fpr.get("review_regime", "")):
            fails.append("review_regime should be a pending-classification slot")
        # countable dims describe the stack by their arms (blend), not one modal
        # label: the fixture is 2 delegate / 1 solo / 1 workflow, so a blended stack
        # led by delegate, flagged is_blended (no 60% majority).
        topo = fpr.get("orchestration_topology") or {}
        b = topo.get("blend")
        if not isinstance(b, list) or (b[0]["value"] if b else None) != "delegate":
            fails.append(f"topology should be a blend led by delegate (2 of 4): {b}")
        if topo.get("is_blended") is not True:
            fails.append("topology should be flagged is_blended (no majority engine)")
        if sum(x["sessions"] for x in (b or [])) != 4:
            fails.append("topology blend sessions should sum to 4")
        if "orchestrator_model" not in fpr:
            fails.append("fingerprint missing the orchestrator_model arm")
        # week-1 fuel/token streams: independent of the pending check above (must
        # run unconditionally, not nested in its else, or they silently stop
        # running if that precondition ever changes).
        b0 = fw[0]
        if b0["surv_kb"] != 23.0:  # (9216 + 14336) / 1024
            fails.append(f"week1 net-code {b0['surv_kb']} != 23.0")
        if b0["output_tok"] != 3000 or b0["read_tok"] != 300:
            fails.append(f"week1 token streams wrong: {b0}")

        # ---- (item 1) the fingerprint labels cache fills the pattern dims ----
        # A run WITHOUT a cache keeps the three pattern dims pending (asserted
        # above on out1). A run WITH a cache fills them from the modal rig label,
        # and a by_review_regime slice appears. The driver consumes the cache
        # deterministically (byte-identical across hash seeds).
        labels_path = os.path.join(tmp, "fingerprint-labels.json")
        build_labels(labels_path)
        out4 = os.path.join(tmp, "out4")
        rep4 = run_driver(snap, repo, frontier, out4, labels=labels_path)
        fpr4 = rep4.get("fingerprint") or {}
        if fpr4.get("review_regime") != "agentic review pass":
            fails.append(f"labels: review_regime should be modal 'agentic review "
                         f"pass', got {fpr4.get('review_regime')}")
        if fpr4.get("knowledge_practice") != "skills":
            fails.append(f"labels: knowledge_practice should be modal 'skills', "
                         f"got {fpr4.get('knowledge_practice')}")
        fine4 = (fpr4.get("orchestration_topology") or {}).get("fine")
        if fine4 != "orchestrator-workers":
            fails.append(f"labels: fine topology should be modal "
                         f"'orchestrator-workers', got {fine4}")
        if "review-regime" not in (fpr4.get("ingested_dimensions") or []):
            fails.append("labels: review-regime should join ingested_dimensions")
        byrr = (rep4.get("fuel_and_work") or {}).get("by_review_regime") or {}
        if "agentic review pass" not in byrr:
            fails.append(f"labels: by_review_regime slice missing regimes: "
                         f"{sorted(byrr)}")
        if not (rep4.get("fuel_and_work") or {}).get("by_knowledge_practice"):
            fails.append("labels: by_knowledge_practice slice missing")
        # determinism of the cache-consuming path: same inputs, different seed
        out5 = os.path.join(tmp, "out5")
        run_driver(snap, repo, frontier, out5, hashseed="7", labels=labels_path)
        for name in ("report.json", "report.html"):
            if open(os.path.join(out4, name), "rb").read() != \
               open(os.path.join(out5, name), "rb").read():
                fails.append(f"labels: {name} not byte-identical across seeds")

        # the chart artifact exists and carries both charts
        htmlp = os.path.join(out1, "report.html")
        if not os.path.exists(htmlp):
            fails.append("report.html was not written")
        else:
            hh = open(htmlp).read()
            if "<svg" not in hh or "durable shipped changes" not in hh:
                fails.append("report.html is not the expected chart")
            if "Fuel and work" not in hh:
                fails.append("report.html is missing the fuel-and-work small multiples")
            # the shareable card carries the wordmark and the number's precise unit
            # (in its tooltip); the lever (here the workflow/high tweak) is in the
            # detail below, not the card.
            if "VIBRANT" not in hh:
                fails.append("report.html is missing the VIBRANT wordmark")
            if "larger is better" not in hh:
                fails.append("report.html is missing the topline unit/reading")
            # the standalone "steepest move" lever was removed: the recommendation now
            # lives in the card as the interactive fingerprint's arrow + the in-card
            # recommendation line (driven by the metric toggles), so no separate lever.
            # the standalone efficiency-over-time chart was retired: the card's waveform
            # now carries the generations (per-era levels + daily bars), so a second chart
            # was redundant. It must be gone, and the card's waveform present instead.
            if "Efficiency over time" in hh:
                fails.append("report.html still carries the retired efficiency-over-time chart")
            if "The bold line is" in hh or "efficiency, not quality" in hh:
                fails.append("report.html still carries the cut explanatory paragraphs")
            # ---- (item 3) the slicer cuts by every fingerprint dimension, now
            # including the orchestrator->worker model-roles config as a first-class
            # arm (the same model reads differently as driver vs worker) ----
            for lbl in ("by orchestrator", "by worker", "by model roles", "by effort",
                        "by engine", "by routing", "by review regime",
                        "by knowledge practice"):
                if lbl not in hh:
                    fails.append(f"report.html slicer missing dimension group: {lbl}")
            # git-side work units join the page (as a table, not a fake time series)
            if "Surviving work by orchestrator" not in hh:
                fails.append("report.html missing the attribution (per-model work) table")
            # still self-contained: no external asset references
            if "src=" in hh or "<link" in hh or "http://" in hh or "https://" in hh:
                fails.append("report.html is not self-contained (external asset reference)")

        # ---- (3c) the measure loop: re-run with the first report as baseline ----
        out3 = os.path.join(tmp, "out3")
        rep3 = run_driver(snap, repo, frontier, out3,
                          baseline=os.path.join(out1, "report.json"))
        m = rep3.get("measure")
        if not m or m["actual_delta"] != 0.0:
            fails.append(f"measure loop: same inputs should show 0 move, got {m}")
        elif lever and m["lever_predicted_efficiency_delta"] != \
                lever["predicted_efficiency_delta"]:
            fails.append("measure loop did not carry the prior lever prediction")
        elif "different unit" not in (m.get("note") or ""):
            fails.append("measure loop should flag the prediction as a different unit")

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
        print("FAIL  vibrant_report:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  vibrant_report: vector, same-shape, provenance, determinism all hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
