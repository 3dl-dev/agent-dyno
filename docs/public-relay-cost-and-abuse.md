# Ignition first: make sharing trivial, curate the view not the write

The thing to minimize is **sharing friction**, not write-abuse. This only ignites if anyone
can share their result in one step and immediately see themselves against a frontier. A
locked-down relay that nobody can publish to is not "unabusable", it is dead. Adoption is the
whole value; any control that makes sharing harder is the failure, not the win.

So the model is the opposite of an allowlist:

## Writes are open. Views are curated by following.

- **Anyone can publish their aggregate**, in one step, no grant and no admission. The skill
  signs and publishes it; the user just said "share my result". That is the ignition path and
  nothing may block it.
- **Spam never shows up because a view folds a follow-set, not the whole relay.** You see the
  frontier of the people (or teams) you follow. A spammer publishing garbage under a fresh key
  is simply not in anyone's follow-set, so it is invisible, no allowlist required. Curate the
  VIEW, not the WRITE. This is how Nostr handles spam, and it is why open writes are safe.
- **The public frontier is a growing curated follow-set**, seeded by 3dl and extended as real
  contributors appear, not a write gate. Being "on the public board" means being followed into
  the public set, which a curator does after a glance, while the contributor already sees their
  own number immediately.

## Grouping is following: individual, team, company, all the same mechanism

A group is just which follow-set a view folds:

- **Individual:** fold yourself. You see your own frontier the instant you share.
- **Team:** fold the team's follow-set (you and your teammates).
- **Company:** fold the company follow-set.
- **Public:** fold the public curated set.

Public or private **relay** is an orthogonal transport choice, not the grouping. A private team
can run its own relay (see the hoistable relay) or share a public one; either way the group is
defined by who they follow, not by who a relay admits. One mechanism, arbitrary grouping.

## None of this vocabulary reaches the user

Nobody cares about npubs, relays, follows, or kinds. The user says "share my result", "show my
team", "show the public frontier". The skill does the keys, the publish, the follow-set, and
the fold. The words npub / relay / follow / event / kind never appear unless the user raises
them first. Leaking nostrism is itself friction, and friction is the enemy here.

## Keeping cost bounded WITHOUT adding friction

Open writes must not mean an open bill or a spam dump. Bound it with measures a real sharer
never feels:

- **Addressable events:** one aggregate per shape per author, REPLACED not appended. Sharing
  ten times a day still costs one event's storage. Per-author footprint is bounded by
  construction, however open the relay.
- **A tiny proof-of-work on publish (NIP-13):** a couple of seconds of the sharer's own CPU,
  once, invisible in a skill flow, but it prices a flood out of existence. This replaces the
  allowlist as the anti-flood gate and costs the honest user nothing they notice.
- **Reads:** open, fronted by an edge rate-limit (Front Door) and a hard Cosmos RU/budget
  ceiling, so a read flood degrades to bounded 429s, never an open bill. The dataset a view
  folds is tiny (a follow-set of latest-per-shape events), so normal reads are cheap.
- **Personal reports** (the larger `/me` payload) still do not belong on a shared public tenant
  un-gated: they go to the user's own relay (hoistable) or a per-key-limited personal tenant.
  But that path is also one step for the user, the skill hands them the link.

## What this corrects

The earlier version of this note treated curator-only writes as the anti-abuse win. That was
backwards: it minimized abuse by minimizing sharing, which minimizes the whole project. The
right target is trivial sharing plus a curated view, with cost bounded by addressable events, a
seconds-long proof-of-work, and edge/RU ceilings, none of which the person sharing ever feels.

## Checklist

- [ ] Writes: OPEN on the public tenant (drop the participation allowlist), gated only by a
      small NIP-13 proof-of-work and addressable-replace, so sharing is one step.
- [ ] Views fold a follow-set (individual / team / company / public), so spam is invisible
      without blocking writes.
- [ ] Public frontier = a seeded, growing curated follow-set, extended by a curator glance,
      never a precondition to publish.
- [ ] Reads: edge rate-limit + hard Cosmos RU/budget ceiling (bounded 429s under flood).
- [ ] The skill hides all of it: "share my result" / "my team" / "the public frontier", never
      npub / relay / follow / kind.
- [ ] Personal `/me` reports: own-relay or a per-key personal tenant, still one step to share.
