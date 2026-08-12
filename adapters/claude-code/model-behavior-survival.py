#!/usr/bin/env python3
"""
Prototype: objective "wasted build" signal, code written and then provably
killed. Walks raw session transcripts, tracks characters written per file path
(Edit/Write, main loop + subagents), then detects kill events that target those
paths in the SAME session:

  rm / rm -rf <path>            git restore <path>
  git rm <path>                 git checkout -- <path> / git checkout <ref> <path>
  git reset --hard              git revert

A path is "killed" if a kill event names it (or, for repo-wide kills like
`git reset --hard` / `git revert`, all not-yet-committed writes in that session
are counted as at-risk). Attributed to the session's dominant assistant model.

This is a FLOOR, not the truth: it only catches deletion that happened inside a
captured session window. Code that was quietly abandoned (written, never
referenced again, never committed) or ripped out in a later rotated-away session
is invisible here. Reported as "provably-killed chars" so it never overclaims.
"""
import glob, json, os, re, sys
from collections import defaultdict, Counter

ROOT = os.path.expanduser("~/.claude/projects")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")

RM   = re.compile(r'\brm\s+(-[a-zA-Z]+\s+)*([^\s;&|]+)')
GRM  = re.compile(r'\bgit\s+rm\s+(-[a-zA-Z]+\s+)*([^\s;&|]+)')
GRES = re.compile(r'\bgit\s+(restore|checkout)\s+(--\s+)?([^\s;&|]+)')
HARD = re.compile(r'\bgit\s+reset\s+--hard\b')
REV  = re.compile(r'\bgit\s+revert\b')
COMMIT = re.compile(r'\bgit\s+commit\b')


def base(m): return (m or "").split("[")[0]


def blocks(msg):
    c = (msg or {}).get("content")
    return c if isinstance(c, list) else []


def dominant_model(path):
    c = Counter()
    try:
        for line in open(path):
            d = json.loads(line)
            if d.get("type") == "assistant" and not d.get("isSidechain"):
                m = base((d.get("message") or {}).get("model"))
                if m and m != "<synthetic>":
                    c[m] += 1
    except Exception:
        return None
    return c.most_common(1)[0][0] if c else None


def session_files(main_path):
    """All transcript files for a session: main + its subagents/**."""
    files = [main_path]
    sid = os.path.basename(main_path)[:-6]
    sub = os.path.join(os.path.dirname(main_path), sid, "subagents")
    if os.path.isdir(sub):
        files += glob.glob(os.path.join(sub, "**", "*.jsonl"), recursive=True)
    return files


def scan_session(main_path):
    """Return (born:dict[path]=chars, killed_chars, hard_or_revert_seen, committed)."""
    born = defaultdict(int)          # chars written per basename-ish key
    born_full = defaultdict(int)     # by full path token as seen
    killed = 0
    committed_any = False
    events = []  # (order, kind, arg)
    order = 0
    for f in session_files(main_path):
        try:
            fh = open(f)
        except Exception:
            continue
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            for b in blocks(d.get("message")):
                if b.get("type") == "tool_use":
                    order += 1
                    nm = b.get("name")
                    inp = b.get("input") or {}
                    if nm in EDIT_TOOLS:
                        p = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
                        txt = inp.get("content") or inp.get("new_string") or ""
                        if p:
                            born_full[p] += len(txt)
                            born[os.path.basename(p)] += len(txt)
                    elif nm == "Bash":
                        cmd = inp.get("command") or ""
                        if COMMIT.search(cmd):
                            committed_any = True
                        for rx, kind in ((GRM, "gitrm"), (RM, "rm"),
                                         (GRES, "restore")):
                            for mt in rx.finditer(cmd):
                                arg = mt.groups()[-1]
                                events.append((order, kind, arg))
                        if HARD.search(cmd):
                            events.append((order, "hard", None))
                        if REV.search(cmd):
                            events.append((order, "revert", None))
    # match kills to born paths
    killed_paths = set()
    repo_wipe = False
    for _o, kind, arg in events:
        if kind in ("hard", "revert"):
            repo_wipe = True
            continue
        if not arg:
            continue
        keyb = os.path.basename(arg.strip().strip('"').strip("'"))
        # match if any born path shares this basename
        if keyb in born:
            killed_paths.add(keyb)
        else:
            # arg might be a dir or glob; match born basenames whose full path contains arg
            for full in born_full:
                if arg.strip("'\"") in full:
                    killed_paths.add(os.path.basename(full))
    killed = sum(born.get(k, 0) for k in killed_paths)
    # repo_wipe (reset --hard / revert) with uncommitted writes: at-risk = all born
    at_risk = 0
    if repo_wipe and not committed_any:
        at_risk = sum(born.values())
    total_born = sum(born.values())
    return total_born, killed, at_risk, committed_any


