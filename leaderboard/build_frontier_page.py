import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

# The public frontier page IS the approved report card surface (vibrant_report._CSS
# + _hero_card treatment + the civ map), light theme by default, differing from a
# personal report only in the peer layer: the frontier engine territories on the map
# and the operator's own star dropped on it via the #you fragment. No fork: no dark
# override, no bespoke chips, no standings table, no full-width wrapper.

rep = json.load(open("report_land_b.json"))
FR = [("solo",1.31,115,9.0,98.6,74),("delegate",1.36,145,29.5,97.7,78),("workflow",1.59,126,57.8,97.3,59)]
FRD = {e:{"cost":c,"eff":ef,"waste":w,"cache":ca,"samples":s} for e,c,ef,w,ca,s in FR}
TERR={"solo":"#6fa0c6","delegate":"#c9a06a","workflow":"#a98bd0"}
LABEL={"solo":"Solo","delegate":"Delegate","workflow":"Workflow"}
DEFAULT_ENGINE = max(FRD, key=lambda e: FRD[e]["eff"])  # frontier-best efficiency leads

som = rep["rig_space"]["som"]
cells_js={}
for c in som["cell_meaning"]:
    e=c.get("engine")
    if e in FRD:
        v=FRD[e]; c["cost"]=v["cost"]; c["eff"]=v["eff"]; c["flow"]=round(100-v["waste"],1); c["simp"]=v["cache"]; c["coord"]=None
        cells_js[f"{c['cell'][0]},{c['cell'][1]}"]={"engine":e,"cost":v["cost"],"eff":v["eff"],"flow":round(100-v["waste"],1),"cache":v["cache"],"samples":v["samples"]}
map_svg = vr.render_civ_map(som, svg_id="map-civ", compact=True)

legend = "".join(
    f'<span><i style="background:{TERR[e]};border-color:{TERR[e]}"></i>{LABEL[e]}</span>'
    for e in TERR)

# Reuse the report's design system verbatim (_CSS) and its map/interaction styles
# (_WALK_CSS). Only two additions, both minimal and on-palette: the map legend row and
# the intro paragraph. Nothing here overrides a report token.
CSS = "<style>" + vr._CSS + "</style>" + vr._WALK_CSS
extra = """<style>
.vibrant .civ-wrap{position:relative;margin:10px 0 6px;}
.vibrant .civ-legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:10px;font-size:12.5px;
 font-weight:650;color:var(--ink2);justify-content:center;}
.vibrant .civ-legend span{display:inline-flex;align-items:center;gap:6px;}
.vibrant .civ-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none;
 border:1px solid;}
.vibrant .fintro{text-align:center;max-width:56ch;margin:6px auto 0;}
.vibrant .fintro b{color:var(--ink);font-weight:650;}
</style>"""

body = f'''<div class="vibrant"><div class="card">
 <div class="top"><div class="brand">{vr._som_mark()}VIBRANT</div><div class="meta">public frontier</div></div>
 <div class="combined" id="focal"></div>
 <div class="civ-wrap">{map_svg}<div class="civ-tip" id="civ-tip"></div>
  <div class="civ-legend">{legend}</div></div>
 <p class="fintro">The efficiency frontier: where each engine style lands on surviving work per token. Run <b>vibrant-report</b> in Claude Code and it hands you a link that drops YOU onto this map. Nothing is uploaded.</p>
 <div class="foot"><span>vibe-coding rig efficiency</span><span>3dl-dev/vibrant</span></div>
</div></div>'''

