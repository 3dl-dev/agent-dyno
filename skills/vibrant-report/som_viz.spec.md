# som_viz.spec.md

The SOM map visualization (item 4): the learned fingerprint drawn as a shaded
lattice with the operator's trajectory, current position, and the recommended move.

## What it is

Item 3 gives the driver a `rig_space["som"]` block (a lattice, a per-cell economic
field, a time trajectory of cells, a current cell, and an arm-change arrow). Until
now the fingerprint has been numbers only in `report.json`; this renders it. It is a
self-contained inline SVG fragment in `report.html`, no external assets.

## The viewer must get it in one glance

The user's standing rule: a visualization that needs three paragraphs failed. This
map has to read on its own. The whole story is: "here is the space of working setups,
here is where you have been moving, here is where you are, and here is the cheaper
cell you already sometimes use." Everything else collapses behind `<details>`.

What the map shows, in one picture:

1. **The lattice**: a `rows x cols` grid of cells. Each cell is one learned working
   style (a region of the shape space: engine, firepower, rigor, fanout). Neighboring
   cells are similar setups (the SOM is topology-preserving).
2. **The field (shading)**: each cell shaded by `field[r][c]` = dollars per surviving
   KB, LOWER is better. Single-hue sequential ramp (the report's cost hue) so cheap
   reads light/calm and costly reads dark/hot, colorblind-safe (meaning is in
   lightness, not hue alone). The ramp is applied on a LOG scale: `d_per_survkb` is a
   ratio with a long tail, and a linear ramp squashes the whole cheap-to-mid range
   against one expensive outlier, so the map loses its midrange contrast. Cells with
   `field == null` (no in-window sessions) are drawn empty/neutral (a faint dashed
   outline, no fill), clearly "no data," never "good." A cell's inner support dot
   scales with `support[r][c]`.
3. **The trajectory (comet trail)**: draw the smoothed `drift` (the mood path), NOT
   the raw `trajectory` cells, as graduated dots: old = small and faint, recent =
   large and bold, so the direction of travel and where work concentrates read
   without a legend. A connected line is deliberately NOT used: when the operator
   oscillates between distant cells the line criss-crosses into noise; the dot
   size/opacity gradient carries time on its own. Fall back to the raw `trajectory`
   cells (deterministic index jitter) only when `drift` is absent. Any jitter is a
   deterministic function of the index, never random.
4. **The current cell**: a clear ring/dot on `current_cell`.
5. **The move arrow**: when `gradient.target_cell` is present, an arrow from
   `current_cell` to `target_cell`, captioned with the one-line arm-change
   (`gradient.arm_change`: "run your orchestrator at sonnet-5", derived from
   `from`/`to`/`axis`). When `target_cell` is null, draw no arrow (the field still
   renders; the arm-change text, if any, sits below as a line).

6. **Regional lenses (Civ-V map modes)**: when the block carries `cell_meaning` (per-cell
   setup, on the hex map), each fingerprint axis is a toggleable regional overlay. Each
   cell is a specific setup, but the SOM places similar setups adjacent, so a per-cell tint
   coloured by an axis paints "regional monotony": coherent coloured territories where the
   axis organises the map, mottled where it does not. Three lenses: `engine`
   (solo/delegate/workflow), `firepower` (lean/mid/heavy, binned off the orchestrator+worker
   models), `effort` (low/medium/high). A category's session-weighted centroid carries a bold
   label, nudged apart when two centroids collide (no overprinting). Tints ride BEHIND the
   cells (`class="som-lens-t"`), labels ON TOP (`class="som-lens-l"`), one group per lens; the
   grid geometry is untouched. One lens shows at a time, engine by default; the others are
   emitted `display:none` and revealed by the card's lens toggle. The overlay is honest by
   construction: a nearly-monotone axis (e.g. all-high effort) collapses to a single region,
   and an axis that does not cluster reads as mottled rather than as false borders. Lenses
   appear only on the hex style with `cell_meaning`; the classic map is unaffected.

Axis hint (small, muted): label the two lattice axes with what the SOM's PCA-oriented
init makes them roughly track, e.g. horizontal ~ firepower/rigor, vertical ~ fanout.
Keep it a hint, not a claim; the exact mapping is emergent.

## API

`render_som_map(som_block) -> str`:
- Pure function of the `rig_space["som"]` dict (the block item 3 emits).
- Returns an HTML string: a titled section containing one inline `<svg>` plus a
  collapsed `<details>` with the plain-language legend and, optionally, the raw
  numbers (mean field, occupied-cell count, window days).
- Returns `""` (empty string) when `som_block` is falsy, so a no-SOM report renders
  exactly as before.
- Called from `render_html` where the fingerprint section is (or a new section near
  the existing rig_space output); wired so its absence changes nothing.

## Stable render hooks (so the structural test is not brittle)

Give the SVG elements these class names, so the acceptance test can count them
without depending on layout:
- each cell fill: `class="som-cell"` (exactly `rows * cols` of them).
- the trajectory (comet-trail dots, or the fallback line): `class="som-path"`.
- the current-cell marker: `class="som-current"`.
- the move arrow (only when `gradient.target_cell` is set): `class="som-arrow"`.
- the arm-change caption text must contain the `to` arm value (e.g. `sonnet-5`).

## Style and theme

- Match the existing SVG charts in `vibrant_report.py` (viewBox, `role="img"`, an
  `aria-label`, the report's existing CSS class conventions and color variables).
  Read the sibling chart builders (the spark and the efficiency-over-time SVG) first
  and reuse their theme approach rather than inventing new colors.
- Theme-aware the same way the rest of the report is (do not hardcode a background
  that breaks in the other theme; use the report's variables/classes).
- Accessible: `aria-label` summarizing the map; do not rely on color alone (shading is
  monotonic in lightness, the current cell has a shape marker, the arrow has a caption).

## Determinism and constraints

- Stdlib only; pure string building. No external fonts, scripts, images, or URLs in
  the SVG (the report must stay self-contained and offline).
- Deterministic: same `som_block` in, byte-identical string out. Any jitter is a pure
  function of the cell index. The `test_vibrant_report.py` determinism assertion must
  stay green.
- No em-dashes.

## Acceptance (test_som_viz.py)

Structural, since pixels are checked by rendering (below):
- `render_som_map(None)` and `render_som_map({})` return `""`.
- For a fixture block with an `R x C` lattice: output contains one `<svg`, and exactly
  `R * C` cell `<rect>` elements (or the chosen cell mark), a trajectory `<polyline>`
  or `<path>`, a current-cell marker, and, when `gradient.target_cell` is set, an
  arrow element and the arm-change caption text.
- A block with `gradient.target_cell == null` yields no arrow element.
- No `http`/`https`/`url(` external references in the output.
- Deterministic: two calls byte-identical.

## Visual verification (not automated)

After the build, render `report.html` with the real snapshot and Read the screenshot
(Playwright chromium at `~/.cache/ms-playwright`). The map must be legible without
reading the `<details>`: the trajectory, current cell, and the cheaper-cell arrow all
visible at a glance. This is the real acceptance; the structural test only guards the
plumbing.

## Known limits

- The field is windowed (recent sessions); older regions the operator has left may
  read as empty even if they were once populated. That is correct: the map shows the
  live economy, and the trajectory still shows the historical path through those cells.
