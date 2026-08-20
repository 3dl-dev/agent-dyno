import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

# Two pages, one design language (vibrant_report._CSS):
#   index.html  = the LIVE public frontier. It folds the board from nostr in the browser
#                 (kind-30078 aggregates, board-gated by the owner's 39301 grants) and renders
#                 the frontier map + a live standings table + a frontier-best hero. Falls back
#                 to the seed if the relay is unreachable. #you=... personalizes the header.
#                 #board=/#follows= override what is folded (team/individual views).
#   sample.html = the full report (render_html), so a visitor can see what their OWN report
#                 looks like, one click from the frontier. Clearly labeled a sample.
# Theme follows the viewer's system on both.

REPORT_SRC = "report_land_b.json"
rep = json.load(open(REPORT_SRC))

DEFAULT_RELAY = "wss://relay.3dl.network"
DEFAULT_BOARD = "30301:28e74283793831aa1563ef0ad0f21bbc8ca51f1e7b63ff71bd14a6b6fd0a31ee:public"

TERR = {"solo": "#6fa0c6", "delegate": "#c9a06a", "workflow": "#a98bd0"}
LABEL = {"solo": "Solo", "delegate": "Delegate", "workflow": "Workflow"}

# seed fallback (mirrors frontier/reference-frontier.json), used only if the relay is down
SEED = {"entries": [
    {"engine": "solo", "vector": {"dollars_per_survkb": 1.31, "survkb_per_outmtok": 115, "waste_pct": 9.0, "cache_read_pct": 98.6}, "samples": 74, "harness": "claude-code", "horizon": "session"},
    {"engine": "delegate", "vector": {"dollars_per_survkb": 1.36, "survkb_per_outmtok": 145, "waste_pct": 29.5, "cache_read_pct": 97.7}, "samples": 78, "harness": "claude-code", "horizon": "session"},
    {"engine": "workflow", "vector": {"dollars_per_survkb": 1.59, "survkb_per_outmtok": 126, "waste_pct": 57.8, "cache_read_pct": 97.3}, "samples": 59, "harness": "claude-code", "horizon": "session"},
]}

som = rep["rig_space"]["som"]
map_svg = vr.render_civ_map(som, svg_id="map-civ", compact=True)
legend = "".join(f'<span><i style="background:{TERR[e]};border-color:{TERR[e]}"></i>{LABEL[e]}</span>' for e in TERR)

# ---------------------------------------------------------------------------------
# sample.html: the full report, labeled a sample, with a link back to the frontier.
# ---------------------------------------------------------------------------------
sample = vr.render_html(rep)
SAMPLE_HEAD = (
    "<meta property='og:title' content='Vibrant, a sample report'>"
    "<style>html,body{margin:0;min-height:100%;background:#f4f3ef;}"
    "@media (prefers-color-scheme:dark){html:not([data-theme=light]),html:not([data-theme=light]) body{background:#141412;}}"
    ".vibrant .sample-band{text-align:left;padding:2px 2px 20px;margin:0 0 24px;border-bottom:1px solid var(--line);}"
    ".vibrant .sample-band .fe{font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:var(--rust);}"
    ".vibrant .sample-band p{font-size:14px;color:var(--ink2);margin:8px 0 0;max-width:60ch;line-height:1.55;}"
    ".vibrant .sample-band a{color:var(--accent);font-weight:650;text-decoration:none;}"
    "</style>")
SAMPLE_BAND = (
    '<div class="sample-band"><div class="fe">Sample report</div>'
    '<p>This is what a full Vibrant report looks like on one setup. Run it on your own logs to '
    'get yours, or <a href="./">go back to the live frontier</a>.</p></div>')
sample = sample.replace("</head>", SAMPLE_HEAD + "</head>", 1)
sample = sample.replace('<div class="vibrant">', '<div class="vibrant">' + SAMPLE_BAND, 1)
sample = sample.replace("<title>Vibrant: your efficiency over time</title>",
                        "<title>Vibrant, a sample report</title>", 1)
open("sample.html", "w").write(sample)