js = f'''<script>
var FRD={json.dumps(FRD,separators=(",",":"))},TERR={json.dumps(TERR,separators=(",",":"))},LAB={json.dumps(LABEL,separators=(",",":"))},CELLS={json.dumps(cells_js,separators=(",",":"))};
var svg=document.getElementById('map-civ'),wrap=svg.parentNode,tip=document.getElementById('civ-tip'),focal=document.getElementById('focal');

// The hero, in the report's exact .combined / .cparts / .cv treatment. The metric
// differs from a personal report (survKB/Mtok is the cross-engine comparable, not the
// operator's private combined score) because this is the peer surface, but the visual
// treatment is identical: supporting chips flow-left into the big number.
function hero(en,cost,eff,waste,cache,you){{
  var flow=Math.round(100-(+waste));
  var numc=you?'var(--rust)':TERR[en];
  var lab=you?('your surviving KB per Mtok, team '+LAB[en]):('surviving KB per Mtok, team '+LAB[en]+' (frontier best)');
  var hint=you?'you, on the public frontier. nothing uploaded.':'the frontier for this engine style. drop yourself in to compare.';
  focal.innerHTML=
    '<div class="topgroup">'
   +'<div class="cparts">'
   +'<span class="mtog" style="--oc:var(--accent)"><b>$'+(+cost).toFixed(2)+'</b> per surv-KB</span>'
   +'<span class="mtog" style="--oc:var(--teal)"><b>'+flow+'</b> flow</span>'
   +'<span class="mtog" style="--oc:var(--good)"><b>'+(+cache)+'%</b> cache</span>'
   +'</div>'
   +'<div class="score-col">'
   +'<div class="cv" style="color:'+numc+'">'+eff+'</div>'
   +'<div class="cn">'+lab+'</div>'
   +'<div class="chint">'+hint+'</div>'
   +'</div></div>';
  // brighten this engine's territory label, dim the others
  svg.querySelectorAll('text').forEach(function(t){{var tx=t.textContent.trim().toLowerCase();
    if(['solo','delegate','workflow'].indexOf(tx)>=0) t.style.opacity=(tx===en)?'0.9':'0.2';}});
}}

// cell hover tooltip, same interaction as the report's maps
svg.querySelectorAll('.civ-cell').forEach(function(cl){{
  cl.addEventListener('mouseenter',function(){{var c=CELLS[cl.getAttribute('data-r')+','+cl.getAttribute('data-c')];if(!c)return;
    tip.innerHTML='<span class="tt">team '+LAB[c.engine]+'</span><div>$'+c.cost.toFixed(2)+' per surviving KB &middot; <b>'+c.eff+'</b> KB/Mtok</div><div>flow '+c.flow+' &middot; cache '+c.cache+'% &middot; '+c.samples+' samples</div>';
    tip.classList.add('on');var wr=wrap.getBoundingClientRect(),cr=cl.getBoundingClientRect(),tw=tip.offsetWidth,th=tip.offsetHeight;
    var cx=cr.left+cr.width/2-wr.left,top=cr.top-wr.top-th-9;if(top<2)top=cr.bottom-wr.top+9;
    tip.style.left=Math.max(4,Math.min(cx-tw/2,wr.width-tw-4)).toFixed(0)+'px';tip.style.top=top.toFixed(0)+'px';}});
  cl.addEventListener('mouseleave',function(){{tip.classList.remove('on');}});}});

// default hero: the frontier-best engine, so the page leads with a number like a report
(function(){{var e='{DEFAULT_ENGINE}',d=FRD[e];hero(e,d.cost,d.eff,d.waste,d.cache,false);}})();
</script>'''

youjs = """<script>
(function(){
var svg=document.getElementById('map-civ');
function ctr(r,c){var cell=+svg.getAttribute('data-cell'),hs=+svg.getAttribute('data-hstep'),vs=+svg.getAttribute('data-vstep'),pad=+svg.getAttribute('data-pad');return {x:pad+cell/2+c*hs+((r%2)?hs/2:0),y:pad+cell/2+r*vs};}
function centroid(en){var xs=0,ys=0,n=0;for(var k in CELLS){if(CELLS[k].engine===en){var rc=k.split(',');var p=ctr(+rc[0],+rc[1]);xs+=p.x;ys+=p.y;n++;}}return n?{x:xs/n,y:ys/n}:null;}
function starPts(cx,cy,R){var p=[];for(var i=0;i<10;i++){var a=Math.PI/2+i*Math.PI/5,rd=(i%2==0)?R:R*0.42;p.push((cx+rd*Math.cos(a)).toFixed(1)+','+(cy-rd*Math.sin(a)).toFixed(1));}return p.join(' ');}
function dropYou(en,cost,eff,waste,cache){var p=centroid(en);if(!p)return;var CLAY='#c2410c',rr=+svg.getAttribute('data-rr')||15;
 var g=document.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('pointer-events','none');
 g.innerHTML='<circle cx="'+p.x+'" cy="'+p.y+'" r="'+(rr*1.5)+'" fill="'+CLAY+'" opacity="0.28" filter="url(#cvg)"></circle><polygon points="'+starPts(p.x,p.y,rr*0.72)+'" fill="'+CLAY+'"></polygon><circle cx="'+p.x+'" cy="'+p.y+'" r="'+(rr*1.05)+'" fill="none" stroke="'+CLAY+'" stroke-width="3"></circle><text x="'+p.x+'" y="'+(p.y-rr*1.55)+'" text-anchor="middle" font-size="13" font-weight="800" fill="'+CLAY+'" paint-order="stroke" stroke="#ffffff" stroke-width="3.5">YOU</text>';
 svg.appendChild(g);
 hero(en,cost,eff,waste,cache,true);}
var m=/(?:^|#|&)you=([^&]+)/.exec(location.hash||'');
if(m){var f=decodeURIComponent(m[1]).split(',');if(f.length>=5&&LAB[f[0]]){dropYou(f[0],f[1],f[2],f[3],f[4]);
  var intro=document.querySelector('.fintro');if(intro)intro.innerHTML='That is you on the frontier, team '+LAB[f[0]]+'. Re-run <b>vibrant-report</b> anytime to refresh your dot. Nothing is uploaded.';}}
})();
</script>"""

page = ("<!doctype html><html><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Vibrant, the public frontier</title>"
        "<meta property='og:title' content='Vibrant, the efficiency frontier'>"
        "<meta property='og:description' content='Are you team Delegate or team Workflow? Surviving work per token, from your own logs.'>"
        "<meta property='og:image' content='https://vibrant.3dl.dev/og.png'>"
        "<meta property='og:url' content='https://vibrant.3dl.dev'>"
        "<meta name='twitter:card' content='summary_large_image'>"
        + CSS + extra + "</head><body>" + body + js + youjs + "</body></html>")
open("frontier_page4.html","w").write(page)
print("wrote frontier_page4.html", len(page))
