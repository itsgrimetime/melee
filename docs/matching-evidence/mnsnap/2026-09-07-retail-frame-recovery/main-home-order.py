from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-main-home-order');out.mkdir(exist_ok=True)
variants={}
start=base.index('void mnSnap_80257F24(void)')
part=base[start:]
# Exchange named ownership/order without changing resource values.
variants['swap-main-warning-declarations']=base[:start]+part.replace('    void** main_joint;', '    void** PLACEHOLDER;').replace('    void** warn_animjoint;', '    void** main_joint;').replace('    void** PLACEHOLDER;', '    void** warn_animjoint;')
for where in ['before-warn','after-warn','first']:
 block=part.replace('    main_joint = &snap->main_joint;\n','',1)
 anchor={'before-warn':'    warn_animjoint = &snap->warn_animjoint;','after-warn':'    warn_matanim = &snap->warn_matanim;','first':'    main_matanim = &snap->main_matanim;'}[where]
 block=block.replace(anchor,'    main_joint = &snap->main_joint;\n'+anchor,1)
 variants['main-assignment-'+where]=base[:start]+block
variants['remove-main-load-alias']=base[:start]+part.replace('    void** main_load;\n','').replace('    main_load = main_joint;\n','').replace('*main_load','*main_joint')
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
