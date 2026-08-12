# Claims register

The field is full of confident claims about what makes an agent setup efficient.
This register turns each into a standing hypothesis with a metric and a verdict,
re-run every measurement window. A claim with no metric is a gap to close, not a
claim to ignore. Verdicts below are from one operator's Claude Code logs
(Jul–Aug 2026); they are illustrative, not universal — run it on your own.

## Efficiency claims

| # | Claim | Verdict (one operator) |
|---|---|---|
| C1 | Cost is O(reads) | **Confirmed** — reads ≈85% of spend, 5.6× generation |
| C2 | Reads grow super-linearly with context depth | **Supported** — read-$/turn ~13× higher at >400k vs ~75k context |
| C3 | Reads are 76–87% of cost at depth | **Matches** — ~85% at high context |
| C4 | Fan-out subagents each re-read the preamble cold | **Confirmed** — ~30–35k tok cold prefill per subagent; 38–66% never reach an edit |
| C5 | Sequential / pin-cheap beats wide parallel fan-out | **Partial** — widest-fanout engine is priciest per surviving-KB; clean test needs the dynamometer |
| C6 | Cross-family mid-session model switch repays full prefill | **Confirmed** — switch turn re-reads ~4× fresh input, cache −11pts |
| C7 | Solo strong model beats mixes on quality | **Supported** — solo lowest waste |
| C8 | Solo beats mixes on cost | **Supported** — solo cheapest per surviving-KB |
| C9 | Coordination overhead drives the mix's cost | **Refined** — the mix's cost is *waste*, not coordination |
| C10 | Orchestrator→cheap-worker is ~N× cheaper | **Refuted** on surviving work — same cost, more waste |
| C11 | The cold-read tax hits subagent delegation | **Not reproduced** — a subagent is its own cached context |
| C12 | Cross-model inefficiency is quality, not fuel | **Supported** |
| C13 | Model choice is second-order to harness | **Refuted** — output→surviving-code varies ~2× by model at fixed harness; the model×harness interaction is the largest term |
| C14 | Reasoning effort is constant/controlled | **Refuted** — it varies (high/max) and must be stratified, not pooled |

## Review-methodology claims (open — blocked on horizon-survival data)

The review debate is just more rows. Most cannot get a verdict until
horizon-survival accrues longitudinal data; flagged honestly, not skipped.

| # | Claim | Verdict |
|---|---|---|
| R1 | Manual-review-everything nets more horizon-survival than lighter regimes, once human fuel is counted | **Open** |
| R2 | "Nothing matters" (no review) survives at horizon as well as reviewed code | **Open** |
| R3 | Cross-model confirmation catches defects same-model review misses | **Open** |
| R4 | Sweeps / adversarial passes raise horizon-survival enough to justify their token cost | **Open** |
| R5 | Spec-driven / acceptance testing lowers the rebuild rate | **Open** |
| R6 | Self-declaration "rigor" proxies correlate with actual horizon-survival | **Open** — prior evidence says the proxy is gameable; horizon-survival is the check |

Contribute a verdict from your own data: run the report, and open a PR against
`frontier/reference-frontier.json` with your anonymized result.
