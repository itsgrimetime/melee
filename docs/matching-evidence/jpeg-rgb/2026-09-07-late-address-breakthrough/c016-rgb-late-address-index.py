from pathlib import Path
import subprocess,json,itertools
p=Path('src/sysdolphin/baselib/hsd_3B34.c');base=p.read_text();seed=Path('/tmp/c016-rgb-asymmetric-address/x518-unsigned-index.c').read_text();out=Path('/tmp/c016-rgb-late-address-index');out.mkdir(exist_ok=True)
index='                    chroma_index = (chroma_x & 2) * 4;\n                    chroma_index = (chroma_x & 1) + chroma_index;\n                    chroma_index += dst_row;'
terms={'low':'(chroma_x & 1)','high':'(chroma_x & 2) * 4','row':'dst_row'}
try:
 for order in itertools.permutations(terms):
  for unsigned_at in ['sum','column']:
   s=seed.replace('                    s32 chroma_index;','').replace(index,'')
   expr='('+' + '.join(terms[n] for n in order)+')'
   if unsigned_at=='sum':s=s.replace('(u32) chroma_index','(u32) '+expr).replace('chroma_index',expr)
   else:
    uexpr='('+' + '.join(('(u32) '+terms[n]) if n=='low' else terms[n] for n in order)+')'
    s=s.replace('(u32) chroma_index',uexpr).replace('chroma_index',expr)
   name='-'.join(order)+'-'+unsigned_at;(out/(name+'.c')).write_text(s);p.write_text(s)
   r=subprocess.run(['python','tools/checkdiff.py','hsd_803B3408','--no-tty','--format','json'],capture_output=True,text=True,timeout=150);(out/(name+'.json')).write_text(r.stdout);x=json.loads(r.stdout);print(name,x['fuzzy_match_percent'],x['classification'].get('stack_frame_sizes'),flush=True)
finally:p.write_text(base)
