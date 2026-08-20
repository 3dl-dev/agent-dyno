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
.vibrant{{max-width:none !important;width:1280px !important;margin:0 !important;padding:0 !important;background:transparent !important}}
html,body{{margin:0}}
.og{{width:1280px;height:640px;overflow:hidden;position:relative;color:#f6f5f0;
 background:
  radial-gradient(900px 560px at 78% 30%, rgba(111,214,201,.20), transparent 55%),
  radial-gradient(700px 500px at 12% 88%, rgba(197,106,76,.12), transparent 55%),
  linear-gradient(135deg,#20241f 0%, #191c17 45%, #14150f 100%);
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
.og::before{{content:"";position:absolute;inset:0;box-shadow:inset 0 0 160px 40px rgba(0,0,0,.5);pointer-events:none}}
.ogtext{{position:absolute;left:72px;top:96px;width:620px;z-index:2}}
.eye{{font-size:16px;font-weight:800;letter-spacing:.24em;text-transform:uppercase;color:#9fb0a8}}
.wm{{display:flex;align-items:center;gap:14px;margin:14px 0 30px}}
.wm .w{{font-size:44px;font-weight:850;letter-spacing:.12em}}
.wm svg{{width:48px;height:48px}}
.h1{{font-size:58px;font-weight:850;letter-spacing:-.02em;line-height:1.02;margin:0 0 22px;color:#fff}}
.sub{{font-size:22px;color:#c7cabf;line-height:1.4;max-width:26ch;margin:0 0 26px}}
.url{{display:inline-block;font-size:21px;font-weight:800;color:#0b0d0a;background:#6fd6c9;padding:9px 18px;border-radius:10px}}
.ogmap{{position:absolute;right:-10px;top:0;bottom:0;width:560px;display:flex;align-items:center;justify-content:center;z-index:1;opacity:.98}}
.ogmap .box{{width:540px}}
.ogmap svg{{width:100% !important;height:auto !important;display:block;filter:drop-shadow(0 20px 60px rgba(0,0,0,.6))}}
</style></head><body><div class="vibrant"><div class="og">
 <div class="ogmap"><div class="box">{map_svg}</div></div>
 <div class="ogtext">
  <div class="eye">Tokenmaxxing 2.0</div>
  <div class="wm">{vr._som_mark()}<span class="w">VIBRANT</span></div>
  <div class="h1">Progress above activity.</div>
  <div class="sub">The most surviving work per token. Roll coal if you want, but haul three trainloads.</div>
  <span class="url">vibrant.3dl.dev</span>
 </div>
</div></div></body></html>'''
open("og.html","w").write(og); print("wrote")