# ---------------------------------------------------------------------------------
# index.html: the live public frontier.
# ---------------------------------------------------------------------------------
CSS = "<style>" + vr._CSS + "</style>" + vr._WALK_CSS
EXTRA = (
    "<style>"
    "html,body{margin:0;min-height:100%;background:#f4f3ef;}"
    "@media (prefers-color-scheme:dark){html:not([data-theme=light]),html:not([data-theme=light]) body{background:#141412;}}"
    ".vibrant .frontier-intro{text-align:left;padding:2px 2px 22px;margin:0 0 22px;border-bottom:1px solid var(--line);}"
    ".vibrant .frontier-intro .fe{font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:var(--rust);}"
    ".vibrant .frontier-intro h1{font-size:clamp(22px,3.4vw,32px);font-weight:800;letter-spacing:-.02em;line-height:1.14;margin:10px 0 12px;max-width:24ch;color:var(--ink);text-wrap:balance;}"
    ".vibrant .frontier-intro p{font-size:14.5px;color:var(--ink2);max-width:62ch;margin:0 0 16px;line-height:1.55;}"
    ".vibrant .run{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;max-width:62ch;}"
    ".vibrant .run-h{font-size:10.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:0 0 9px;}"
    ".vibrant .run-steps{list-style:decimal;margin:0;padding:0 0 0 20px;display:flex;flex-direction:column;gap:7px;font-size:13.5px;color:var(--ink2);}"
    ".vibrant .run code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:2px 7px;color:var(--ink);}"
    ".vibrant .run b{color:var(--ink);font-weight:650;}"
    ".vibrant .civ-wrap{position:relative;margin:8px 0 4px;}"
    ".vibrant .civ-legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12.5px;font-weight:650;color:var(--ink2);}"
    ".vibrant .civ-legend span{display:inline-flex;align-items:center;gap:6px;}"
    ".vibrant .civ-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none;border:1px solid;}"
    ".vibrant h2.sec{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:30px 0 12px;font-weight:800;}"
    ".vibrant .edot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;vertical-align:middle;}"
    ".vibrant td.best{color:var(--good);font-weight:750;}"
    ".vibrant td.best::after{content:'';display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--good);margin-left:6px;box-shadow:0 0 7px var(--good);vertical-align:middle;}"
    ".vibrant .pareto{font-size:9.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--good);border:1px solid var(--good);border-radius:999px;padding:1px 6px;margin-left:7px;}"
    ".vibrant tr.you-row td{background:color-mix(in srgb,var(--rust) 12%,transparent);}"
    ".vibrant .youtag{font-size:9.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--rust);border:1px solid var(--rust);border-radius:999px;padding:1px 6px;margin-left:7px;}"
    ".vibrant .ctxline{font-size:12.5px;color:var(--muted);margin:12px 2px 0;line-height:1.5;}"
    ".vibrant .seelink{font-size:13.5px;margin:22px 2px 0;}"
    ".vibrant .seelink a{color:var(--accent);font-weight:650;text-decoration:none;}"
    "</style>")

INTRO = (
    '<div class="frontier-intro"><div class="fe" id="fe">Public frontier &middot; live</div>'
    '<h1 id="h1">Where each rig style lands on surviving work per token.</h1>'
    '<p id="lede">Folded live from the shared board: surviving work per token, by engine, '
    'contributor-owned and anonymized. No single rank, read the vector. Run it on your own logs '
    'to add yours.</p>'
    '<div class="run"><div class="run-h">Run it in Claude Code</div>'
    '<ol class="run-steps">'
    '<li><code>/plugin marketplace add 3dl-dev/vibrant</code></li>'
    '<li><code>/plugin install vibrant@vibrant</code></li>'
    '<li>Then just ask: <b>"How efficient is my coding setup?"</b></li>'
    '</ol></div></div>')

BODY = (
    '<div class="vibrant"><div class="card">'
    '<div class="top"><div class="brand">' + vr._som_mark() + 'VIBRANT</div>'
    '<div class="meta" id="board-meta">public frontier</div></div>'
    + INTRO +
    '<div class="combined" id="focal"></div>'
    '<div class="civ-wrap">' + map_svg + '<div class="civ-tip" id="civ-tip"></div>'
    '<div class="civ-legend">' + legend + '</div></div>'
    '<h2 class="sec">Standings</h2>'
    '<table><thead><tr><th>engine</th><th>$/surv-KB</th><th>KB/Mtok</th><th>waste</th>'
    '<th>cache</th><th>n</th></tr></thead><tbody id="rows"></tbody></table>'
    '<div class="ctxline" id="context">Loading the frontier...</div>'
    '<div class="seelink"><a href="sample.html">See a full sample report &rarr;</a>'
    '  what you get when you run it on your own setup.</div>'
    '<div class="foot"><span>vibe-coding rig efficiency</span><span>3dl-dev/vibrant</span></div>'
    '</div></div>')

