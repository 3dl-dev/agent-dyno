import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

# Two pages, one design language (vibrant_report._CSS):
#   index.html  = the LIVE public frontier, TWO COLUMN (one column on mobile). Left: the live
#                 board folded from nostr (map + standings + frontier-best hero). Right: the
#                 rigor, how the measure works, what was tested, the sources and analyses
#                 integrated, and how to run it yourself (plugin OR a bare git clone). So the
#                 picture is never opaque: the method sits beside it.
#   sample.html = the full report (render_html), one click away, labeled a sample.
# Both theme-aware (system); html+body themed so no white band.

REPORT_SRC = "report_land_b.json"
rep = json.load(open(REPORT_SRC))

DEFAULT_RELAY = "wss://relay.3dl.network"
DEFAULT_BOARD = "30301:28e74283793831aa1563ef0ad0f21bbc8ca51f1e7b63ff71bd14a6b6fd0a31ee:public"
BLOB = "https://github.com/3dl-dev/vibrant/blob/main/"

TERR = {"solo": "#6fa0c6", "delegate": "#c9a06a", "workflow": "#a98bd0"}
LABEL = {"solo": "Solo", "delegate": "Delegate", "workflow": "Workflow"}

SEED = {"entries": [
    {"engine": "solo", "vector": {"dollars_per_survkb": 1.31, "survkb_per_outmtok": 115, "waste_pct": 9.0, "cache_read_pct": 98.6}, "samples": 74, "harness": "claude-code", "horizon": "session"},
    {"engine": "delegate", "vector": {"dollars_per_survkb": 1.36, "survkb_per_outmtok": 145, "waste_pct": 29.5, "cache_read_pct": 97.7}, "samples": 78, "harness": "claude-code", "horizon": "session"},
    {"engine": "workflow", "vector": {"dollars_per_survkb": 1.59, "survkb_per_outmtok": 126, "waste_pct": 57.8, "cache_read_pct": 97.3}, "samples": 59, "harness": "claude-code", "horizon": "session"},
]}

som = rep["rig_space"]["som"]
map_svg = vr.render_civ_map(som, svg_id="map-civ", compact=True)
legend = "".join(f'<span><i style="background:{TERR[e]};border-color:{TERR[e]}"></i>{LABEL[e]}</span>' for e in TERR)

# ---- sample.html: the full report, labeled a sample, link back to the frontier ----
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

# ---- index.html: the live frontier, two column ----
CSS = "<style>" + vr._CSS + "</style>" + vr._WALK_CSS
EXTRA = (
    "<style>"
    "html,body{margin:0;min-height:100%;background:#f4f3ef;}"
    "@media (prefers-color-scheme:dark){html:not([data-theme=light]),html:not([data-theme=light]) body{background:#141412;}}"
    # widen the page for two columns and left-align it (not the centered 760 report column).
    # The .vibrant is now just the page frame; the shareable is its own .card (left) and the
    # explanatory copy sits OUTSIDE that card, on the page background (right).
    ".vibrant{max-width:1160px;padding-top:34px;}"
    ".vibrant .fgrid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:44px;align-items:start;}"
    "@media (max-width:880px){.vibrant .fgrid{grid-template-columns:1fr;gap:34px;}}"
    # the shareable card: a discrete, screenshot-ready marketing unit with its own headline
    ".vibrant .share .fe{font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:var(--rust);}"
    ".vibrant .share h1{font-size:clamp(24px,2.7vw,32px);font-weight:850;letter-spacing:-.025em;line-height:1.08;margin:8px 0 10px;max-width:16ch;color:var(--ink);text-wrap:balance;}"
    ".vibrant .share .csub{font-size:14px;color:var(--ink2);line-height:1.5;margin:0 0 18px;max-width:46ch;}"
    ".vibrant .share .csub b{color:var(--ink);font-weight:650;}"
    # the explanatory column: on the page ground, no card frame, reads as context beside the share
    ".vibrant .method{padding-top:2px;}"
    ".vibrant .method .lead{font-size:15px;color:var(--ink2);line-height:1.55;margin:0 0 4px;max-width:52ch;}"
    ".vibrant .civ-wrap{position:relative;margin:8px 0 4px;}"
    ".vibrant .civ-legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12.5px;font-weight:650;color:var(--ink2);}"
    ".vibrant .civ-legend span{display:inline-flex;align-items:center;gap:6px;}"
    ".vibrant .civ-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none;border:1px solid;}"
    ".vibrant h2.sec{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:26px 0 12px;font-weight:800;}"
    ".vibrant h2.sec:first-child{margin-top:0;}"
    ".vibrant .edot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;vertical-align:middle;}"
    ".vibrant td.best{color:var(--good);font-weight:750;}"
    ".vibrant td.best::after{content:'';display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--good);margin-left:6px;box-shadow:0 0 7px var(--good);vertical-align:middle;}"
    ".vibrant .pareto{font-size:9.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--good);border:1px solid var(--good);border-radius:999px;padding:1px 6px;margin-left:7px;}"
    ".vibrant .ctxline{font-size:12.5px;color:var(--muted);margin:12px 2px 0;line-height:1.5;}"
    # the method / rigor column
    ".vibrant .mblock{margin:0 0 20px;}"
    ".vibrant .mblock .mh{font-size:14px;font-weight:750;color:var(--ink);margin:0 0 5px;letter-spacing:-.01em;}"
    ".vibrant .mblock p{font-size:13.5px;color:var(--ink2);line-height:1.55;margin:0 0 8px;}"
    ".vibrant .mblock ul{margin:6px 0 8px;padding-left:18px;font-size:13px;color:var(--ink2);line-height:1.5;}"
    ".vibrant .mblock ul li{margin:0 0 5px;}"
    ".vibrant .mblock b{color:var(--ink);font-weight:650;}"
    ".vibrant .verdict{font-size:10px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;padding:0 5px;border-radius:4px;margin-left:3px;}"
    ".vibrant .verdict.ok{color:var(--good);border:1px solid color-mix(in srgb,var(--good) 55%,transparent);}"
    ".vibrant .verdict.no{color:var(--down);border:1px solid color-mix(in srgb,var(--down) 55%,transparent);}"
    ".vibrant .refs a,.vibrant .mblock a{color:var(--accent);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 30%,transparent);}"
    ".vibrant .mblock pre{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 13px;font-size:12px;line-height:1.5;color:var(--ink2);overflow-x:auto;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:8px 0;}"
    ".vibrant .mblock code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:1px 5px;color:var(--ink);}"
    ".vibrant .seelink{font-size:13.5px;margin:8px 2px 0;}"
    ".vibrant .seelink a{color:var(--accent);font-weight:650;text-decoration:none;}"
    "</style>")

