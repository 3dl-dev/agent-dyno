---
name: vibrant-federate
description: Publish your anonymized Vibrant frontier over the live Nostr mesh, or start / view a team board, with no command line for you. You (the agent) mint the identity, produce the aggregate, sign it, publish it, and confirm it, all in this session. The operator only answers questions (which relay, which board); they never run a command or install anything. Use for "share my frontier live", "set up a team leaderboard", "publish to our Nostr board", or "view the team board".
argument-hint: [contribute | start-board | grant <member-pubkey> | view] [--relay <ws-url>] [--board <30301:owner:d>]
---

# Vibrant federate (live mesh, zero command line)

The operator never types a command. YOU run every step in this session with the Bash
tool. When a step needs a value only the operator has, a relay address, a board
coordinate, a member's key, ASK for that value in chat; never ask them to run anything.
Nothing is installed: the tools are Python 3 stdlib.

Read `docs/governance.md` and `docs/federation-nostr.md` first. This is the opt-in live
surface; the file path stays the default and is untouched. Only anonymized `summarize`
aggregates travel, never raw logs. No wallet, no chain.

## 0. Locate the tools and mint the identity (once)

The federation tools are `nostr_event.py` (sign), `relay_io.py` (publish/query over a
stdlib WebSocket), and `keys.py` (identity), from the `nostr-emit` repo. Find them at
`$NOSTR_EMIT` or `~/projects/nostr-emit` (a shipped skill bundles them alongside this
file). Then mint or load the operator's key, which is stored `0600` and reused:

```
NE=${NOSTR_EMIT:-~/projects/nostr-emit}
SK=$(python3 "$NE/keys.py" ensure)          # ~/.config/vibrant/nostr.key, minted if absent
PUB=$(python3 "$NE/keys.py" pub "$SK")
```

Report the short public key so the operator has an identity to share. Never print or ask
for the secret.

## 1. Pick the action

- **contribute** (default): publish the operator's frontier to a board.
- **start-board**: create a team board the operator owns.
- **grant <member-pubkey>**: as the owner, let a member contribute.
- **view**: fold a board and show the standings.

Resolve `--relay` (a `ws://`/`wss://` URL) and, for team actions, `--board`
(`30301:<owner-pub>:<d>`). If either is needed and not given, ASK for it. For a solo
publish with no relay, tell the operator the file path (`vibrant-contribute`) already
covers them and a relay is only for the live mesh.

## 2. contribute: publish the frontier

1. **Aggregate.** Take the operator's anonymized entries: prefer their `vibrant-report`
   result; otherwise run `python3 core/frontier.py summarize <frontier> --min-samples 1`
   and use `entries[]`. Confirm each carries no identity (governance gate); if the
   technique text would leak anything, rewrite it generically or drop it.
2. **Sign and publish each** (you run this, once per aggregate; `$AGG` is the compact JSON):
   ```
   python3 "$NE/nostr_event.py" --sec "$SK" --kind 30078 --content "$AGG" \
     --tag d="$ID" --tag t=vibrant-aggregate --tag engine="$ENGINE" \
     | python3 "$NE/relay_io.py" publish "$RELAY"
   ```
   A `{"ok": true}` line is success; on `false`, report the message, do not retry blindly.
3. **Confirm** with a query and show the operator what landed:
   ```
   python3 "$NE/relay_io.py" query "$RELAY" '{"kinds":[30078],"#t":["vibrant-aggregate"]}'
   ```
   Re-publishing the same shape UPDATES its event (addressable), it does not duplicate.
4. **Show it.** Present the folded standings as a small table you format from the query,
   and give the operator the viewer URL to open in a browser (a click, not a command):
   `leaderboard/vibrant.html?relay=<relay>` (add `&board=<coord>` for a team board).

## 3. start-board: an owner-rooted team frontier

The operator's key is the board's trust root. Create the board and self-grant, then hand
back the coordinate to share.

```
BOARD="30301:$PUB:$SLUG"                     # $SLUG e.g. "team"
python3 "$NE/nostr_event.py" --sec "$SK" --kind 30301 --content '{"name":"<team name>"}' \
  --tag d="$SLUG" | python3 "$NE/relay_io.py" publish "$RELAY"
python3 "$NE/nostr_event.py" --sec "$SK" --kind 39301 --content '' \
  --tag d="$PUB" --tag p="$PUB" --tag a="$BOARD" --tag role=contributor \
  | python3 "$NE/relay_io.py" publish "$RELAY"
```

Give the operator the board coordinate `$BOARD` and the relay to share with the team. Only
keys the owner grants can contribute; the viewer re-verifies, so the relay is never trusted
to gate writes.

## 4. grant / revoke: manage members (owner only)

To let member `$MPUB` contribute (or to remove them with `role=revoked`, latest wins):

```
python3 "$NE/nostr_event.py" --sec "$SK" --kind 39301 --content '' \
  --tag d="$MPUB" --tag p="$MPUB" --tag a="$BOARD" --tag role=contributor \
  | python3 "$NE/relay_io.py" publish "$RELAY"
```

Only the board owner's grants count. A member then runs the **contribute** action with the
board's relay; their rows appear once the owner has granted them.

## 5. view: fold a board

Query the board's grants and aggregates, derive the granted author set (owner plus
`contributor` grants, latest per grantee, `revoked` removed), keep only aggregates from
granted authors, and present the standings as a table. Or just hand the operator the viewer
URL `leaderboard/vibrant.html?relay=<relay>&board=<coord>`, which does the same fold in the
browser. Report the relay, the row count, and, for a board, that ungranted authors were
excluded.

## Rules

- The operator runs nothing. You run every command here; you only ASK for values (relay,
  board, member key) you cannot derive.
- Anonymized always: only `summarize` aggregates travel, identity and code never do.
- The file path is the default; the mesh is opt-in. Never publish without the operator
  choosing a relay.
- Honest failure: a relay `false` OK, an unreachable relay, or a missing tool is reported
  plainly, never faked into a pass.
