from pathlib import Path
import subprocess,json,re
p=Path('src/sysdolphin/baselib/hsd_3B34.c');base=p.read_text();seed=Path('docs/matching-evidence/jpeg-rgb/2026-09-07-donor-row-breakthrough/structural-candidate.c.txt').read_text();out=Path('/tmp/c016-rgb-array-local');out.mkdir(exist_ok=True)
try:
 for names in [('chroma_index',),('chroma_dest',),('chroma_index','chroma_dest')]:
  for remove in [False,True]:
   a=seed.index('void hsd_803B3408(');b=seed.index('static void fn_803B376C',a);body=seed[a:b]
   for name in names:
    body=re.sub(r'\b'+name+r'\b',name+'[0]',body)
    body=body.replace(name+'[0];',name+'[1];',1)
   if remove:
    body=body.replace('s32 row_offset = (pixel_index & 2) * stride;','')
    body=re.sub(r'\brow_offset\b','((pixel_index & 2) * stride)',body)
   s=seed[:a]+body+seed[b:];name='-'.join(names)+('-no-row' if remove else '')
   (out/(name+'.c')).write_text(s);p.write_text(s)
   r=subprocess.run(['python','tools/checkdiff.py','hsd_803B3408','--no-tty','--format','json'],capture_output=True,text=True,timeout=150)
   (out/(name+'.json')).write_text(r.stdout);(out/(name+'.log')).write_text(r.stderr)
   x=json.loads(r.stdout);print(name,x.get('fuzzy_match_percent'),x.get('classification',{}).get('stack_frame_sizes'),flush=True)
finally:p.write_text(base)