# LEFT: the shareable card, a discrete screenshot-ready marketing unit (brand, headline,
# hero, map, standings). This is the thing you clip to social.
LEFT = (
    '<div class="card share">'
    '<div class="top"><div class="brand">' + vr._som_mark() + 'VIBRANT</div>'
    '<div class="meta" id="board-meta">public frontier</div></div>'
    '<div class="fe" id="fe">Tokenmaxxing 2.0</div>'
    '<h1 id="h1">Progress over activity.</h1>'
    '<p class="csub" id="csub">The most surviving work per token, not the biggest bill. If you '
    'are rolling coal, you had better be hauling three trainloads.</p>'
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
    '</div>')

# RIGHT: the rigor, OUTSIDE the shareable card, on the page ground.
RIGHT = (
    '<div class="method">'
    '<p class="lead">Tokenmaxxing 1.0 was burning as many tokens as possible, rolling coal to '
    'look busy. 2.0 flips it: the win is surviving work per token, progress above activity. Spend big '
    'if the job needs it, then haul the cargo to match. The board above is the bragging rights, '
    'folded live from the shared frontier and anonymized; the method beside it is how to find '
    'the setup that hauls the most for your needs, and the one change most likely to move your '
    'number.</p>'
    '<h2 class="sec">How this is measured</h2>'
    '<div class="mblock"><div class="mh">Surviving work per token</div>'
    '<p>The numerator is a git measurement: lines you shipped that still live at HEAD, not '
    'reverted, rebuilt, or later bug-fixed, read at a horizon. It is the same for a human, '
    'Claude Code, or any agent. The denominator is priced tokens: input, output, and cache '
    'differ in price by about 20x, so they are counted and costed separately.</p></div>'
    '<div class="mblock"><div class="mh">The rig fingerprint</div>'
    '<p>Every setup is placed in a rig-space by a self-organizing map: topology, model routing, '
    'reasoning effort, review regime. The map on the left is that space; the territories are '
    'engine styles. Efficiency is a vector, never one grade, because the winner on one axis '
    'rarely wins another.</p></div>'
    '<div class="mblock"><div class="mh">What we tested</div>'
    '<p>Vibrant keeps a claims register: standing hypotheses re-checked every measurement '
    'window. A sample of the verdicts, from one operator\'s real logs:</p>'
    '<ul>'
    '<li><b>Cost is O(reads)</b><span class="verdict ok">confirmed</span> reads about 85% of spend.</li>'
    '<li><b>Solo is cheapest per surviving-KB</b><span class="verdict ok">supported</span></li>'
    '<li><b>Orchestrator to cheap-worker is N x cheaper</b><span class="verdict no">refuted</span> same cost, more waste.</li>'
    '<li><b>A cross-family model switch repays full prefill</b><span class="verdict ok">confirmed</span></li>'
    '<li><b>The raw efficiency ranking is real thrift</b><span class="verdict no">refuted</span> it is a task-difficulty selection artifact: efficiency = survival-rate x production-rate.</li>'
    '</ul>'
    '<p>To remove that confound, the <b>dynamometer</b> runs one fixed task across engines: '
    'orchestration multiplies token consumption for the same passing result. Its payoff is '
    'scope, not thrift.</p></div>'
    '<div class="mblock"><div class="mh">Sources and analyses</div>'
    '<ul class="refs">'
    f'<li><a href="{BLOB}docs/protocol.md">Protocol</a> and <a href="{BLOB}docs/governance.md">governance</a>: the measure, and the constitution behind it.</li>'
    f'<li><a href="{BLOB}docs/claims.md">Claims register</a>: every hypothesis, its metric, and its verdict (C1 to C14, review claims R1 to R6, external X1 to X8).</li>'
    f'<li><a href="{BLOB}docs/dyno-result.md">Dynamometer result</a>: the fixed-task solo versus orchestration experiment.</li>'
    f'<li><a href="{BLOB}docs/federation-nostr.md">Federation</a>: how anonymized aggregates travel (Nostr NIP-01 events, NIP-13 proof-of-work, BIP-340 signatures).</li>'
    '<li>Anthropic, <a href="https://www.anthropic.com/research">Optimizing for cost and intelligence</a> and <a href="https://www.anthropic.com/research">Multi-agent systems</a>: their findings, re-tested against our own git-survival data (claims X1 to X8), never adopted on faith.</li>'
    '<li><a href="https://dora.dev">DORA</a>: the change-failure-rate definition used in the report.</li>'
    '</ul></div>'
    '<div class="mblock"><div class="mh">Run it yourself</div>'
    '<p>Both ways are just Claude Code and a plain question. Install the plugin anywhere:</p>'
    '<pre>/plugin marketplace add 3dl-dev/vibrant\n/plugin install vibrant@vibrant\n"How efficient is my coding setup?"</pre>'
    '<p>Or clone the repo and start Claude Code inside it, nothing to install:</p>'
    '<pre>git clone https://github.com/3dl-dev/vibrant\ncd vibrant\nclaude\n# then ask: "How efficient is my coding setup?"</pre>'
    '<p>Claude Code runs the repo\'s own vibrant-report skill on your machine: it reads your '
    'logs and your git survival and writes the report. Python 3 standard library, nothing '
    'uploaded. The first run reads all your logs and can take a few minutes.</p></div>'
    '</div>')

