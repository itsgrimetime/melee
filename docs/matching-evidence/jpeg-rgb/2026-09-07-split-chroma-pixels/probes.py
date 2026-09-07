from pathlib import Path
import subprocess,json,re
p=Path('src/sysdolphin/baselib/hsd_3B34.c');base=p.read_text();seed=Path('docs/matching-evidence/jpeg-rgb/2026-09-07-donor-row-breakthrough/structural-candidate.c.txt').read_text();out=Path('/tmp/c016-rgb-split-pixels');out.mkdir(exist_ok=True)
try:
 for source_name,source in [('coherent',seed),('production',base)]:
  for typ in ['u16','s32','u32']:
   for scope in ['loop','per-store']:
    a=source.index('void hsd_803B3408(');b=source.index('static void fn_803B376C',a);body=source[a:b]
    first=body.index('                    pixel = src[');second=body.index('                    pixel = src[',first+1);end=body.index('\n                }',second)
    one=re.sub(r'\bpixel\b','cb_pixel',body[first:second]);two=re.sub(r'\bpixel\b','cr_pixel',body[second:end])
    if scope=='loop':
     one='                    '+typ+' cb_pixel;\n                    '+typ+' cr_pixel;\n\n'+one
    else:
     one=one.replace('cb_pixel = src[',typ+' cb_pixel = src[',1)
     two=two.replace('cr_pixel = src[',typ+' cr_pixel = src[',1)
     one='                    {\n'+one+'                    }\n'
     two='                    {\n'+two+'\n                    }'
    body=body[:first]+one+two+body[end:];s=source[:a]+body+source[b:];name=source_name+'-'+typ+'-'+scope
    (out/(name+'.c')).write_text(s);p.write_text(s)
    r=subprocess.run(['python','tools/checkdiff.py','hsd_803B3408','--no-tty','--format','json'],capture_output=True,text=True,timeout=150)
    (out/(name+'.json')).write_text(r.stdout);(out/(name+'.log')).write_text(r.stderr)
    x=json.loads(r.stdout);print(name,x.get('fuzzy_match_percent'),x.get('classification',{}).get('stack_frame_sizes'),flush=True)
finally:p.write_text(base)
