import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

# The public site is ONE page: the real report (vibrant_report.render_html: sankey flows,
# the metric toggles with projection, the score-over-time timeline, the maps), topped by a
# slim orientation band. No second card, no overlay, no iframe: the earlier lead-in was a
# near-duplicate of the report's own hero+map, which read as two disjoint cards with no way
# back. The map, hero, and timeline each appear exactly once, in the report.
#
# Theme follows the VIEWER's system (light default, dark on system-dark) via the report's
# own tokens; the only theme-specific literals are the body canvas background (the .vibrant
# --surface token is out of scope on <body>), set for both themes so the canvas never
# mismatches the card.
#
# Data source: report_land_b.json is the seed frontier today, the drop-in for the nostr
# board aggregate (docs/federation-nostr.md); same report shape either way.

REPORT_SRC = "report_land_b.json"
rep = json.load(open(REPORT_SRC))
html = vr.render_html(rep)   # no data-theme pin: follow system

INTRO = (
    '<div class="frontier-intro">'
    '<div class="fe">Public frontier &middot; seed board</div>'
    '<h1>Where each rig style lands on surviving work per token.</h1>'
    '<p>These are frontier numbers, not yours yet. Run <b>vibrant-report</b> in Claude Code '
    'to drop your own onto the map below. Nothing is uploaded.</p>'
    '</div>')

HEAD_EXTRA = (
    "<meta property='og:title' content='Vibrant, the efficiency frontier'>"
    "<meta property='og:description' content='Where each rig style lands on surviving work per token. Run vibrant-report to drop your own in.'>"
    "<meta property='og:image' content='https://vibrant.3dl.dev/og.png'>"
    "<meta property='og:url' content='https://vibrant.3dl.dev'>"
    "<meta name='twitter:card' content='summary_large_image'>"
    "<style>"
    # canvas background follows the theme so it never mismatches the centered card
    "html,body{margin:0;background:#f4f3ef;}"
    "@media (prefers-color-scheme:dark){html:not([data-theme=light]) body{background:#141412;}}"
    # the orientation band, in the report's own theme tokens (so it tracks light/dark for free)
    ".vibrant .frontier-intro{text-align:center;padding:4px 4px 22px;margin:0 0 24px;"
    "border-bottom:1px solid var(--line);}"
    ".vibrant .frontier-intro .fe{font-size:11px;font-weight:800;letter-spacing:.2em;"
    "text-transform:uppercase;color:var(--muted);}"
    ".vibrant .frontier-intro h1{font-size:clamp(21px,3.2vw,29px);font-weight:800;"
    "letter-spacing:-.02em;line-height:1.12;margin:10px auto 10px;max-width:22ch;"
    "color:var(--ink);text-wrap:balance;}"
    ".vibrant .frontier-intro p{font-size:14px;color:var(--ink2);max-width:54ch;"
    "margin:0 auto;line-height:1.55;}"
    ".vibrant .frontier-intro p b{color:var(--ink);font-weight:650;}"
    "</style>")

# inject: OG + theme CSS before </head>, and the band as the first child of .vibrant
html = html.replace("</head>", HEAD_EXTRA + "</head>", 1)
html = html.replace('<div class="vibrant">', '<div class="vibrant">' + INTRO, 1)
# a real title for the public unfurl / tab
html = html.replace("<title>Vibrant: your efficiency over time</title>",
                    "<title>Vibrant, the public frontier</title>", 1)

open("index.html", "w").write(html)
print("wrote index.html", len(html), "| em-dashes:", html.count("—"))
