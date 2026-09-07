from pathlib import Path
import json,sys,itertools
sys.path.insert(0,'/Users/mike/code/mwcc-decomp/tools')
from coloring_model import replay_simplify
b=json.load(open('/tmp/c016-rgb-dest-expr-stages/creation/coloring-0001-gpr-01-before.json'));a=json.load(open('/tmp/c016-rgb-dest-expr-stages/creation/coloring-0001-gpr-01-after.json'));t={int(k):v for k,v in json.load(open('/tmp/c016-rgb-dest-expr-correspondence.json'))['target_assignments'].items()};actual={n['virtual_register']:n['physical_register'] for n in a['nodes']}
base=replay_simplify(b);assert base['simplify_order']==b['simplify_order'] and all(actual[v]==c for v,c in base['colors'].items())
rows=[]
for family in ['rank']:
 pairs=itertools.product([n+0.5 for n in range(32,141)],[n+0.5 for n in range(90,140)])
 for x,y in pairs:
  params={'ranks':{53:x,37:y}} if family=='rank' else {'extra_permanent_degree':{53:x,37:y}}
  r=replay_simplify(b,**params);miss={v:[r['colors'].get(v),c] for v,c in t.items() if r['colors'].get(v)!=c};rows.append({'family':family,'inputs':[x,y],'misses':miss,'count':len(miss),'order':r['simplify_order']})
 best=sorted([r for r in rows if r['family']==family],key=lambda r:r['count'])[:5];print(family,[(r['inputs'],r['count']) for r in best],flush=True)
Path('/tmp/c016-rgb-dest-rank-grid.json').write_text(json.dumps({'scope':'Hypothetical rank and degree perturbations; no compiler changes, no source-realizability proof. Full baseline replay verified. Degree deltas are abstract, not actual new edges.','rows':rows},indent=2))
