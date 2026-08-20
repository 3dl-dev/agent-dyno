import json, sys
sys.path.insert(0, "/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr

rep = json.load(open("report_land_b.json"))
FR = [("solo",1.31,115,9.0,98.6,74),("delegate",1.36,145,29.5,97.7,78),("workflow",1.59,126,57.8,97.3,59)]
FRD = {e:{"cost":c,"eff":ef,"waste":w,"cache":ca,"samples":s} for e,c,ef,w,ca,s in FR}
TERR={"solo":"#6fa0c6","delegate":"#c9a06a","workflow":"#a98bd0"}
LABEL={"solo":"Solo","delegate":"Delegate","workflow":"Workflow"}
TAG={"solo":"one-shotters","delegate":"orchestrator + worker","workflow":"DAG fan-out"}
som = rep["rig_space"]["som"]
cells_js={}
for c in som["cell_meaning"]:
    e=c.get("engine")
    if e in FRD:
        v=FRD[e]; c["cost"]=v["cost"]; c["eff"]=v["eff"]; c["flow"]=round(100-v["waste"],1); c["simp"]=v["cache"]; c["coord"]=None
        cells_js[f"{c['cell'][0]},{c['cell'][1]}"]={"engine":e,"cost":v["cost"],"eff":v["eff"],"flow":round(100-v["waste"],1),"cache":v["cache"],"samples":v["samples"]}
map_svg = vr.render_civ_map(som, svg_id="map-civ", compact=True)

AX=[("cost",1),("eff",0),("waste",1),("cache",0)]
best={k:(min if lo else max)(FRD, key=lambda e:FRD[e]["waste"] if k=="waste" else FRD[e][k]) for k,lo in AX}
def dom(a,b):
    ge=True;gt=False
    for k,lo in AX:
        av=FRD[a][k if k!="waste" else "waste"]; bv=FRD[b][k if k!="waste" else "waste"]
        if lo:
            if av>bv:ge=False
            if av<bv:gt=True
        else:
            if av<bv:ge=False
            if av>bv:gt=True
    return ge and gt
rows=""
for e in ["solo","delegate","workflow"]:
    d=FRD[e]; pareto=not any(dom(o,e) for o in FRD if o!=e)
    def C(k,fn,val): return f'<td class="num{" best" if best[k]==e else ""}">{fn(val)}</td>'
    rows+=f'<tr data-engine="{e}" style="--ec:{TERR[e]}"><td><span class="edot" style="background:{TERR[e]}"></span><b style="color:{TERR[e]}">{LABEL[e]}</b>{" <span class=pareto>frontier</span>" if pareto else ""}</td>{C("cost",lambda x:f"${x:.2f}",d["cost"])}{C("eff",lambda x:f"{x:.0f}",d["eff"])}{C("waste",lambda x:f"{x:.0f}%",d["waste"])}{C("cache",lambda x:f"{x:.1f}%",d["cache"])}<td class="num meta">{d["samples"]}</td></tr>'

chips="".join(f'<button class="team" data-engine="{e}" style="--tc:{TERR[e]}">team {LABEL[e]}<span class="tt2">{TAG[e]}</span></button>' for e in ["solo","delegate","workflow"])

CSS="<style>"+vr._CSS+"</style>"+vr._WALK_CSS
extra="""<style>
html,body{background:#141412;margin:0}
.fwrap{max-width:1140px;margin:0 auto;padding:8px}
.feye{font-size:11px;font-weight:800;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
.fh1{font-size:clamp(28px,4vw,44px);font-weight:850;letter-spacing:-.02em;color:var(--ink);margin:6px 0 8px;line-height:1.03;text-wrap:balance}
.fsub{color:var(--ink2);font-size:15.5px;max-width:70ch;margin:0 0 16px;line-height:1.55}
.fsub b{color:var(--ink)}
.teams{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 6px}
.team{font:inherit;font-size:14px;font-weight:700;cursor:pointer;background:transparent;color:var(--ink2);
 border:1.5px solid var(--line);border-radius:12px;padding:9px 15px;display:flex;flex-direction:column;gap:1px;line-height:1.15;transition:all .12s}
.team .tt2{font-size:10.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.team:hover{border-color:var(--tc)}
.team.on{border-color:var(--tc);color:var(--tc);box-shadow:inset 0 0 0 1px var(--tc),0 0 22px -6px var(--tc)}
.team.on .tt2{color:var(--tc);opacity:.8}
.focal{display:flex;align-items:baseline;gap:16px;margin:14px 2px 2px;flex-wrap:wrap}
.focal .big{font-size:clamp(46px,7vw,72px);font-weight:850;letter-spacing:-.04em;line-height:.9;font-variant-numeric:tabular-nums;color:var(--fc)}
.focal .flab{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);max-width:16ch;line-height:1.3}
.focal .vec{font-size:14px;color:var(--ink2);font-variant-numeric:tabular-nums}
.focal .vec b{color:var(--ink)}
.fgrid{display:grid;grid-template-columns:1.25fr 1fr;gap:26px;align-items:start;margin-top:20px}
@media(max-width:860px){.fgrid{grid-template-columns:1fr}}
.stand h2{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin:0 0 8px;font-weight:800}
.stand table{border-collapse:collapse;width:100%;font-size:13.5px}
.stand th,.stand td{padding:9px 8px;text-align:right;border-bottom:1px solid var(--line)}
.stand th{color:var(--muted);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;font-weight:800}
.stand th:first-child,.stand td:first-child{text-align:left}
.stand td.num{font-family:ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums;color:var(--ink)}
.stand td.best{color:var(--good);font-weight:800}
.stand td.best::after{content:"";display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--good);margin-left:6px;box-shadow:0 0 7px var(--good)}
.stand tr.on td{background:color-mix(in srgb,var(--ec) 12%,transparent)}
.edot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}
.pareto{font-size:9.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--good);border:1px solid var(--good);border-radius:999px;padding:1px 6px;margin-left:6px}
.stand .note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.45}
.runline{font-size:13px;color:var(--muted);margin-top:14px}
.runline b{color:var(--accent)}
</style>"""

body=f'''<div class="vibrant"><div class="fwrap"><div class="card">
 <div class="top"><div class="brand">{vr._som_mark()}VIBRANT</div><div class="meta">public frontier</div></div>
 <div style="padding:8px 6px 0">
  <div class="feye">Third Division Labs &middot; the efficiency frontier</div>
  <div class="fh1">Are you team Delegate or team Workflow?</div>
  <div class="fsub">From one-shotters to DAG orchestrators, across every combination of harness, model, context, and skill suites, vibe-coding rigs vary immeasurably. Vibrant densifies that statespace and objectively measures agentic code survival, waste, cache usage, cost, and surviving work per token.</div>
  <div class="teams">{chips}</div>
  <div class="focal" id="focal"></div>
  <div class="fgrid">
   <div class="civ-wrap">{map_svg}<div class="civ-tip" id="civ-tip"></div>
    <div class="civ-legend">{''.join(f'<span><i style="background:{TERR[e]};border-color:{TERR[e]}"></i>{LABEL[e]}</span>' for e in TERR)}</div></div>
   <div class="stand"><h2>Standings</h2>
    <table><thead><tr><th>team</th><th>$/surv-KB</th><th>KB/Mtok</th><th>waste</th><th>cache</th><th>n</th></tr></thead><tbody id="rows">{rows}</tbody></table>
    <div class="note">No single rank: the leader on one axis rarely leads another (dot = axis leader). <b style="color:var(--good)">frontier</b> = nothing beats it on every axis. Read the vector, not a rank.</div></div>
  </div>
  <div class="runline">This is the frontier. Run <b>vibrant-report</b> in Claude Code and it hands you a link that drops YOU onto this map, right next to your team. Nothing is uploaded.</div>
 </div>
 <div class="foot"><span>vibe-coding rig efficiency</span><span>3dl-dev/vibrant</span></div>
</div></div></div>'''

js=f'''<script>
var FRD={json.dumps(FRD,separators=(",",":"))},TERR={json.dumps(TERR,separators=(",",":"))},LAB={json.dumps(LABEL,separators=(",",":"))},CELLS={json.dumps(cells_js,separators=(",",":"))};
var tip=document.getElementById('civ-tip'),svg=document.getElementById('map-civ'),wrap=svg.parentNode,focal=document.getElementById('focal');
function pick(e){{
  document.querySelectorAll('.team').forEach(function(b){{b.classList.toggle('on',b.getAttribute('data-engine')===e);}});
  document.querySelectorAll('#rows tr').forEach(function(r){{r.classList.toggle('on',r.getAttribute('data-engine')===e);}});
  var d=FRD[e],c=TERR[e];
  focal.style.setProperty('--fc',c);
  focal.innerHTML='<div class="big">'+d.eff+'</div><div class="flab">surviving KB per output-Mtok, team '+LAB[e]+'</div>'
   +'<div class="vec">$<b>'+d.cost.toFixed(2)+'</b>/KB &middot; <b>'+d.waste+'%</b> waste &middot; <b>'+d.cache+'%</b> cache &middot; '+d.samples+' samples</div>';
  // brighten this team's territory label, dim the others
  svg.querySelectorAll('text').forEach(function(t){{var tx=t.textContent.trim().toLowerCase();
    if(['solo','delegate','workflow'].indexOf(tx)>=0) t.style.opacity=(tx===e)?'0.85':'0.18';}});
}}
document.querySelectorAll('.team').forEach(function(b){{b.addEventListener('click',function(){{pick(b.getAttribute('data-engine'));}});}});
svg.querySelectorAll('.civ-cell').forEach(function(cl){{
  cl.addEventListener('mouseenter',function(){{var c=CELLS[cl.getAttribute('data-r')+','+cl.getAttribute('data-c')];if(!c)return;
    tip.innerHTML='<span class="tt">team '+LAB[c.engine]+'</span><div>$'+c.cost.toFixed(2)+' per surviving KB &middot; <b>'+c.eff+'</b> KB/Mtok</div><div>flow '+c.flow+' &middot; cache '+c.cache+'% &middot; '+c.samples+' samples</div>';
    tip.classList.add('on');var wr=wrap.getBoundingClientRect(),cr=cl.getBoundingClientRect(),tw=tip.offsetWidth,th=tip.offsetHeight;
    var cx=cr.left+cr.width/2-wr.left,top=cr.top-wr.top-th-9;if(top<2)top=cr.bottom-wr.top+9;
    tip.style.left=Math.max(4,Math.min(cx-tw/2,wr.width-tw-4)).toFixed(0)+'px';tip.style.top=top.toFixed(0)+'px';}});
  cl.addEventListener('mouseleave',function(){{tip.classList.remove('on');}});}});
pick('delegate');
</script>'''

youjs = """<script>
(function(){
var svg=document.getElementById('map-civ'),focal=document.getElementById('focal');
function ctr(r,c){var cell=+svg.getAttribute('data-cell'),hs=+svg.getAttribute('data-hstep'),vs=+svg.getAttribute('data-vstep'),pad=+svg.getAttribute('data-pad');return {x:pad+cell/2+c*hs+((r%2)?hs/2:0),y:pad+cell/2+r*vs};}
function centroid(en){var xs=0,ys=0,n=0;for(var k in CELLS){if(CELLS[k].engine===en){var rc=k.split(',');var p=ctr(+rc[0],+rc[1]);xs+=p.x;ys+=p.y;n++;}}return n?{x:xs/n,y:ys/n}:null;}
function starPts(cx,cy,R){var p=[];for(var i=0;i<10;i++){var a=Math.PI/2+i*Math.PI/5,rd=(i%2==0)?R:R*0.42;p.push((cx+rd*Math.cos(a)).toFixed(1)+','+(cy-rd*Math.sin(a)).toFixed(1));}return p.join(' ');}
function dropYou(en,cost,eff,waste,cache){var p=centroid(en);if(!p)return;var CLAY='#C56A4C',rr=+svg.getAttribute('data-rr')||15;
 var g=document.createElementNS('http://www.w3.org/2000/svg','g');g.setAttribute('pointer-events','none');
 g.innerHTML='<circle cx="'+p.x+'" cy="'+p.y+'" r="'+(rr*1.5)+'" fill="'+CLAY+'" opacity="0.30" filter="url(#cvg)"></circle><polygon points="'+starPts(p.x,p.y,rr*0.72)+'" fill="'+CLAY+'"></polygon><circle cx="'+p.x+'" cy="'+p.y+'" r="'+(rr*1.05)+'" fill="none" stroke="'+CLAY+'" stroke-width="3"></circle><text x="'+p.x+'" y="'+(p.y-rr*1.55)+'" text-anchor="middle" font-size="13" font-weight="800" fill="'+CLAY+'" paint-order="stroke" stroke="#141412" stroke-width="3.5">YOU</text>';
 svg.appendChild(g);
 focal.style.setProperty('--fc',CLAY);
 focal.innerHTML='<div class="big">'+eff+'</div><div class="flab">your surviving KB per output-Mtok, team '+LAB[en]+'</div><div class="vec">$<b>'+(+cost).toFixed(2)+'</b>/KB &middot; <b>'+waste+'%</b> waste &middot; <b>'+cache+'%</b> cache</div>';
 var tb=document.getElementById('rows');tb.querySelectorAll('tr').forEach(function(r){r.classList.remove('on');});
 var tr=document.createElement('tr');tr.className='on';tr.style.setProperty('--ec',CLAY);
 tr.innerHTML='<td><span class="edot" style="background:'+CLAY+'"></span><b style="color:'+CLAY+'">YOU</b> <span class="pareto" style="color:'+CLAY+';border-color:'+CLAY+'">team '+LAB[en]+'</span></td><td class="num">$'+(+cost).toFixed(2)+'</td><td class="num">'+eff+'</td><td class="num">'+waste+'%</td><td class="num">'+cache+'%</td><td class="num meta">you</td>';
 tb.insertBefore(tr,tb.firstChild);
 document.querySelectorAll('.team').forEach(function(b){b.classList.toggle('on',b.getAttribute('data-engine')===en);});
 svg.querySelectorAll('text').forEach(function(t){var tx=t.textContent.trim().toLowerCase();if(['solo','delegate','workflow'].indexOf(tx)>=0)t.style.opacity=(tx===en)?'0.9':'0.18';});}
var m=/(?:^|#|&)you=([^&]+)/.exec(location.hash||'');
if(m){var f=decodeURIComponent(m[1]).split(',');if(f.length>=5&&LAB[f[0]]){dropYou(f[0],f[1],f[2],f[3],f[4]);var rl=document.querySelector('.runline');if(rl)rl.innerHTML='That is you on the frontier, team '+LAB[f[0]]+'. Re-run <b>vibrant-report</b> anytime to refresh your dot.';}}
})();
</script>"""

page="<!doctype html><html data-theme=dark><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><meta name=color-scheme content=dark><title>Vibrant, the public frontier</title>"+CSS+extra+"</head><body>"+body+js+youjs+"</body></html>"
open("frontier_page4.html","w").write(page)
print("wrote frontier_page4.html", len(page))
