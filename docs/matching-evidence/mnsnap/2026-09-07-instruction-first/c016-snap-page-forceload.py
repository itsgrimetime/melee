from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-page-forceload');out.mkdir(exist_ok=True)
variants={}
start=base.index('void mnSnap_80257F24(void)')
helper='static inline void** mnSnap_GetPageJoint(mnSnap_State* snap)\n{\n    return &snap->page_joint;\n}\n\n'
for mode in ['getter','embedded-getter','embedded-field']:
 head=base[:start]
 part=base[start:]
 if mode!='embedded-field':head=head.replace('static inline void** mnSnap_GetMainJoint',helper+'static inline void** mnSnap_GetMainJoint',1)
 expr='mnSnap_GetPageJoint(snap)' if mode!='embedded-field' else '&snap->page_joint'
 if mode.startswith('embedded'):
  part=part.replace('    page_joint = &snap->page_joint;\n','',1)
  expr='(page_joint = '+expr+')'
 part=part.replace('"MenMainSubCsrSn_Top_shapeanim_joint", page_joint,','"MenMainSubCsrSn_Top_shapeanim_joint", '+expr+',',1)
 variants[mode]=head+part
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
