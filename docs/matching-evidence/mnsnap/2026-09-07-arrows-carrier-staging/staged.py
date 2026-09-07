from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-arrows-staged');out.mkdir(exist_ok=True)
variants={}
start=base.index('void mnSnap_80257F24(void)')
for fields in [('joint',),('shape',),('joint','shape')]:
 part=base[start:]
 decl=''
 if 'joint' in fields:
  decl+='    HSD_Joint* arrows_model;\n'
  old='    jobj = HSD_JObjLoadJoint((HSD_Joint*) *arrows_joint);'
  part=part.replace(old,'    arrows_model = (HSD_Joint*) *arrows_joint;\n    jobj = HSD_JObjLoadJoint(arrows_model);',1)
 if 'shape' in fields:
  decl+='    HSD_ShapeAnimJoint* arrows_shape;\n'
  anchor='    HSD_JObjAddAnimAll(jobj, (HSD_AnimJoint*) *arrows_animjoint,'
  part=part.replace(anchor,'    arrows_shape = (HSD_ShapeAnimJoint*) *arrows_shapeanim;\n'+anchor,1).replace('(HSD_ShapeAnimJoint*) *arrows_shapeanim);','arrows_shape);',1)
 part=part.replace('    s32 i;',decl+'    s32 i;',1)
 variants['staged-'+'-'.join(fields)]=base[:start]+part
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
