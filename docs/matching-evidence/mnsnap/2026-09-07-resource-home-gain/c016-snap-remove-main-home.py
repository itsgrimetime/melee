from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-remove-main-home');out.mkdir(exist_ok=True)
variants={}
start=base.index('void mnSnap_80257F24(void)')
for direct in [False,True]:
 part=base[start:]
 if direct:part=part.replace('mnSnap_GetWarnAnimJoint(snap)','warn_animjoint',1)
 part=part.replace('    void** main_joint;\n','',1).replace('    main_joint = &snap->main_joint;\n','',1)
 for expr in ['&snap->main_joint','mnSnap_GetMainJoint(snap)']:
  for embedded in [False,True]:
   block=part.replace('    main_load = main_joint;','    main_load = '+expr+';',1)
   if embedded:
    block=block.replace('    main_load = '+expr+';\n','',1).replace('*main_load','*(main_load = '+expr+')',1)
   name=('direct-warn' if direct else 'getter-warn')+'-'+('field' if expr.startswith('&') else 'getter')+'-'+('embedded' if embedded else 'separate')
   variants[name]=base[:start]+block
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