def session_mtime(main_path):
    """Newest mtime across a session's transcript files (main + subagents).

    A new subagent transcript changes this, so the cache entry invalidates and
    the session is rescanned.
    """
    m = 0.0
    for f in session_files(main_path):
        try:
            m = max(m, os.path.getmtime(f))
        except OSError:
            continue
    return m


def per_session_survival(cache_path=None, verbose=False):
    """Compute {sid: (born_chars, killed_chars)} over ROOT, scanning each session once.

    This is the expensive transcript walk shared by the survival-join analyses
    (harness-efficiency, harness-modeleffect). Computing it here, with an
    optional on-disk cache keyed by (session id + newest transcript mtime),
    means the walk happens once and later tools reuse it: point every tool at
    the same `cache_path` (e.g. a file next to the snapshot) and the second run
    is near-instant. Only sessions whose transcripts changed are rescanned.

    Sessions with zero born chars are omitted from the return, but are still
    recorded in the cache so they are not rescanned next time.
    """
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                cache = json.load(f)
        except Exception:
            cache = {}
    out = {}
    new_cache = {}
    scanned = reused = 0
    for mp in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        sid = os.path.basename(mp)[:-6]
        mt = session_mtime(mp)
        ce = cache.get(sid)
        if ce and abs(ce.get("mtime", -1) - mt) < 1e-6:
            born, killed = ce.get("born", 0), ce.get("killed", 0)
            reused += 1
        else:
            born, killed, _at_risk, _committed = scan_session(mp)
            scanned += 1
        new_cache[sid] = {"mtime": mt, "born": born, "killed": killed}
        if born:
            out[sid] = (born, killed)
    if cache_path:
        try:
            tmp = cache_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(new_cache, f)
            os.replace(tmp, cache_path)
        except Exception:
            pass
    if verbose:
        print(f"  per-session survival: {len(out)} sessions with writes "
              f"({scanned} scanned, {reused} from cache)", file=sys.stderr)
    return out


def main():
    since = None
    if "--since" in sys.argv:
        since = sys.argv[sys.argv.index("--since") + 1]
    mains = [p for p in glob.glob(os.path.join(ROOT, "*", "*.jsonl"))]
    agg = defaultdict(lambda: Counter())
    n = 0
    for mp in mains:
        model = dominant_model(mp)
        if not model:
            continue
        born, killed, at_risk, committed = scan_session(mp)
        if born == 0:
            continue
        n += 1
        a = agg[model]
        a["sessions"] += 1
        a["born"] += born
        a["killed"] += killed
        a["at_risk"] += at_risk
        if killed or at_risk:
            a["sessions_with_kill"] += 1
    print(f"scanned {n} sessions with writes\n")
    hdr = f"{'model':22s}{'sess':>6}{'MB born':>10}{'killed%':>9}{'atrisk%':>9}{'kill-sess%':>11}"
    print(hdr); print("-" * len(hdr))
    for m in ["claude-fable-5", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5"]:
        a = agg.get(m)
        if not a:
            continue
        born = a["born"] or 1
        print(f"{m:22s}{a['sessions']:>6}{a['born']/1e6:>10.2f}"
              f"{100*a['killed']/born:>8.2f}%{100*a['at_risk']/born:>8.2f}%"
              f"{100*a['sessions_with_kill']/max(1,a['sessions']):>10.1f}%")


if __name__ == "__main__":
    main()
