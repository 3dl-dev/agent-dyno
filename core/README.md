# core, the harness-neutral numerator

`survival_git.py` computes horizon-survival from git alone: of the lines added in
a past window, what fraction are still alive at HEAD (still blamed to the adding
commit), bucketed by age, plus a fix/revert churn proxy.

```bash
python3 core/survival_git.py --repo /path/to/repo --since 30.days.ago
```

Because it reads the repository and not a transcript, it is identical for Claude
Code, pi, OpenCode, or a human. Git is the shared substrate, so **the unit of
shippable work is portable by construction.** No adapter is needed to run it.

Known limits (tracked, not hidden):
- fix/revert detection is commit-message-based (crude); true defect attribution
  (a fix touching recently-added lines) is a follow-on.
- blame is line-exact, so a cosmetic reformat resets blame and undercounts survival.
- repo-level until commits are mapped to sessions/harnesses for per-engine
  attribution, that mapping is what turns the numerator into a harness comparison.
