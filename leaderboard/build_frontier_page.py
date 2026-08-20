import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

# The public site is the REAL report (vibrant_report.render_html: sankey flows, the
# metric toggles with projection, the score-over-time timeline, the maps), fed by
# frontier data. It is not a bespoke view. Two files:
#   report.html  = render_html(<frontier report>)   -- the real interface, standalone
#                  so its layout-measuring JS (sankey/waveform) runs uncontained.
#   index.html   = the lead-in (the map+hero attract card) laid OVER report.html in an
#                  iframe. The lead-in yields (fades) to the real report on enter, or is
#                  skipped entirely for a returning visitor / a #you deep-link, which is
#                  the "you have been here and loaded your data" path.
# Data source: report_land_b.json is the seed frontier today; it is the drop-in for the
# nostr-folded board aggregate (Stage 0/4, docs/federation-nostr.md) once the board is
# published, same report shape either way.

REPORT_SRC = "report_land_b.json"
rep = json.load(open(REPORT_SRC))

# ---- the real thing -------------------------------------------------------------
# Pin the public site to light on BOTH surfaces so a system-dark viewer never sees the
# lead-in and the iframe'd report split across themes (no dark-on-light mixing).
report_html = vr.render_html(rep).replace("<html>", "<html data-theme=light>", 1)
open("report.html", "w").write(report_html)

# ---- the lead-in attract card (map + hero), reusing the report's own design -----
FR = [("solo",1.31,115,9.0,98.6,74),("delegate",1.36,145,29.5,97.7,78),("workflow",1.59,126,57.8,97.3,59)]
FRD = {e:{"cost":c,"eff":ef,"waste":w,"cache":ca,"samples":s} for e,c,ef,w,ca,s in FR}
TERR={"solo":"#6fa0c6","delegate":"#c9a06a","workflow":"#a98bd0"}
LABEL={"solo":"Solo","delegate":"Delegate","workflow":"Workflow"}
DEFAULT_ENGINE = max(FRD, key=lambda e: FRD[e]["eff"])

som = rep["rig_space"]["som"]
cells_js={}
for c in som["cell_meaning"]:
    e=c.get("engine")
    if e in FRD:
        v=FRD[e]
        cells_js[f"{c['cell'][0]},{c['cell'][1]}"]={"engine":e,"cost":v["cost"],"eff":v["eff"],"flow":round(100-v["waste"],1),"cache":v["cache"],"samples":v["samples"]}
map_svg = vr.render_civ_map(som, svg_id="lead-civ", compact=True)
legend = "".join(f'<span><i style="background:{TERR[e]};border-color:{TERR[e]}"></i>{LABEL[e]}</span>' for e in TERR)

CSS = "<style>" + vr._CSS + "</style>" + vr._WALK_CSS
extra = """<style>
/* Explicit light ground (the .vibrant --surface token is out of scope here, so a var
   would leave these transparent and let the iframe bleed around the lead-in card). */
html,body{margin:0;min-height:100%;background:#f4f3ef;}
#real{position:fixed;inset:0;width:100vw;height:100vh;border:0;background:#f4f3ef;}
#leadin{position:fixed;inset:0;z-index:5;overflow:auto;background:#f4f3ef;
 display:flex;align-items:center;justify-content:center;padding:24px 16px;
 transition:opacity .55s ease;}
#leadin.gone{opacity:0;pointer-events:none;}
#leadin .card{max-width:680px;margin:0;}
.vibrant .civ-wrap{position:relative;margin:10px 0 6px;}
.vibrant .civ-legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12.5px;
 font-weight:650;color:var(--ink2);justify-content:center;}
.vibrant .civ-legend span{display:inline-flex;align-items:center;gap:6px;}
.vibrant .civ-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none;border:1px solid;}
.vibrant .lead-cta{display:flex;flex-direction:column;align-items:center;gap:8px;margin:18px auto 2px;text-align:center;}
.vibrant .lead-cta button{font:inherit;font-size:15px;font-weight:750;letter-spacing:.01em;cursor:pointer;
 color:#fff;background:var(--accent);border:0;border-radius:12px;padding:12px 26px;
 box-shadow:0 6px 22px -8px var(--accent);transition:transform .1s,box-shadow .2s;}
.vibrant .lead-cta button:hover{transform:translateY(-1px);box-shadow:0 10px 28px -8px var(--accent);}
.vibrant .lead-cta button:focus-visible{outline:2px solid var(--accent);outline-offset:3px;}
.vibrant .lead-sub{font-size:12.5px;color:var(--muted);max-width:46ch;line-height:1.5;}
.vibrant .lead-sub b{color:var(--ink2);font-weight:650;}
</style>"""

lead = f'''<div class="vibrant"><div class="card">
 <div class="top"><div class="brand">{vr._som_mark()}VIBRANT</div><div class="meta">public frontier</div></div>
 <div class="combined" id="focal"></div>
 <div class="civ-wrap">{map_svg}<div class="civ-tip" id="civ-tip"></div>
  <div class="civ-legend">{legend}</div></div>
 <div class="lead-cta">
  <button id="enter" type="button">Explore the report</button>
  <div class="lead-sub">A live report over the seed frontier. Run <b>vibrant-report</b> in Claude Code and it drops YOUR data in. Nothing is uploaded.</div>
 </div>
 <div class="foot"><span>vibe-coding rig efficiency</span><span>3dl-dev/vibrant</span></div>
</div></div>'''

