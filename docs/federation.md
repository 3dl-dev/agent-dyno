# Federation and trust: run your own, share if you want

Agent Dyno has no central service and no signup. A leaderboard is a file you host,
so there is nothing to run and nobody to register with. Third Division Labs keeps
one public, curated frontier; anyone can keep their own for a project, team, or
company and share upward by hand. The design is many frontiers, not one central
board.

Be clear about what that means today. What ships is the file format, a viewer, the
`dyno-contribute` step, and the curated public frontier. The tree of frontiers is a
convention you run by hand, not a system that runs itself: see "Federation" below
for exactly what is automated and what is not.

## A frontier is just a file

A leaderboard is a `reference-frontier.json` plus something that renders it. That
is the whole architecture. You host the file wherever you already keep things: a
git repo, a gist, a shared drive, a pinned Slack message. There is no database and
no server to run.

- **Local / solo:** keep the file on your machine, view it with `leaderboard/dyno.html`
  pointed at it. Nothing leaves your box.
- **Team / company:** keep it in a private repo or shared location; your team
  writes their entries there and the viewer reflects your group.
- **Public:** Third Division Labs runs one public frontier at
  `3dl-dev/agent-dyno`. It is just another frontier, with no special status beyond
  being the shared one.

## Surfaces

One surface ships: the web viewer, `leaderboard/dyno.html`, which reads any
`reference-frontier.json` you point it at. Host your own copy.

Because a frontier is plain JSON, two more surfaces are a few lines you write, not
features we ship: post the standings to a Slack or Discord incoming webhook, or
print the table in a CI job. If those become common we may ship helpers; today they
are yours to wire.

## Federation: upward, opt-in, by hand

Frontiers form a tree only by choice, and today only by hand. Your entry stays in
your scope unless you move it up, and moving it up is one explicit action:

- to a team or org frontier: write to (or open a PR against) that frontier's file.
- to the public frontier: open a PR against `3dl-dev/agent-dyno`, curated by Third
  Division Labs.

Nothing auto-shares. `dyno-contribute` writes to your local frontier by default and
reaches a parent only when you tell it to. There is no automated rollup or subscribe
yet: a parent frontier is populated by its owner merging what they trust, and you
compare against a frontier by pointing the report at its file.

## Trust, kept simple on purpose

A leaderboard of self-reported numbers invites fakery, so headline claims must
*reproduce*. That converts "trust the claim" into "the claim is re-derivable," and
we lean only on things a developer already has. No keys, no wallet, no chain. A
heavy identity dependency would kill adoption, and adoption is the whole value.

Every entry carries a **proof tier**, shown on its face, so nobody mistakes a
self-report for a reproduced result:

- **Tier 0, sanity:** the entry passes basic bounds (survival in [0,100], tokens
  positive, ratios sane). Checked locally, automatic.
- **Tier 1, self-report:** an ordinary entry, taken on its word. Fine for entries
  that do not top the board.
- **Tier 2, git-verifiable:** references a public repo and commit SHAs, so anyone
  can re-run `survival_git` and confirm the surviving-work side.
- **Tier 3, reproduced:** the technique was re-run on a standard task suite with
  the dynamometer and the number held. Required to top a public frontier.

The sybil surface is small because the prize is small. This is engine craft and
self-improvement, with no money and no product-ranking, so manufacturing clout is
rarely worth it. Where identity matters, a GitHub PR carries a real, persistent
account and GitHub's own anti-abuse, at zero setup cost. Reproduction is the sybil
tax: faking many confirmed claims means paying for many real runs. Curation is the
frontier owner merging what they trust. That is enough at this size; a heavier
identity layer can come later only if adoption ever creates a reason for it.
