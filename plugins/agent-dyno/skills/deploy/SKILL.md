---
name: deploy
description: "Set up and run Agent Dyno: measure the token-efficiency of your AI coding setup from your own logs and git history, harness-neutral, on your machine. Self-extracts a verified harness, then sets it up and grades. Nothing uploaded."
---

# This skill sets agent-dyno up before it reports agent-dyno is up

You are about to bring **agent-dyno** up from a *recipe*, not from a finished instance. The
skill ships agent-dyno as source: a carried recipe plus the pin to the code that runs it, like
a self-extracting archive that carries both its contents and the unpacker. Before you tell
anyone agent-dyno is running, deploy it against **this** target and GRADE it honestly. You do
the work in-loop; nobody runs a command line. The material is the carried recipe, the
binds, the checks, and the acceptance in the sections below.

Two roles run through this. The **author** packaged agent-dyno as this skill on their machine.
The **receiver** is whoever installs it, a different target, whose substrate, secrets, and
paths you resolve here. You work so the receiver reaches a real, graded agent-dyno, or an honest
reason it could not, never a silent success.

## Recipe (run before your first report that agent-dyno is up)

1. **Cache / idempotency.** If agent-dyno is already up on this target in this session (a prior
   graded namespace exists, or a resolution is recorded here), reuse it, emit the Reusing
   line, and skip to step 6. Do not re-deploy over a live instance.

2. **Resolve the binds.** For each entry in the binds section, probe this target for the
   matching capability, and resolve the isolation substrate to the required strength the
   carried recipe names. If a *required* bind has no match here, or no substrate meets the
   required strength, STOP, deploy nothing, and report cannot-build naming the missing one.
   Never guess and never substitute. If you cannot positively confirm a required bind,
   treat it as missing.

3. **Self-extract the runtime (the bootstrap).** The carried recipe carries a pin under
   `operators` (`version`, `url`, `sha256`), but the code that runs the deploy lives
   *inside* that kit, so you unpack it yourself first, and only after verifying it. Do
   exactly this: (a) fetch the tarball at the pin `url`; (b) compute its sha256 and confirm
   it equals the pin's `sha256`, if it does not, STOP and report cannot-build (tampered or
   wrong kit), and never unpack or run an unverified tarball; (c) extract the verified
   tarball, that unpack IS the self-extraction, and it yields the runtime: `hoist/pins.py`
   (fetch and verify), `envelope/` (the enforced grader: isolation, honest grade,
   teardown), and the operator steps. From here the extracted runtime drives the graded
   pass and re-verifies the kit into its cache. Because you checked the sha256 by hand
   before unpacking, nothing unverified executes.

4. **Know early, then deploy.** Run the pre-check first, it deploys nothing. If it says
   cannot-build, stop at the door and give the user the named reason. Otherwise run the
   full graded pass through the extracted grader, which *enforces* the invariants: a
   runner-owned isolated namespace (non-destructive), and teardown. You never re-run
   agent-dyno's own singular deployment onto a live host.

5. **Grade.** The acceptance checks rebuild on THIS target. Compute the honest transfer
   score, how many of the acceptance checks passed, N of M, and name every check that did
   not transfer.

6. **Report** the outcome in one line, using one of the templates below. Never let a design
   read as a running system; if it did not transfer, say what did not.

7. **Hand off.** Point the user at any follow-up the carried recipe includes (how to
   extend it, operate it, or keep it running), so they can use agent-dyno, not merely have it
   installed.

Before your first report, state in one line what happened, only one line, and do not
narrate the loop, using one of these templates:
- "Built agent-dyno. Acceptance transferred N of M on this target. Ready."
- "Built agent-dyno, but N of M acceptance checks did not transfer here: [the specific checks]."
- "Cannot build agent-dyno: this target is missing [the named bind or substrate strength]."
- "Reusing the agent-dyno setup from earlier this session. Ready."

The failure to avoid: reporting agent-dyno is up because the recipe *looks* right. It is up only
when it deployed and its acceptance transferred on this target. Grade it, then report what
you measured.

## The carried recipe (the authority; the operators pin travels with it)

