import json, sys
sys.path.insert(0,"/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr
rep=json.load(open("report_land_b.json"))
FR={"solo":(1.31,115,9,98.6),"delegate":(1.36,145,29.5,97.7),"workflow":(1.59,126,57.8,97.3)}
som=rep["rig_space"]["som"]
for c in som["cell_meaning"]:
    e=c.get("engine")
    if e in FR: c["cost"],c["eff"]=FR[e][0],FR[e][1]; c["flow"]=100-FR[e][2]; c["simp"]=FR[e][3]; c["coord"]=None
map_svg=vr.render_civ_map(som,svg_id="og-map",compact=True)
CSS="<style>"+vr._CSS+"</style>"+vr._WALK_CSS
og=f'''<!doctype html><html data-theme=dark><head><meta charset=utf-8>{CSS}<style>
*{{box-sizing:border-box}}
.vibrant{{max-width:none !important;width:1200px !important;margin:0 !important;padding:0 !important;background:transparent !important}}
html,body{{margin:0;background:#141412}}
.og{{width:1200px;height:630px;overflow:hidden;position:relative;
 background:radial-gradient(880px 480px at 82% -10%, rgba(111,214,201,.13), transparent 58%),#141412;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
.ogtext{{position:absolute;left:64px;top:126px;width:600px}}
.eye{{font-size:15px;font-weight:800;letter-spacing:.24em;text-transform:uppercase;color:var(--muted)}}
.wm{{display:flex;align-items:center;gap:13px;margin:12px 0 24px}}
.wm .w{{font-size:38px;font-weight:850;letter-spacing:.12em;color:var(--ink)}}
.wm svg{{width:42px;height:42px}}
.h1{{font-size:52px;font-weight:850;letter-spacing:-.02em;line-height:1.03;color:var(--ink);margin:0 0 18px}}
.sub{{font-size:20px;color:var(--ink2);line-height:1.4;max-width:26ch;margin:0 0 22px}}
.url{{font-size:20px;font-weight:700;color:var(--accent)}}
.ogmap{{position:absolute;right:40px;top:0;bottom:0;width:520px;display:flex;align-items:center;justify-content:center}}
.ogmap .box{{width:480px}}
.ogmap svg{{width:100% !important;height:auto !important;display:block;filter:drop-shadow(0 18px 55px rgba(0,0,0,.55))}}
</style></head><body><div class="vibrant"><div class="og">
 <div class="ogtext">
  <div class="eye">Third Division Labs</div>
  <div class="wm">{vr._som_mark()}<span class="w">VIBRANT</span></div>
  <div class="h1">Are you team Delegate or team Workflow?</div>
  <div class="sub">The efficiency frontier of AI coding setups. Surviving work per token, from your own logs.</div>
  <div class="url">vibrant.3dl.dev</div>
 </div>
 <div class="ogmap"><div class="box">{map_svg}</div></div>
</div></div></body></html>'''
open("og.html","w").write(og); print("wrote")
