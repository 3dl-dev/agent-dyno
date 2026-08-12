# frontier — the shared reference numbers

`reference-frontier.json` is the community-maintained set of efficiency vectors
that `dyno-tune` compares your engine against, so "am I near the state of the
art?" has an answer the collective owns rather than one a purse-holder hands
down.

## Contributing (opt-in, anonymized)

Run `dyno-report`, let it emit an anonymized summary, and open a PR adding it to
`reference-frontier.json`. An entry carries **only**:

- the harness and the engine fingerprint (engine class, model *roles* not
  identities where you prefer, effort, review regime),
- the efficiency vector,
- the survival horizon it was measured at, and the sample size,
- a date.

It carries **no** identity, no repo names, no code, no product information. That
is the governance line (`docs/governance.md`): the frontier compares engine
craft, never people, and never against product outcomes. Do not submit anyone
else's numbers, and never submit without explicit consent.

The seed entries below are from one operator's Claude Code logs, measured at the
same-session survival floor (Jul–Aug 2026). They are a starting point, not a
verdict. Better data — especially at day/week horizons — replaces them.
