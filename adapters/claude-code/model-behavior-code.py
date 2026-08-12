#!/usr/bin/env python3
"""
Coding-activity extractor, per session, split into orchestrator (main loop) and
worker (subagent) counters, attributed to the model that drove the session.

    python3 model-behavior-code.py --out ~/model-code-$(hostname).jsonl

One record per session:
  {"k":"code","sess":..,"proj":..,"model":..,"orch":{..},"work":{..},"nsub":N}

Counters (both sides): calls, edits, edit_chars, bash, test_runs, build_runs,
git_ops, commits, reverts, reads, errors, err_Edit, err_Bash, uniq_files, refile.

Pairs with model-behavior.py; both feed model-behavior-metrics.py.
"""
import argparse
import glob
import json
import os
import re
import socket
from collections import Counter

TESTRX = re.compile(r'\b(pytest|go test|npm (run )?test|yarn test|cargo test|make test|'
                    r'jest|vitest|tox|unittest|rspec|dotnet test|ctest|bats)\b')
BUILDRX = re.compile(r'\b(go build|cargo build|npm run build|make\b|tsc\b|mvn|gradle|docker build)\b')
GITRX = re.compile(r'\bgit (commit|push|revert|reset)\b')
EDIT_TOOLS = ('Edit', 'Write', 'NotebookEdit')


def blank():
    return Counter()


def scan(paths, main_thread_only, acc, files, by_model=None):
    """Accumulate tool activity from a list of transcript files.

    `by_model`, if given, is a dict[model] -> Counter that additionally
    receives the same in_tok/cache_w_tok/cache_r_tok/out_tok breakdown,
    split by the assistant model that produced each message.
    """
    tid = {}
    for p in paths:
        for line in open(p, errors='replace'):
            if '"type"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get('type')
            if t == 'assistant':
                if main_thread_only and d.get('isSidechain'):
                    continue
                m = d.get('message') or {}
                mm = m.get('model')
                if mm == '<synthetic>':
                    continue
                u = m.get('usage') or {}
                acc['in_tok'] += u.get('input_tokens') or 0
                acc['cache_w_tok'] += u.get('cache_creation_input_tokens') or 0
                acc['cache_r_tok'] += u.get('cache_read_input_tokens') or 0
                acc['out_tok'] += u.get('output_tokens') or 0
                if by_model is not None and mm:
                    bm = by_model.setdefault(mm, Counter())
                    bm['in_tok'] += u.get('input_tokens') or 0
                    bm['cache_w_tok'] += u.get('cache_creation_input_tokens') or 0
                    bm['cache_r_tok'] += u.get('cache_read_input_tokens') or 0
                    bm['out_tok'] += u.get('output_tokens') or 0
                for b in (m.get('content') or []):
                    if not isinstance(b, dict) or b.get('type') != 'tool_use':
                        continue
                    nm = b.get('name')
                    inp = b.get('input') or {}
                    tid[b.get('id')] = nm
                    acc['calls'] += 1
                    if nm in EDIT_TOOLS:
                        acc['edits'] += 1
                        fp = inp.get('file_path')
                        if fp:
                            files[fp] += 1
                        acc['edit_chars'] += len(inp.get('new_string') or inp.get('content') or '')
                    elif nm == 'Bash':
                        acc['bash'] += 1
                        c = inp.get('command') or ''
                        if TESTRX.search(c):
                            acc['test_runs'] += 1
                        if BUILDRX.search(c):
                            acc['build_runs'] += 1
                        if GITRX.search(c):
                            acc['git_ops'] += 1
                        if re.search(r'\bgit commit\b', c):
                            acc['commits'] += 1
                        if re.search(r'\bgit (revert|reset --hard)\b', c):
                            acc['reverts'] += 1
                    elif nm == 'Read':
                        acc['reads'] += 1
            elif t == 'user':
                if main_thread_only and d.get('isSidechain'):
                    continue
                c = (d.get('message') or {}).get('content')
                if not isinstance(c, list):
                    continue
                for b in c:
                    if not isinstance(b, dict) or b.get('type') != 'tool_result':
                        continue
                    nm = tid.get(b.get('tool_use_id'))
                    if not nm:
                        continue
                    txt = b.get('content')
                    if isinstance(txt, list):
                        txt = ' '.join(x.get('text', '') for x in txt if isinstance(x, dict))
                    txt = txt if isinstance(txt, str) else ''
                    if (b.get('is_error') or txt.startswith('Error:')
                            or 'String to replace not found' in txt
                            or 'has not been read yet' in txt):
                        acc['errors'] += 1
                        if nm in ('Edit', 'Write'):
                            acc['err_Edit'] += 1
                        elif nm == 'Bash':
                            acc['err_Bash'] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    host = socket.gethostname()
    outp = a.out or os.path.expanduser(f"~/model-code-{host}.jsonl")
    n = 0
    with open(outp, "w") as out:
        for p in sorted(glob.glob(os.path.join(a.root, "*", "*.jsonl"))):
            proj = re.sub(r"-home-[^-]+-projects-", "", os.path.basename(os.path.dirname(p)))
            sid = os.path.basename(p)[:-6]
            models = Counter()
            day = None
            for line in open(p, errors='replace'):
                if '"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('type') != 'assistant' or d.get('isSidechain'):
                    continue
                mm = (d.get('message') or {}).get('model')
                if mm and mm != '<synthetic>':
                    models[mm] += 1
                    day = day or (d.get("timestamp") or "")[:10]
            if not models:
                continue
            orch, of = blank(), Counter()
            orch_by_model = {}
            scan([p], True, orch, of, orch_by_model)
            subs = glob.glob(p[:-6] + '/subagents/**/*.jsonl', recursive=True)
            work, wf = blank(), Counter()
            work_by_model = {}
            scan(subs, False, work, wf, work_by_model)
            for acc, f in ((orch, of), (work, wf)):
                acc['uniq_files'] = len(f)
                acc['refile'] = sum(v - 1 for v in f.values() if v > 1)
            out.write(json.dumps(dict(k="code", host=host, sess=sid, proj=proj, day=day,
                                      model=models.most_common(1)[0][0], nsub=len(subs),
                                      orch=dict(orch), work=dict(work),
                                      orch_by_model={m: dict(c) for m, c in orch_by_model.items()},
                                      work_by_model={m: dict(c) for m, c in work_by_model.items()}),
                                 separators=(",", ":")) + "\n")
            n += 1
    print(f"host={host} sessions={n} out={outp}")


if __name__ == "__main__":
    main()