```json
{
  "_comment": "Agent Dyno's Layer 2 recipe: what 'install and run agent-dyno' means. The distributable marketplace under plugins/agent-dyno is scaffolded from this by the hoistable build tool (/hoistable:build); the compiled skill carries this recipe inlined and self-pinning. source.clone names the public home (local grading overrides it). Nothing of the harness is repo'd; it is pinned by URL.",
  "app": "agent-dyno",
  "binds": [
    {
      "name": "git",
      "probe": "git --version",
      "required": true
    },
    {
      "name": "python3",
      "probe": "python3 --version",
      "required": true
    }
  ],
  "default_profile": "default",
  "operators": {
    "sha256": "93c02cedd7bd66a8afcfdd547fc95bb830fe6ce1699ca009917f8551b4200ad5",
    "url": "https://github.com/3dl-dev/hoistable/releases/download/operators-v0.5.0/hoistable-operators-0.5.0.tgz",
    "version": "0.5.0"
  },
  "profiles": {
    "default": {
      "acceptance": [
        {
          "check": "python3 core/test_survival_git.py",
          "name": "numerator-selftest"
        },
        {
          "check": "python3 skills/dyno-report/test_dyno_report.py",
          "name": "driver-selftest"
        },
        {
          "check": "python3 adapters/claude-code/fingerprint_evidence.py --selftest",
          "name": "evidence-selftest"
        },
        {
          "check": "python3 skills/dyno-report/demo.py --selftest",
          "name": "demo-render-selftest"
        },
        {
          "check": "grep -q 'functionality per Mtok' .hoist-report/report.html",
          "name": "report-has-topline"
        },
        {
          "check": "grep -q '<svg' .hoist-report/report.html",
          "name": "report-is-a-chart"
        }
      ],
      "bringup": [
        {
          "name": "render-demo-report",
          "run": "python3 skills/dyno-report/demo.py --out .hoist-report"
        }
      ],
      "health": [
        {
          "check": "test -f .hoist-report/report.json",
          "name": "report-json-written"
        },
        {
          "check": "test -f .hoist-report/report.html",
          "name": "report-html-written"
        }
      ],
      "isolation": {
        "none": true,
        "why": "hermetic: everything runs inside a throwaway clone. demo.py fabricates its own synthetic snapshot and a throwaway git repo under .hoist-report/_demo and renders the report there; it starts no daemons, binds no host ports, and writes no state outside the clone. Nothing leaves the machine."
      },
      "preflight": [
        {
          "name": "python>=3.8",
          "probe": "python3 -c \"import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)\"",
          "required": true
        }
      ]
    }
  },
  "source": {
    "clone": "https://github.com/3dl-dev/agent-dyno",
    "dir": "agent-dyno"
  }
}
```

## Binds (resolve these on the target; a missing required one is cannot-build)

- `git` (required), probe: `git --version`
- `python3` (required), probe: `python3 --version`
- isolation substrate: none required, this profile is hermetic (hermetic: everything runs inside a throwaway clone. demo.py fabricates its own synthetic snapshot and a throwaway git repo under .hoist-report/_demo and renders the report there; it starts no daemons, binds no host ports, and writes no state outside the clone. Nothing leaves the machine.).

## Checks (invariants every deploy obeys)

- **Non-destructive.** The deploy lands in a runner-owned isolated namespace (its own name, ports, storage); a profile that declares no isolation is refused; teardown always runs. It never re-runs agent-dyno's own singular deployment onto a live host.
- **No silent success.** agent-dyno is graded on the real target; a run that cannot say it worked says what did not transfer. A design never reads as a running system.
- **Verified runtime.** The fetched kit is run only after its sha256 matches the carried pin; a tampered or unreachable kit is cannot-build, named.

## Acceptance (the held-back transfer test; the honest score)

- `numerator-selftest`: `python3 core/test_survival_git.py`
- `driver-selftest`: `python3 skills/dyno-report/test_dyno_report.py`
- `evidence-selftest`: `python3 adapters/claude-code/fingerprint_evidence.py --selftest`
- `demo-render-selftest`: `python3 skills/dyno-report/demo.py --selftest`
- `report-has-topline`: `grep -q 'functionality per Mtok' .hoist-report/report.html`
- `report-is-a-chart`: `grep -q '<svg' .hoist-report/report.html`
