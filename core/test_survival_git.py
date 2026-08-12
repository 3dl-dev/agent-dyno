#!/usr/bin/env python3
"""
Acceptance test for survival_git (the spec made executable).

Builds a throwaway git repo with a known survival answer and checks the reference
build against it. Regenerate survival_git.py from survival_git.spec.md and this
test must still pass; that is what makes the code correct by construction.

    python3 core/test_survival_git.py      # exits 0 on pass, 1 on fail
Stdlib only. Needs git on PATH.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def git(repo, *a):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", repo, *a], env=env,
                          capture_output=True, text=True, check=True).stdout


def main():
    with tempfile.TemporaryDirectory() as repo:
        git(repo, "init", "-q")
        # commit A: add 10 lines
        path = os.path.join(repo, "f.txt")
        with open(path, "w") as fh:
            fh.write("\n".join(f"line{i}" for i in range(10)) + "\n")
        git(repo, "add", "f.txt")
        git(repo, "commit", "-q", "-m", "add ten lines")
        # commit B: delete 4 of them (pure deletion), leaving 6 alive
        with open(path, "w") as fh:
            fh.write("\n".join(f"line{i}" for i in range(6)) + "\n")
        git(repo, "commit", "-qam", "trim to six")

        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "survival_git.py"),
             "--repo", repo, "--since", "1.day.ago"],
            capture_output=True, text=True).stdout

        m = re.search(r"surviving at HEAD=(\d+).*?\(([\d.]+)%\)", out, re.S)
        assert m, f"could not find totals in output:\n{out}"
        surviving, pct = int(m.group(1)), float(m.group(2))

        # 10 added, 4 deleted, 6 survive -> 60%
        ok = surviving == 6 and abs(pct - 60.0) < 0.5
        if ok:
            print(f"PASS  survival_git: 10 added, 4 deleted -> {surviving} surviving, {pct}%")
            return 0
        print(f"FAIL  expected 6 surviving / 60%, got {surviving} / {pct}%\n\n{out}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
