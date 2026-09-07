from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-arrows-carriers');out.mkdir(exist_ok=True)
variants={}
import re
start=base.index('void mnSnap_80257F24(void)')
for fields in [('arrows_joint',),('arrows_shapeanim',),('arrows_joint','arrows_shapeanim')]:
 part=base[start:]
 for field in fields:
  part=part.replace('    void** '+field+';', '    struct { void** value; } '+field+';')
  part=re.sub(r'(?<!->)\b'+field+r'\b(?!;)',field+'.value',part)
 variants['carrier-'+'-'.join(fields)]=base[:start]+part
for fields in [('arrows_joint','arrows_animjoint','arrows_matanim','arrows_shapeanim'),('arrows_shapeanim','arrows_matanim','arrows_animjoint','arrows_joint')]:
 part=base[start:]
 for field in fields:part=part.replace('    void** '+field+';\n','')
 part=part.replace('    s32 i;','    struct {\n'+''.join('        void** '+f.replace('arrows_','')+';\n' for f in fields)+'    } arrows;\n    s32 i;',1)
 for field in fields:part=re.sub(r'(?<!->)\b'+field+r'\b','arrows.'+field.replace('arrows_',''),part)
 variants['grouped-'+fields[0]]=base[:start]+part
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
