---
name: vibrant-federate
description: Share your anonymized efficiency result to a frontier and see how you compare, or set up a shared frontier for a team, with no command line and nothing to install. You (the agent) handle the identity, the publishing, and the grouping in this session; the operator only chooses what to share and with whom. Use for "share my result", "compare to others", "set up our team frontier", or "put my report on the web".
argument-hint: [share | start-team | add-member | view] [a group or host, optional]
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
stdlib WebSocket), and `keys.py` (identity). They are BUNDLED with this skill in the
`nostr-tools/` folder next to this file, so set `NE` to that folder (you know where you
loaded this skill from). A dev checkout may instead set `$NOSTR_EMIT` or use
`~/projects/nostr-emit`. Then mint or load the operator's key, stored `0600` and reused:

```
NE="<this skill's dir>/nostr-tools"          # bundled; or ${NOSTR_EMIT:-~/projects/nostr-emit}
SK=$(python3 "$NE/keys.py" ensure)           # ~/.config/vibrant/nostr.key, minted if absent
PUB=$(python3 "$NE/keys.py" pub "$SK")
```

Report the short public key so the operator has an identity to share. Never print or ask
for the secret.

## 1. Pick the action

- **contribute** (default): publish the operator's frontier to a board.
- **start-board**: create a team board the operator owns.
- **grant <member-pubkey>**: as the owner, let a member contribute.
- **view**: fold a board and show the standings.

Resolve `--relay` and `--board`, but DO NOT make the operator think about Nostr for the
common case. The public frontier has known defaults, so for "share to the public frontier"
just use them silently, never ask for a relay or a board:

- default relay `wss://relay.3dl.network`
- default board `30301:28e74283793831aa1563ef0ad0f21bbc8ca51f1e7b63ff71bd14a6b6fd0a31ee:public`

Only ask about a relay or board when the operator explicitly wants their OWN team frontier
(start-board, or a `--relay`/`--board` they supplied). Words like "npub", "relay", "kind",
and "event" should not appear in what you say unless the operator raised them first. For a
solo user with no interest in sharing, the file path (`vibrant-contribute`) already covers
them; the mesh is only for those who want it.

## 2. contribute: publish the frontier

1. **Aggregate.** Take the operator's anonymized entries: prefer their `vibrant-report`
   result; otherwise run `python3 core/frontier.py summarize <frontier> --min-samples 1`
   and use `entries[]`. Confirm each carries no identity (governance gate); if the
   technique text would leak anything, rewrite it generically or drop it.
2. **Sign and publish each** (you run this, once per aggregate; `$AGG` is the compact JSON).
   The Vibrant relay is open-write but proof-of-work gated, so mine the PoW with `--pow` (a few
   seconds, once; the operator never sees it). Content kinds (aggregate/report/board/grant) need
   it; follow lists do not:
   ```
   python3 "$NE/nostr_event.py" --sec "$SK" --kind 30078 --content "$AGG" \
     --tag d="$ID" --tag t=vibrant-aggregate --tag engine="$ENGINE" --pow 20 \
     | python3 "$NE/relay_io.py" publish "$RELAY"
   ```
   A `{"ok": true}` line is success; on `false` report the message (e.g. "insufficient
   proof-of-work" means raise `--pow` to the relay's floor), do not retry blindly.
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

## 5b. publish-report: your report on the web (hide the key)

Put the operator's OWN report online so they can open it at a link, without ever seeing or
typing a key. The identity rides in the URL fragment; you handle it, they just get a link.

1. **Render.** Use the HTML the `vibrant-report` skill produced (a full self-contained page).
2. **Consent on the two revealing fields.** The report carries absolute **spend and volume**
   ($ , sessions, output tokens) and **repo coverage names**, which the anonymized frontier
   aggregate strips. Publishing puts them on the web under the operator's key. Say that
   plainly and ask once. If they want them held back, render the metrics-only variant (ratios,
   no absolute $ or repo names); if that render flag does not exist yet, say so rather than
   publishing the full thing silently.
3. **Pack and publish** (you run this): gzip+base64 the HTML into one addressable event.
   ```
   PACKED=$(python3 -c "import gzip,base64,sys;print(base64.b64encode(gzip.compress(open(sys.argv[1],'rb').read(),9)).decode())" report.html)
   python3 "$NE/nostr_event.py" --sec "$SK" --kind 30079 --content "$PACKED" \
     --tag d=report --tag t=vibrant-report | python3 "$NE/relay_io.py" publish "$RELAY"
   ```
   Publishes to the operator's relay; a relay the operator can write to is required (the public
   frontier relay is curator-only, so a personal report needs the operator's own relay or a
   personal tenant, not the public one).
4. **Hand back the link, not the key.** `https://vibrant.3dl.dev/me#<pubkey>` (or `?relay=`
   plus the fragment for a non-default relay). Present it as "your report link"; never call it
   an npub or ask the operator to manage it. Re-publishing replaces it in place (addressable).

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
