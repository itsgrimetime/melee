from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-arrows-lifetime');out.mkdir(exist_ok=True)
variants={}
start=base.index('void mnSnap_80257F24(void)')
part=base[start:]
for op in ['==','!=']:
 for where,anchor in [('before-archive','    lbArchive_LoadSections('),('after-archive','    /* Main GObj */'),('after-arrows','    /* Cursor GObj */')]:
  expr='    (void) (arrows_joint '+op+' arrows_shapeanim);\n'
  block=part.replace(anchor,expr+anchor,1)
  variants[where+'-'+('eq' if op=='==' else 'ne')]=base[:start]+block
rows=[]
try:
 for name,source in variants.items():
  p.write_text(source);(out/(name+'.c')).write_text(source)
  r=subprocess.run(['python','tools/checkdiff.py','mnSnap_80257F24','--format','json'],capture_output=True,text=True)
  (out/(name+'.json')).write_text(r.stdout);(out/(name+'.stderr')).write_text(r.stderr)
  try:
   d=json.loads(r.stdout);row={'name':name,'score':d['fuzzy_match_percent'],'frame':d['classification']['stack_frame_sizes'],'structural':d.get('structural')}
  except Exception:row={'name':name,'error':r.stdout[-300:]+r.stderr[-300:]}
  rows.append(row);print(row,flush=True)
finally:p.write_text(base)
(out/'summary.json').write_text(json.dumps(rows,indent=2))
