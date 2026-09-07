from pathlib import Path
import json,sys
sys.path.insert(0,'/Users/mike/code/mwcc-decomp/tools')
from coloring_model import replay_simplify
b=json.load(open('/tmp/c016-rgb-dest-expr-stages/creation/coloring-0001-gpr-01-before.json'));a=json.load(open('/tmp/c016-rgb-dest-expr-stages/creation/coloring-0001-gpr-01-after.json'));m=json.load(open('/tmp/c016-rgb-dest-expr-correspondence.json'));t={int(k):v for k,v in m['target_assignments'].items()};actual={n['virtual_register']:n['physical_register'] for n in a['nodes']}
base=replay_simplify(b);assert base['simplify_order']==b['simplify_order'] and all(actual[v]==c for v,c in base['colors'].items())
rows=[]
for v in [int(k) for k in m['changed_assignments']]:
 best=None
 for rank in [n+.5 for n in range(32,140)]:
  r=replay_simplify(b,ranks={v:rank});miss={x:[r['colors'].get(x),y] for x,y in t.items() if r['colors'].get(x)!=y}
  row={'virtual':v,'rank':rank,'count':len(miss),'misses':miss}
  if best is None or row['count']<best['count']:best=row
 rows.append(best);print(v,best['rank'],best['count'],flush=True)
Path('/tmp/c016-rgb-dest-rank.json').write_text(json.dumps({'scope':'Offline one-node scan-rank hypotheses only, no compiler forcing or source proof. Exact full baseline replay validated.','baseline_misses':len(m['changed_assignments']),'best_per_virtual':rows},indent=2))