leadjs = f'''<script>
var FRD={json.dumps(FRD,separators=(",",":"))},TERR={json.dumps(TERR,separators=(",",":"))},LAB={json.dumps(LABEL,separators=(",",":"))},CELLS={json.dumps(cells_js,separators=(",",":"))};
var svg=document.getElementById('lead-civ'),wrap=svg.parentNode,tip=document.getElementById('civ-tip'),focal=document.getElementById('focal');
function hero(en,cost,eff,waste,cache,you){{
  var flow=Math.round(100-(+waste)),numc=you?'var(--rust)':TERR[en];
  var lab=you?('your surviving KB per Mtok, team '+LAB[en]):('surviving KB per Mtok, team '+LAB[en]+' (frontier best)');
  var hint=you?'you, on the public frontier. nothing uploaded.':'the frontier for this engine style. explore the live report below.';
  focal.innerHTML='<div class="topgroup"><div class="cparts">'
   +'<span class="mtog" style="--oc:var(--accent)"><b>$'+(+cost).toFixed(2)+'</b> per surv-KB</span>'
   +'<span class="mtog" style="--oc:var(--teal)"><b>'+flow+'</b> flow</span>'
   +'<span class="mtog" style="--oc:var(--good)"><b>'+(+cache)+'%</b> cache</span>'
   +'</div><div class="score-col"><div class="cv" style="color:'+numc+'">'+eff+'</div>'
   +'<div class="cn">'+lab+'</div><div class="chint">'+hint+'</div></div></div>';
  svg.querySelectorAll('text').forEach(function(t){{var tx=t.textContent.trim().toLowerCase();
    if(['solo','delegate','workflow'].indexOf(tx)>=0) t.style.opacity=(tx===en)?'0.9':'0.2';}});
}}
svg.querySelectorAll('.civ-cell').forEach(function(cl){{
  cl.addEventListener('mouseenter',function(){{var c=CELLS[cl.getAttribute('data-r')+','+cl.getAttribute('data-c')];if(!c)return;
    tip.innerHTML='<span class="tt">team '+LAB[c.engine]+'</span><div>$'+c.cost.toFixed(2)+' per surviving KB &middot; <b>'+c.eff+'</b> KB/Mtok</div><div>flow '+c.flow+' &middot; cache '+c.cache+'% &middot; '+c.samples+' samples</div>';
    tip.classList.add('on');var wr=wrap.getBoundingClientRect(),cr=cl.getBoundingClientRect(),tw=tip.offsetWidth,th=tip.offsetHeight;
    var cx=cr.left+cr.width/2-wr.left,top=cr.top-wr.top-th-9;if(top<2)top=cr.bottom-wr.top+9;
    tip.style.left=Math.max(4,Math.min(cx-tw/2,wr.width-tw-4)).toFixed(0)+'px';tip.style.top=top.toFixed(0)+'px';}});
  cl.addEventListener('mouseleave',function(){{tip.classList.remove('on');}});}});
(function(){{var e='{DEFAULT_ENGINE}',d=FRD[e];
 var m=/(?:^|#|&)you=([^&]+)/.exec(location.hash||'');
 if(m){{var f=decodeURIComponent(m[1]).split(',');if(f.length>=5&&LAB[f[0]]){{hero(f[0],f[1],f[2],f[3],f[4],true);return;}}}}
 hero(e,d.cost,d.eff,d.waste,d.cache,false);}})();
</script>'''

# controller: yield the lead-in to the real report, or skip it for a returning /
# deep-linked visitor (the "loaded your data" path). #you rides through to the report.
controljs = """<script>
(function(){
var leadin=document.getElementById('leadin'),real=document.getElementById('real'),enter=document.getElementById('enter');
var hash=location.hash||'',hasYou=/you=/.test(hash);
if(hasYou){try{localStorage.setItem('vibrant_you',hash);}catch(e){}}
var stored=''; try{stored=localStorage.getItem('vibrant_you')||'';}catch(e){}
var deep=hasYou?hash:stored;
real.src='report.html'+deep;
var seen=false; try{seen=!!localStorage.getItem('vibrant_seen');}catch(e){}
function yieldTo(){leadin.classList.add('gone');try{localStorage.setItem('vibrant_seen','1');}catch(e){}
 setTimeout(function(){leadin.style.display='none';},600);}
if(hasYou||seen){yieldTo();}                       // been here / loaded data -> straight to the real report
if(enter)enter.addEventListener('click',yieldTo);  // otherwise the lead-in yields on enter
})();
</script>"""

page = ("<!doctype html><html data-theme=light><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Vibrant, the public frontier</title>"
        "<meta property='og:title' content='Vibrant, the efficiency frontier'>"
        "<meta property='og:description' content='Are you team Delegate or team Workflow? Surviving work per token, from your own logs.'>"
        "<meta property='og:image' content='https://vibrant.3dl.dev/og.png'>"
        "<meta property='og:url' content='https://vibrant.3dl.dev'>"
        "<meta name='twitter:card' content='summary_large_image'>"
        + CSS + extra + "</head><body>"
        + '<iframe id="real" title="Vibrant report" src="report.html"></iframe>'
        + '<div id="leadin">' + lead + '</div>'
        + leadjs + controljs + "</body></html>")
open("index.html", "w").write(page)
print("wrote report.html", len(report_html), "| index.html", len(page))