# JS: fold the board (kind 30078 + owner grants 39301), render standings + frontier-best hero,
# seed fallback, and #you personalization. Adapted from leaderboard/vibrant.html (proven fold).
JS = (
    "<script>"
    "var DEFAULT_RELAY=" + json.dumps(DEFAULT_RELAY) + ",DEFAULT_BOARD=" + json.dumps(DEFAULT_BOARD) + ";"
    "var SEED=" + json.dumps(SEED, separators=(",", ":")) + ";"
    "var TERR=" + json.dumps(TERR, separators=(",", ":")) + ",LAB=" + json.dumps(LABEL, separators=(",", ":")) + ";"
    "var CELLS_YOU=" + json.dumps({f"{c['cell'][0]},{c['cell'][1]}": c.get("engine") for c in som["cell_meaning"] if c.get("engine") in TERR}, separators=(",", ":")) + ";"
    "var AXES=[['dollars_per_survkb','lo'],['survkb_per_outmtok','hi'],['waste_pct','lo'],['cache_read_pct','hi']];"
    "function ecol(e){return TERR[e]||'var(--muted)';}"
    "function fold(url,board){return new Promise(function(res,rej){"
    "var ws=new WebSocket(url),sub='vb',aggs={},grants={},owner=board?board.split(':')[1]:null,done=false;"
    "var timer=setTimeout(fin,15000);"
    "function granted(){var g={};if(owner)g[owner]=1;Object.keys(grants).forEach(function(p){if(grants[p]==='contributor')g[p]=1;});return g;}"
    "function fin(){if(done)return;done=true;clearTimeout(timer);try{ws.close();}catch(e){}"
    "var list=Object.keys(aggs).map(function(k){return aggs[k];});"
    "if(board){var g=granted();list=list.filter(function(a){return g[a._pub];});}"
    "var entries=list.map(function(a){return a.c;});"
    "entries.length?res({entries:entries,n:entries.length}):rej(new Error('empty'));}"
    "ws.onopen=function(){var fs=[{kinds:[30078],'#t':['vibrant-aggregate']}];"
    "if(board)fs.push({kinds:[39301],authors:[owner]});ws.send(JSON.stringify(['REQ',sub].concat(fs)));};"
    "ws.onmessage=function(m){var d;try{d=JSON.parse(m.data);}catch(e){return;}"
    "if(d[0]==='EVENT'&&d[1]===sub){var ev=d[2];"
    "if(ev.kind===30078){var c;try{c=JSON.parse(ev.content);}catch(e){return;}"
    "if(c&&c.engine&&c.vector)aggs[(c.id||ev.id)+':'+ev.pubkey]={c:c,_pub:ev.pubkey};}"
    "else if(ev.kind===39301){var p=null,role=null;(ev.tags||[]).forEach(function(t){if(t[0]==='p')p=t[1];if(t[0]==='role')role=t[1];});if(p)grants[p]=role;}}"
    "else if(d[0]==='EOSE'&&d[1]===sub)fin();};"
    "ws.onerror=function(){rej(new Error('relay error'));};});}"
    "function fmt(k,v){if(k==='dollars_per_survkb')return '$'+(+v).toFixed(2);"
    "if(k==='survkb_per_outmtok')return ''+Math.round(v);"
    "if(k==='waste_pct')return Math.round(v)+'%';return (+v).toFixed(1)+'%';}"
    "function render(data){var es=data.entries;var best={};"
    "AXES.forEach(function(a){var k=a[0],dir=a[1],vals=es.map(function(e){return +e.vector[k];});"
    "best[k]=dir==='lo'?Math.min.apply(null,vals):Math.max.apply(null,vals);});"
    "function dom(a,b){var ge=true,gt=false;AXES.forEach(function(ax){var k=ax[0],dir=ax[1],av=+a.vector[k],bv=+b.vector[k];"
    "if(dir==='lo'){if(av>bv)ge=false;if(av<bv)gt=true;}else{if(av<bv)ge=false;if(av>bv)gt=true;}});return ge&&gt;}"
    "es=es.slice().sort(function(a,b){return (+b.vector.survkb_per_outmtok)-(+a.vector.survkb_per_outmtok);});"
    "var youeng=(window._youEngine||null);"
    "var rows=es.map(function(e){var pareto=!es.some(function(o){return o!==e&&dom(o,e);});"
    "function cell(k){var v=+e.vector[k],b=Math.abs(v-best[k])<1e-9;return '<td class=\"num'+(b?' best':'')+'\">'+fmt(k,v)+'</td>';}"
    "var isyou=youeng&&e.engine===youeng&&e._you;"
    "return '<tr class=\"'+(isyou?'you-row':'')+'\" style=\"--ec:'+ecol(e.engine)+'\">'"
    "+'<td><span class=\"edot\" style=\"background:'+ecol(e.engine)+'\"></span><b style=\"color:'+ecol(e.engine)+'\">'+(LAB[e.engine]||e.engine)+'</b>'"
    "+(pareto?'<span class=\"pareto\">frontier</span>':'')+(isyou?'<span class=\"youtag\">you</span>':'')+'</td>'"
    "+cell('dollars_per_survkb')+cell('survkb_per_outmtok')+cell('waste_pct')+cell('cache_read_pct')"
    "+'<td class=\"num meta\">'+(e.samples||'')+'</td></tr>';}).join('');"
    "document.getElementById('rows').innerHTML=rows;"
    "var top=es[0];if(top)heroFor(top.engine,top.vector,'frontier best');"
    "document.getElementById('context').textContent=(data.n||es.length)+' shared results on the frontier, contributor-owned and anonymized. A row per rig; the glowing cell leads that axis, the frontier badge means nothing beats it on every axis. Read the vector, not a rank.';"
    "if(window._applyYou)window._applyYou();}"
    "function heroFor(en,v,note){var f=document.getElementById('focal');"
    "f.innerHTML='<div class=\"topgroup\"><div class=\"cparts\">'"
    "+'<span class=\"mtog\" style=\"--oc:var(--accent)\"><b>$'+(+v.dollars_per_survkb).toFixed(2)+'</b> per surv-KB</span>'"
    "+'<span class=\"mtog\" style=\"--oc:var(--teal)\"><b>'+Math.round(100-(+v.waste_pct))+'</b> flow</span>'"
    "+'<span class=\"mtog\" style=\"--oc:var(--good)\"><b>'+(+v.cache_read_pct)+'%</b> cache</span>'"
    "+'</div><div class=\"score-col\"><div class=\"cv\" style=\"color:'+ecol(en)+'\">'+Math.round(v.survkb_per_outmtok)+'</div>'"
    "+'<div class=\"cn\">surviving KB per Mtok, team '+(LAB[en]||en)+' ('+note+')</div>'"
    "+'<div class=\"chint\">the cross-engine comparable; higher is more surviving work per token</div></div></div>';}"
    # #you: mark the visitor's row + reframe the header (their four axes ride in the link)
    "(function(){var m=/(?:^|#|&)you=([^&]+)/.exec(location.hash||'');if(!m)return;"
    "var f=decodeURIComponent(m[1]).split(',');if(f.length<5||!LAB[f[0]])return;"
    "var en=f[0],cost=+f[1],eff=f[2],waste=f[3],cache=f[4];window._youEngine=en;"
    "window._applyYou=function(){"
    "document.getElementById('fe').textContent='Your result';"
    "document.getElementById('h1').textContent='You are team '+LAB[en]+'.';"
    "document.getElementById('lede').innerHTML='Your rig, from the link: <b>$'+cost.toFixed(2)+'</b> per surviving KB, <b>'+eff+'</b> KB per Mtok, <b>'+waste+'%</b> waste, <b>'+cache+'%</b> cache. Nothing was uploaded, your four numbers ride in the link. Below is the live frontier for context.';"
    "heroFor(en,{dollars_per_survkb:cost,survkb_per_outmtok:eff,waste_pct:waste,cache_read_pct:cache},'you');};})();"
    # boot: fold the baked board (or #board/#follows override), else seed
    "(function(){var h=new URLSearchParams((location.hash||'').replace(/^#/,''));"
    "var relay=h.get('relay')||DEFAULT_RELAY,board=h.get('board')||DEFAULT_BOARD;"
    "var meta=document.getElementById('board-meta');"
    "fold(relay,board).then(function(d){if(meta)meta.textContent='live frontier';render(d);})"
    ".catch(function(){if(meta)meta.textContent='seed frontier (offline)';render(SEED);});})();"
    "</script>")

PAGE = ("<!doctype html><html><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Vibrant, the public frontier</title>"
        "<meta property='og:title' content='Vibrant, the efficiency frontier'>"
        "<meta property='og:description' content='Surviving work per token, by engine, folded live from the shared board. Run vibrant-report to add yours.'>"
        "<meta property='og:image' content='https://vibrant.3dl.dev/og.png'>"
        "<meta property='og:url' content='https://vibrant.3dl.dev'>"
        "<meta name='twitter:card' content='summary_large_image'>"
        + CSS + EXTRA + "</head><body>" + BODY + JS + "</body></html>")
open("index.html", "w").write(PAGE)
print("wrote index.html", len(PAGE), "| sample.html", len(sample),
      "| em-dashes:", (PAGE + sample).count("—"))
