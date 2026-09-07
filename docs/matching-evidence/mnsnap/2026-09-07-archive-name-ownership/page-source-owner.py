from pathlib import Path
import subprocess,json
p=Path('src/melee/mn/mnsnap.c');base=p.read_text();out=Path('/tmp/c016-snap-page-source-owner');out.mkdir(exist_ok=True)
variants={}
anchor='static inline void** mnSnap_GetMainJoint'
old='(page_name = "MenMainPhotoSn_Top_joint")'
for kind,body in [('direct','    return name;'),('named','    const char* result = name;\n    return result;'),('output','    *out = name;\n    return name;')]:
 signature='static inline const char* mnSnap_ResourceName(const char* name'+(', const char** out' if kind=='output' else '')+')\n{\n'+body+'\n}\n\n'
 seed=base.replace(anchor,signature+anchor,1)
 for mode in ['inside','outside']:
  if kind=='output':
   expr='mnSnap_ResourceName("MenMainPhotoSn_Top_joint", &page_name)'
   if mode=='outside':expr='(page_name = '+expr+')'
  elif mode=='inside':expr='(page_name = mnSnap_ResourceName("MenMainPhotoSn_Top_joint"))'
  else:expr='mnSnap_ResourceName(page_name = "MenMainPhotoSn_Top_joint")'
  variants[kind+'-'+mode]=seed.replace(old,expr,1)
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
