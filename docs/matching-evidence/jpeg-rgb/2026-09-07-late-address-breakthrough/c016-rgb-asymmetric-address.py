from pathlib import Path
import subprocess,json
p=Path('src/sysdolphin/baselib/hsd_3B34.c');base=p.read_text();seed=Path('/tmp/c016-rgb-chroma-ownership/dest-expression.c').read_text();out=Path('/tmp/c016-rgb-asymmetric-address');out.mkdir(exist_ok=True)
try:
 for field in ['x518','x618']:
  original='((JpegWork*) (HSD_804D2648_BUF + chroma_index * 4))->data.'+field+'[0]'
  forms={'unsigned-index':'((JpegWork*) (HSD_804D2648_BUF + (u32) chroma_index * 4))->data.'+field+'[0]',
  'unsigned-product':'((JpegWork*) (HSD_804D2648_BUF + (u32) (chroma_index * 4)))->data.'+field+'[0]',
  'typed-field':'((JpegWork*) HSD_804D2648_BUF)->data.'+field+'[chroma_index]',
  'typed-field-unsigned':'((JpegWork*) HSD_804D2648_BUF)->data.'+field+'[(u32) chroma_index]',
  'char-base':'((JpegWork*) ((char*) HSD_804D2648_BUF + chroma_index * 4))->data.'+field+'[0]'}
  for label,expr in forms.items():
   assert original in seed;s=seed.replace(original,expr,1);name=field+'-'+label;(out/(name+'.c')).write_text(s);p.write_text(s)
   r=subprocess.run(['python','tools/checkdiff.py','hsd_803B3408','--no-tty','--format','json'],capture_output=True,text=True,timeout=150);(out/(name+'.json')).write_text(r.stdout);x=json.loads(r.stdout);print(name,x['fuzzy_match_percent'],x['classification'].get('stack_frame_sizes'),flush=True)
finally:p.write_text(base)