BODY = ('<div class="vibrant"><div class="fgrid">' + LEFT + RIGHT + '</div></div>')

JS = (
    "<script>"
    "var DEFAULT_RELAY=" + json.dumps(DEFAULT_RELAY) + ",DEFAULT_BOARD=" + json.dumps(DEFAULT_BOARD) + ";"
    "var SEED=" + json.dumps(SEED, separators=(",", ":")) + ";"
    "var TERR=" + json.dumps(TERR, separators=(",", ":")) + ",LAB=" + json.dumps(LABEL, separators=(",", ":")) + ";"
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
    "var rows=es.map(function(e){var pareto=!es.some(function(o){return o!==e&&dom(o,e);});"
    "function cell(k){var v=+e.vector[k],b=Math.abs(v-best[k])<1e-9;return '<td class=\"num'+(b?' best':'')+'\">'+fmt(k,v)+'</td>';}"
    "return '<tr style=\"--ec:'+ecol(e.engine)+'\">'"
    "+'<td><span class=\"edot\" style=\"background:'+ecol(e.engine)+'\"></span><b style=\"color:'+ecol(e.engine)+'\">'+(LAB[e.engine]||e.engine)+'</b>'"
    "+(pareto?'<span class=\"pareto\">frontier</span>':'')+'</td>'"
    "+cell('dollars_per_survkb')+cell('survkb_per_outmtok')+cell('waste_pct')+cell('cache_read_pct')"
    "+'<td class=\"num meta\">'+(e.samples||'')+'</td></tr>';}).join('');"
    "document.getElementById('rows').innerHTML=rows;"
    "var top=es[0];if(top)heroFor(top.engine,top.vector,'frontier best');"
    "document.getElementById('context').textContent=(data.n||es.length)+' shared results, contributor-owned and anonymized. The glowing cell leads that axis; the frontier badge means nothing beats it on every axis.';"
    "if(window._applyYou)window._applyYou();}"
    # the combined-score hero, matching the report's score card: three meter toggles flow into
    # one big score (their product); toggling a meter recomputes it live, same interaction.
    "function heroFor(en,v,note){var f=document.getElementById('focal');"
    "var meters=[{k:'eff',label:'efficiency',oc:'var(--accent)',val:Math.round(+v.survkb_per_outmtok)},"
    "{k:'flow',label:'flow',oc:'var(--teal)',val:Math.round(100-(+v.waste_pct))},"
    "{k:'cache',label:'cache',oc:'var(--good)',val:Math.round(+v.cache_read_pct)}];"
    "window._meters=meters;window._on={eff:1,flow:1,cache:1};"
    "var chips=meters.map(function(m){return '<button type=\"button\" class=\"mtog\" data-m=\"'+m.k+'\" aria-pressed=\"true\" style=\"--oc:'+m.oc+'\"><b>'+m.val+'</b> '+m.label+'</button>';}).join('');"
    "var col=(note==='you')?'var(--rust)':ecol(en);"
    "f.innerHTML='<div class=\"topgroup\"><div class=\"cparts\">'+chips+'</div>'"
    "+'<div class=\"score-col\"><div class=\"cv\" id=\"vb-score\" style=\"color:'+col+'\"></div>'"
    "+'<div class=\"cn\">score, team '+(LAB[en]||en)+(note?' ('+note+')':'')+'</div>'"
    "+'<div class=\"chint\">the three meters multiplied; toggle one to change it, watch the trend not the total</div></div></div>';"
    "f.querySelectorAll('.mtog').forEach(function(b){b.addEventListener('click',function(){var k=b.getAttribute('data-m'),on=b.getAttribute('aria-pressed')==='true';b.setAttribute('aria-pressed',on?'false':'true');window._on[k]=on?0:1;recompute();});});"
    "recompute();}"
    "function recompute(){var p=1,any=false;(window._meters||[]).forEach(function(m){if(window._on[m.k]){p*=m.val;any=true;}});var el=document.getElementById('vb-score');if(el)el.textContent=any?p.toLocaleString():'0';}"
    "(function(){var m=/(?:^|#|&)you=([^&]+)/.exec(location.hash||'');if(!m)return;"
    "var f=decodeURIComponent(m[1]).split(',');if(f.length<5||!LAB[f[0]])return;"
    "var en=f[0],cost=+f[1],eff=f[2],waste=f[3],cache=f[4];"
    "window._applyYou=function(){"
    "var h1=document.getElementById('h1');if(h1)h1.textContent='You are team '+LAB[en]+'.';"
    "var cs=document.getElementById('csub');if(cs)cs.innerHTML='Your rig, from the link: <b>$'+cost.toFixed(2)+'</b> per surviving KB, <b>'+eff+'</b> KB per Mtok, <b>'+waste+'%</b> waste, <b>'+cache+'%</b> cache. Nothing uploaded, your numbers ride in the link.';"
    "heroFor(en,{dollars_per_survkb:cost,survkb_per_outmtok:eff,waste_pct:waste,cache_read_pct:cache},'you');};})();"
    "(function(){var h=new URLSearchParams((location.hash||'').replace(/^#/,''));"
    "var relay=h.get('relay')||DEFAULT_RELAY,board=h.get('board')||DEFAULT_BOARD;"
    "var meta=document.getElementById('board-meta');"
    "fold(relay,board).then(function(d){if(meta)meta.textContent='live frontier';render(d);})"
    ".catch(function(){if(meta)meta.textContent='seed frontier (offline)';render(SEED);});})();"
    "</script>")

PAGE = ("<!doctype html><html><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Vibrant, the public frontier</title>"
        "<meta property='og:title' content='Vibrant, Tokenmaxxing 2.0'>"
        "<meta property='og:description' content='Progress over activity. The most surviving work per token. Roll coal if you want, but haul three trainloads.'>"
        "<meta property='og:image' content='https://vibrant.3dl.dev/og.png'>"
        "<meta property='og:url' content='https://vibrant.3dl.dev'>"
        "<meta name='twitter:card' content='summary_large_image'>"
        + CSS + EXTRA + "</head><body>" + BODY + JS + "</body></html>")
open("index.html", "w").write(PAGE)
print("wrote index.html", len(PAGE), "| sample.html", len(sample),
      "| em-dashes:", (PAGE + sample).count("\u2014"))
