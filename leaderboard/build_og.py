import sys
sys.path.insert(0,"/home/baron/projects/agent-dyno/skills/vibrant-report")
import vibrant_report as vr
TEAMS=[("Solo","#6fa0c6",115),("Delegate","#c9a06a",145),("Workflow","#a98bd0",126)]
CSS="<style>"+vr._CSS+"</style>"
cards="".join(f'<div class="tc" style="--c:{c}"><div class="tl"><span class="d"></span><span class="nm">team {n}</span></div><div class="num">{v}<span class="u">KB / Mtok</span></div></div>' for n,c,v in TEAMS)
og=f'''<!doctype html><html data-theme=dark><head><meta charset=utf-8>{CSS}<style>
*{{box-sizing:border-box}}
.vibrant{{max-width:none !important;width:1200px !important;margin:0 !important;padding:0 !important;background:transparent !important}}
html,body{{margin:0;background:#141412}}
.og{{width:1200px;height:630px;overflow:hidden;position:relative;
 background:radial-gradient(880px 480px at 80% -12%, rgba(111,214,201,.13), transparent 58%),#141412;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
.ogtext{{position:absolute;left:64px;top:118px;width:700px}}
.eye{{font-size:15px;font-weight:800;letter-spacing:.24em;text-transform:uppercase;color:var(--muted)}}
.wm{{display:flex;align-items:center;gap:13px;margin:12px 0 26px}}
.wm .w{{font-size:38px;font-weight:850;letter-spacing:.12em;color:var(--ink)}}
.wm svg{{width:42px;height:42px}}
.h1{{font-size:50px;font-weight:850;letter-spacing:-.02em;line-height:1.04;color:var(--ink);margin:0 0 18px}}
.sub{{font-size:20px;color:var(--ink2);line-height:1.4;max-width:30ch;margin:0 0 24px}}
.url{{font-size:20px;font-weight:700;color:var(--accent)}}
.ogcards{{position:absolute;right:56px;top:150px;width:308px;display:flex;flex-direction:column;gap:16px}}
.tc{{border:1px solid var(--line);border-left:4px solid var(--c);border-radius:14px;background:linear-gradient(100deg,color-mix(in srgb,var(--c) 12%,transparent),transparent 72%);padding:15px 18px}}
.tl{{display:flex;align-items:center;gap:9px;margin-bottom:5px}}
.tl .d{{width:11px;height:11px;border-radius:50%;background:var(--c);flex:none}}
.tl .nm{{font-size:19px;font-weight:800;color:var(--c)}}
.num{{font-size:38px;font-weight:850;color:var(--ink);font-variant-numeric:tabular-nums;line-height:1;white-space:nowrap}}
.num .u{{font-size:13px;font-weight:600;color:var(--muted);margin-left:8px}}
</style></head><body><div class="vibrant"><div class="og">
 <div class="ogtext">
  <div class="eye">Third Division Labs</div>
  <div class="wm">{vr._som_mark()}<span class="w">VIBRANT</span></div>
  <div class="h1">Are you team Delegate or team Workflow?</div>
  <div class="sub">The efficiency frontier of AI coding setups. Surviving work per token, from your own logs.</div>
  <div class="url">vibrant.3dl.dev</div>
 </div>
 <div class="ogcards">{cards}</div>
</div></div></body></html>'''
open("og.html","w").write(og); print("wrote")
