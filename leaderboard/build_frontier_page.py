import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

# The public site is ONE page: the real report (vibrant_report.render_html) topped by a
# header that is HONEST about what the reader is looking at. report_land_b is a personal
# report (it has a YOU on the map, a personal score, a "your next move" line), so the page
# must present it as a SAMPLE / example, not as "the frontier, not yours" (that label
# contradicts the YOU the report visibly shows). The header also carries the how-to-run
# help, left-aligned. Theme follows the viewer's system; html AND body take the themed
# canvas so a tall viewport never shows a light band under a dark card.
#
# Data source: report_land_b.json is the seed/sample today, the drop-in for the nostr board
# aggregate (docs/federation-nostr.md); same report shape either way.

REPORT_SRC = "report_land_b.json"
rep = json.load(open(REPORT_SRC))
html = vr.render_html(rep)   # no data-theme pin: follow system

INTRO = (
    '<div class="frontier-intro">'
    '<div class="fe">Sample report</div>'
    '<h1>See how efficiently your coding setup turns tokens into work that lasts.</h1>'
    '<p>Below is a live example report: surviving work per token, the rig on the map, the '
    'single steepest move to improve it. Run it on your own logs and git history to get '
    'yours. It reads your machine locally and uploads nothing.</p>'
    '<div class="run">'
    '<div class="run-h">Run it in Claude Code</div>'
    '<ol class="run-steps">'
    '<li><code>/plugin marketplace add 3dl-dev/vibrant</code></li>'
    '<li><code>/plugin install vibrant@vibrant</code></li>'
    '<li>Then just ask: <b>"How efficient is my coding setup?"</b></li>'
    '</ol>'
    '<div class="run-note">The wizard measures your setup, and can drop your result onto '
    'this frontier if you choose. Publishing is always a separate, deliberate step.</div>'
    '</div>'
    '</div>')

HEAD_EXTRA = (
    "<meta property='og:title' content='Vibrant, the efficiency frontier'>"
    "<meta property='og:description' content='See how efficiently your coding setup turns tokens into work that lasts. Surviving work per token, from your own logs.'>"
    "<meta property='og:image' content='https://vibrant.3dl.dev/og.png'>"
    "<meta property='og:url' content='https://vibrant.3dl.dev'>"
    "<meta name='twitter:card' content='summary_large_image'>"
    "<style>"
    # canvas follows the theme on BOTH html and body, so a tall viewport never shows a
    # light band under a dark card (the earlier bug: only body was themed).
    "html,body{margin:0;min-height:100%;background:#f4f3ef;}"
    "@media (prefers-color-scheme:dark){"
    "html:not([data-theme=light]),html:not([data-theme=light]) body{background:#141412;}}"
    # the header: left-aligned, in the report's own theme tokens (tracks light/dark for free),
    # and constrained to the card's own column so it lines up with the report below.
    ".vibrant .frontier-intro{text-align:left;max-width:none;padding:2px 2px 24px;"
    "margin:0 0 26px;border-bottom:1px solid var(--line);}"
    ".vibrant .frontier-intro .fe{font-size:11px;font-weight:800;letter-spacing:.18em;"
    "text-transform:uppercase;color:var(--rust);}"
    ".vibrant .frontier-intro h1{font-size:clamp(22px,3.4vw,32px);font-weight:800;"
    "letter-spacing:-.02em;line-height:1.14;margin:10px 0 12px;max-width:24ch;"
    "color:var(--ink);text-wrap:balance;}"
    ".vibrant .frontier-intro p{font-size:14.5px;color:var(--ink2);max-width:62ch;"
    "margin:0 0 18px;line-height:1.55;}"
    ".vibrant .frontier-intro .run{background:var(--surface);border:1px solid var(--line);"
    "border-radius:12px;padding:16px 18px;max-width:62ch;}"
    ".vibrant .frontier-intro .run-h{font-size:10.5px;font-weight:800;letter-spacing:.09em;"
    "text-transform:uppercase;color:var(--muted);margin:0 0 10px;}"
    ".vibrant .frontier-intro .run-steps{list-style:decimal;margin:0;padding:0 0 0 20px;"
    "display:flex;flex-direction:column;gap:8px;font-size:13.5px;color:var(--ink2);}"
    ".vibrant .frontier-intro .run-steps li{line-height:1.5;}"
    ".vibrant .frontier-intro .run-steps b{color:var(--ink);font-weight:650;}"
    ".vibrant .frontier-intro code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"
    "monospace;font-size:12.5px;background:var(--card);border:1px solid var(--line);"
    "border-radius:6px;padding:2px 7px;color:var(--ink);}"
    ".vibrant .frontier-intro .run-note{font-size:12px;color:var(--muted);line-height:1.5;"
    "margin-top:12px;}"
    "</style>")

# #you: when the visitor arrives on their own share link, reframe the HEADER to state their
# four public axes (carried in the link, nothing uploaded). It deliberately does NOT touch
# the report body: the sample's map, score, and timeline stay as frontier context, because a
# four-number link cannot fabricate a personal report. The full personal report, and the
# per-URL team/individual fold from nostr, are the next build.
YOUJS = (
    "<script>(function(){var m=/(?:^|#|&)you=([^&]+)/.exec(location.hash||'');if(!m)return;"
    "var f=decodeURIComponent(m[1]).split(',');"
    "var LAB={solo:'Solo',delegate:'Delegate',workflow:'Workflow'};"
    "var en=f[0];if(!LAB[en]||f.length<5)return;"
    "var cost=+f[1],eff=f[2],waste=f[3],cache=f[4];"
    "var intro=document.querySelector('.frontier-intro');if(!intro)return;"
    "var fe=intro.querySelector('.fe');if(fe)fe.textContent='Your result';"
    "var h1=intro.querySelector('h1');if(h1)h1.textContent='You are team '+LAB[en]+'.';"
    "var p=intro.querySelector('p');if(p)p.innerHTML='Your rig, from the link: <b>$'+cost.toFixed(2)+"
    "'</b> per surviving KB, <b>'+eff+'</b> KB per Mtok, <b>'+waste+'%</b> waste, <b>'+cache+"
    "'%</b> cache. Nothing was uploaded, your four numbers ride in the link itself. The report "
    "below is the public frontier for context; run vibrant-report for your own full report.';"
    "})();</script>")

# inject: OG + theme CSS before </head>, header as the first child of .vibrant, #you wiring
# before </body>, and a real public title.
html = html.replace("</head>", HEAD_EXTRA + "</head>", 1)
html = html.replace('<div class="vibrant">', '<div class="vibrant">' + INTRO, 1)
html = html.replace("</body>", YOUJS + "</body>", 1)
html = html.replace("<title>Vibrant: your efficiency over time</title>",
                    "<title>Vibrant, the public frontier</title>", 1)

open("index.html", "w").write(html)
print("wrote index.html", len(html), "| em-dashes:", html.count("\u2014"))
