# Getting started

Run Vibrant against your own data in a couple of minutes. Nothing is uploaded;
every command reads your local git and your local logs.

## 0. Fresh clone

```bash
git clone https://github.com/3dl-dev/vibrant
cd vibrant
```

Python 3, stdlib only. Nothing to install.

## 1. The numerator (fast, any repo, no adapter)

```bash
python3 core/survival_git.py --repo /path/to/any/repo --since 30.days.ago
```

You should see overall survival and a survival-by-age table. This works for code
written by any agent, model, or human, because it reads git, not a transcript.
Cost is one `git blame` pass over the files touched in the window: sub-second on a
small repo, up to a minute or two on a large, active one (hundreds of KLOC in the
window).

## 2. Freeze your fuel snapshot (Claude Code adapter, ~30-40s)

```bash
python3 adapters/claude-code/snapshot.py --out /tmp/vibrant
SNAP=$(ls -d /tmp/vibrant/*/ | tail -1)
```

Writes two small JSONL files (mb = turns/sessions, mc = code) under a dated dir.
This is your long-horizon fuel record: keep it. It holds only derived per-turn and
per-session metrics, no transcript text, so it stays a few megabytes even for a
large store (a few hundred sessions), versus the multi-GB raw logs it distills.

## 3. Fast reads (snapshot only, seconds)

```bash
python3 adapters/claude-code/harness-characterize.py "$SNAP"/mb-*.jsonl "$SNAP"/mc-*.jsonl
python3 adapters/claude-code/harness-readcost.py "$SNAP"/mb-*.jsonl
```

Engine classes and engine-vs-model entanglement, then whether your cost is
O(reads).

## 4. The survival join (first run walks your transcript store, then cached)

```bash
python3 adapters/claude-code/harness-efficiency.py "$SNAP"/mb-*.jsonl "$SNAP"/mc-*.jsonl
python3 adapters/claude-code/harness-modeleffect.py "$SNAP"
python3 core/horizon_attribute.py --repo /path/to/a/repo/you/code/in --snapshot "$SNAP" --since 30.days.ago
```

`harness-efficiency` and `harness-modeleffect` need per-session survival, which
comes from a one-time walk of your raw transcripts. The first of the two to run
does the walk and writes `survival-cache.json` next to your snapshot; the second
reuses it, so it returns in well under a second. The cache is keyed by session id
plus transcript mtime, so only sessions that changed are rescanned on later runs.

`horizon_attribute` does not walk transcripts; it reads the snapshot and does one
`git blame` pass, so its cost scales with the repo, not the transcript store. Note
its `--repo` must be a repo you have actually run sessions in: it matches commits
to sessions by project name, and prints "no sessions ... match" if none line up
(a brand-new clone with no session history will not match).

Rough timings on a ~2.8GB, ~300-session transcript store:

| step | time |
|------|------|
| `harness-efficiency` (first run, builds cache) | ~18s |
| `harness-modeleffect` (reuses cache) | <1s |
| either tool, re-run with warm cache | <1s |
| `horizon_attribute` (on a small/medium repo) | a few seconds to a minute, blame-bound |

Once you have a rendered report, `reading-the-report.md` walks the scorecard element by
element (the score, the three meters, the timeline generations, the map territories, the
coordination core, and the recommendation) and lists the external research the design draws
on.

## 5. Verify the build against its spec

```bash
python3 core/test_survival_git.py     # builds a fixture repo, asserts 60% survival
```

## 6. See a leaderboard

Open `leaderboard/vibrant.html` in a browser. It renders the seed frontier. Point it
at your own `frontier/reference-frontier.json` to see your own board.

## 7. Contribute (optional, federated)

Draft an anonymized entry for your frontier following
`skills/vibrant-contribute/SKILL.md`: the technique, the fingerprint, the vector, the
horizon, the proof tier. Append it to your own `frontier/reference-frontier.json`
for internal use, or open a PR against `3dl-dev/vibrant` to go public.

## Building history past ~30 days

A first run sees about a month, and it is worth knowing exactly which half of the
measurement is capped and which is not.

- **Surviving work (the numerator) is never capped.** It lives in git, which everyone
  keeps forever. `python3 core/survival_git.py --since 180.days.ago` gives you six
  months today, on a repo you have never snapshotted. The topline's numerator has as
  much history as your git log does.
- **The fuel and fingerprint side is what rotates.** Tokens, effort, and which engine
  ran come from the harness transcripts, and Claude Code prunes those after ~30 days.
  That is the only reason a fresh report's engine timeline stops at a month.

So to extend the *fuel* history, freeze it before it rotates. `snapshot.py` writes a
few kilobytes of derived metrics per run; keep those and your window grows. Run it on
a schedule, for example a weekly cron:

```bash
# crontab -e  ->  every Monday 9am, freeze the week before it rotates
0 9 * * 1  cd /path/to/vibrant && python3 adapters/claude-code/snapshot.py --out ~/.vibrant/snapshots
```

Each run drops a dated `~/.vibrant/snapshots/<date>-<host>/` directory. Keep them.
After a few months you have a continuous fuel record no rotation can erase.

To build one report across several retained snapshots, gather their `mb-*.jsonl` and
`mc-*.jsonl` into a single directory and point `--snapshot` there; the driver keys
sessions by id, so overlapping windows dedupe rather than double-count. The one piece
that does not simply concatenate is `survival-cache.json` (a JSON map, not JSONL): if
you want survival across the whole span, delete the stale caches and let the next
`harness-efficiency` run rebuild one over the combined transcripts it can still see.

## If something looks off

Open an issue at https://github.com/3dl-dev/vibrant/issues with the command
you ran, the output, and your setup. A number that surprises you is often the
interesting part, not a bug, so include what you expected too.
