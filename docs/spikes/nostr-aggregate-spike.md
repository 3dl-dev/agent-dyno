# Spike: aggregate-as-Nostr-event, end to end

Scope for the smallest honest proof of `federation-nostr.md`. This is a SPIKE: throwaway,
time-boxed, meant to derisk the path, not to ship. It proves one thing: a Vibrant
`summarize` aggregate can travel as an addressable Nostr event and be folded by the
leaderboard, with no encryption, no keys ceremony, and no group machinery.

## Goal

Point `leaderboard/vibrant.html` at a relay instead of a file, and have it render the same
board by folding aggregate events. Publishing a new aggregate makes a new row appear;
re-publishing the same shape UPDATES its row (latest-wins), it does not duplicate.

## Non-goals (explicitly out, do not build)

- No encryption / CEK / NIP-44. Aggregates are anonymized and public by design.
- No real identity: a throwaway key is fine. No board, no role grants, no owner-rooted trust.
- No relay-as-source-of-truth: the file path stays the default and is untouched.
- No production relay change: run against a scratch relay, not moot.pub's allowlist.
- No signer or WebSocket client added to the repo: `nak` publishes; only the read path is ours.

## The three pieces

### 1. Payload: the aggregate we already produce

`core/frontier.py summarize` already emits one anonymized object per rig shape (id, harness,
engine, effort, model_roles, vector, samples, proof, date, `aggregate: true`), with a
k-anonymity floor and nothing identifying (`core/frontier.py:106`). That object IS the event
content. No new producer code: run `summarize` and take its `entries`.

### 2. Event format: addressable, latest-wins per shape

One NIP-78 app-specific event per aggregate, parameterized-replaceable so `(author, kind,
d-tag)` dedupes to the latest:

- `kind`: `30078` (app-specific, parameterized-replaceable).
- `content`: the summarize object, JSON.
- tags:
  - `["d", "<summary id>"]`  -> the addressable key; republish of a shape replaces its event.
  - `["t", "vibrant-aggregate"]`  -> the REQ filter the leaderboard subscribes to.
  - `["harness", ...]`, `["engine", ...]`, `["horizon", ...]`  -> plaintext routing tags,
    mirroring the envelope-split lesson (routing tags stay queryable even though, here,
    nothing is secret).

Publish with `nak` and a throwaway key (the sibling repos already cross-check against `nak`,
so it is the trusted reference publisher):

```
KEY=$(nak key generate)
python3 core/frontier.py summarize frontier/reference-frontier.json --min-samples 1 \
  | jq -c '.entries[]' \
  | while read -r agg; do
      id=$(jq -r .id <<<"$agg")
      nak event -k 30078 --sec "$KEY" \
        -t d="$id" -t t=vibrant-aggregate \
        -t harness="$(jq -r .harness <<<"$agg")" -t engine="$(jq -r .engine <<<"$agg")" \
        -c "$agg" "$RELAY"
    done
```

(`summarize`'s CLI already streams the aggregate JSON to stdout when `--out` is omitted
(`core/frontier.py:202`, verified), so no producer change is needed. `jq`/`nak` are spike
tools, not repo deps.)

### 3. Read path: fold the relay in the leaderboard (the only code we write)

Add one additive function to `leaderboard/vibrant.html`. The current tail is:

```
fetch("../frontier/reference-frontier.json").then(r=>r.ok?r.json():Promise.reject())
  .then(render).catch(()=>render(SEED));               // vibrant.html:133
```

Gate a relay fold behind a `?relay=<wss-url>` query param so the default file path is
untouched:

```
const relay = new URLSearchParams(location.search).get("relay");
if (relay) foldRelay(relay).then(render).catch(()=>render(SEED));
else fetch("../frontier/reference-frontier.json")...   // unchanged
```

`foldRelay(url)`: open a WebSocket, send `["REQ","s",{"kinds":[30078],"#t":["vibrant-aggregate"]}]`,
collect each `["EVENT","s",ev]` by parsing `ev.content` into an entry, and on `["EOSE",...]`
close and resolve `{entries}`. Addressability means the relay already returns only the latest
event per shape, so no client-side dedup is needed. About 30 lines, no library.

## Acceptance

1. With a scratch relay seeded by the publish loop, opening `vibrant.html?relay=<url>` renders
   the SAME three rows as the file path (solo / delegate / workflow), from folded events.
2. Publishing a fourth aggregate (any shape) makes a fourth row appear on reload, with no
   code change.
3. Re-publishing an existing shape (edited vector) UPDATES that row, it does not add a
   duplicate. This is the addressability proof: the whole point.
4. The default `vibrant.html` (no `?relay=`) is byte-for-byte unchanged in behavior.

## Relay for the spike

Local `strfry` (dumb, no auth) is the least-friction target; a throwaway public relay also
works. Pointing at moot.pub / `3dl.network` is a one-line allowlist add for the throwaway
npub, deferred out of the spike so no production surface is touched. Note the sibling lesson:
allowlisted relays that never send AUTH hang a client that waits for a challenge, so the fold
must not block on NIP-42 (`dontguess/docs/design/nostr-first-client-ed2.md`).

## What it derisks (why it is worth doing)

- The aggregate round-trips as an event and the REQ filter selects it (payload + tag design).
- Addressability delivers latest-wins-per-shape for free, so the fold is a plain map, not a
  reconciliation engine.
- A browser fold is effectively instant at our scale (sibling measurement: 15-60ms warm,
  load is tens/minute, `nostr-relay/docs/feasibility-stateless-core.md`).

## What it deliberately leaves unproven (the next spikes, if this passes)

- Group boards + owner-rooted grants (who may write to a team frontier).
- Signing/publishing from our own stdlib code instead of `nak` (BIP-340 Schnorr + a minimal
  WS writer, the one real build).
- CSP: a hosted (non-file) leaderboard cannot open an external WebSocket under the artifact
  CSP; the file-served spike sidesteps this, a hosted mesh would need a relay on an allowed
  origin.
- Proof-tier carriage and curation over the wire.

## Effort

Half a day, one person, no repo dependencies added: a ~30-line `foldRelay` in the leaderboard,
a scratch relay, and the publish one-liner above. The producer (`summarize`) needs no change.
