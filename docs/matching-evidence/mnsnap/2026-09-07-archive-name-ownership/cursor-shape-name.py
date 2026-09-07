from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-cursor-shape-name');out.mkdir(exist_ok=True)
variants={}
start=base.index('void mnSnap_80257F24(void)')
for mode in ['named','eq','ne']:
 part=base[start:]
 part=part.replace('    const char* page_name;','    const char* page_name;\n    const char* cursor_shape_name;',1)
 part=part.replace('"MenMainSubSn_Top_shapeanim_joint"','(cursor_shape_name = "MenMainSubSn_Top_shapeanim_joint")',1)
 if mode!='named':
  expr='    (void) ((const void*) cursor_shape_name '+('==' if mode=='eq' else '!=')+' (const void*) snap);\n'
  part=part.replace('    /* Main GObj */',expr+'    /* Main GObj */',1)
 variants[mode]=base[:start]+part
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
