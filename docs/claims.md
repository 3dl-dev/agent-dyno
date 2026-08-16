# Claims register

The field is full of confident claims about what makes an agent setup efficient.
This register turns each into a standing hypothesis with a metric and a verdict,
re-run every measurement window. A claim with no metric is a gap to close, not a
claim to ignore. Verdicts below are from one operator's Claude Code logs
(Jul–Aug 2026); they are illustrative, not universal, run it on your own.

## Efficiency claims

| # | Claim | Verdict (one operator) |
|---|---|---|
| C1 | Cost is O(reads) | **Confirmed**, reads ≈85% of spend, 5.6× generation |
| C2 | Reads grow super-linearly with context depth | **Supported**, read-$/turn ~13× higher at >400k vs ~75k context |
| C3 | Reads are 76–87% of cost at depth | **Matches**, ~85% at high context |
| C4 | Fan-out subagents each re-read the preamble cold | **Confirmed**, ~30–35k tok cold prefill per subagent; 38–66% never reach an edit |
| C5 | Sequential / pin-cheap beats wide parallel fan-out | **Partial**, widest-fanout engine is priciest per surviving-KB; clean test needs the dynamometer |
| C6 | Cross-family mid-session model switch repays full prefill | **Confirmed**, switch turn re-reads ~4× fresh input, cache −11pts |
| C7 | Solo strong model beats mixes on quality | **Supported**, solo lowest waste |
| C8 | Solo beats mixes on cost | **Supported**, solo cheapest per surviving-KB |
| C9 | Coordination overhead drives the mix's cost | **Refined**, the mix's cost is *waste*, not coordination |
| C10 | Orchestrator→cheap-worker is ~N× cheaper | **Refuted** on surviving work, same cost, more waste |
| C11 | The cold-read tax hits subagent delegation | **Not reproduced**, a subagent is its own cached context |
| C12 | Cross-model inefficiency is quality, not fuel | **Supported** |
| C13 | Model choice is second-order to harness | **Refuted**, output→surviving-code varies ~2× by model at fixed harness; the model×harness interaction is the largest term |
| C14 | Reasoning effort is constant/controlled | **Refuted**, it varies (high/max) and must be stratified, not pooled |

## Review-methodology claims (open, blocked on horizon-survival data)

The review debate is just more rows. Most cannot get a verdict until
horizon-survival accrues longitudinal data; flagged honestly, not skipped.

| # | Claim | Verdict |
|---|---|---|
| R1 | Manual-review-everything nets more horizon-survival than lighter regimes, once human fuel is counted | **Open** |
| R2 | "Nothing matters" (no review) survives at horizon as well as reviewed code | **Open** |
| R3 | Cross-model confirmation catches defects same-model review misses | **Open** |
| R4 | Sweeps / adversarial passes raise horizon-survival enough to justify their token cost | **Open** |
| R5 | Spec-driven / acceptance testing lowers the rebuild rate | **Open** |
| R6 | Self-declaration "rigor" proxies correlate with actual horizon-survival | **Open**, prior evidence says the proxy is gameable; horizon-survival is the check |

Contribute a verdict from your own data: run the report, and open a PR against
`frontier/reference-frontier.json` with your anonymized result.

## Metric definition: simplicity (updated 2026-08-16)

Simplicity is a STOCK measure of the surviving code's complexity DENSITY, not the
inverse of bloat. Definition:

    density    = net decision points per 1000 SURVIVING lines (numerator.complexity_per_1k_lines)
    simplicity = 100 * e^(-density / 100)      # 0..100, higher = simpler; half-point ~69/1000 lines

Attributed per config (net_complexity / surviving lines of that rig) and per period
(net-surviving lines of that bucket). See `_density_simplicity` / `_surviving_lines`.

Why density, not `100 - bloat` (the earlier definition):

- bloat = decision points per shipped CHANGE (a per-change flow). It is blind to code
  density: two configs with the same bloat can differ ~7x in how tightly their surviving
  code is branched. `100 - bloat` therefore does not measure the simplicity of the code.
- bloat, like efficiency (changes per Mtok), rewards making MORE, smaller changes, so its
  inverse shared efficiency's salami-slicing pathology and carried little new signal.
- density is orthogonal AND counterbalanced by efficiency: the only way to game low density
  is to pad lines, which costs output tokens and lowers efficiency. So the two axes
  self-correct. bloat is retained as a separate change-discipline meter, not as simplicity.

## External hypotheses: cost/intelligence guidance (to test on your own data)

Source: Anthropic, "Optimizing for cost and intelligence" (platform.claude.com, Jul-Aug
2026). These are the doc's measured findings, framed as claims to verify against YOUR
git-survival data, not truths adopted. They stay model/harness-neutral: the numbers are
Anthropic's benchmarks and will drift; the shape is what we test.

| # | Claim | Verdict |
|---|---|---|
| X1 | A more capable model costs LESS per unit of surviving work despite a higher per-token price (it backtracks/re-reads less). Vibrant's efficiency axis already exposes this | **Open**, testable now (compare eff by orchestrator tier) |
| X2 | "Free wins" (cache hygiene, context/token trimming) are a larger efficiency lever than model or effort choice. Sessions already carry cache_r / cache_w | **Open**, needs the fuel-line decomposition below |
| X3 | The reasoning-effort curve is often flat: lower effort gives up little and can beat an architecture change. Effort is a fingerprint axis already | **Open**, testable (eff/simp/flow by effort, holding rig) |
| X4 | Cost concentrates in the TAIL: the hardest ~10% of tasks carry a large share of spend, and the tail (not the median) decides the setup | **Open**, needs a tail view over per-session cost |

## Numerator stability: count vs continuous (measured 2026-08-16)

| # | Claim | Verdict |
|---|---|---|
| X5 | A CONTINUOUS surviving-work numerator (surviving decision points per Mtok) is a stabler, more convention-neutral efficiency measure than counting durable changes | **Supported so far** on the reference corpus, pending more federated data |

Evidence (15 configs, one corpus): counting durable changes ranks configs quite
differently from continuous surviving work (Spearman 0.586 vs the complexity numerator,
0.364 vs the surviving-lines numerator), while the two continuous variants agree (0.807).
The divergence is diagnostic: `fable-5 -> haiku-4-5` ranks 3rd by change-COUNT (one lucky
commit over tiny tokens) but near-bottom by continuous surviving work (4 decision points,
24 surviving lines that stuck). Counting units is fragile to commit/PR granularity and to
tiny-sample lucky units; the continuous measure is blind to how work was chopped into
sessions/commits/PRs, so it survives unseen data better. `eq_continuous` (topline) and
`eff_cont` (per config) are now carried in parallel with the count numerator so the
frontier accumulates both and the switch can be made on evidence, not assertion.
