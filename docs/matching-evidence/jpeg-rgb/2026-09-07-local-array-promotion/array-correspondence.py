from pathlib import Path
import json,re,sys
sys.path.insert(0,str(Path('tools/melee-agent').resolve()))
from src.mwcc_debug.tiebreak import IG,IGNode,validate_g1,predict_assignments
root=Path('/tmp/c016-rgb-array-stages/creation')
def instructions(name):return [i for b in json.loads((root/name).read_text())['blocks'] for i in b['instructions']]
final=instructions('pcode-0001-final.json');pre={i['address']:i for i in instructions('pcode-0001-forward_peephole.json')}
asm=json.loads(Path('/tmp/c016-rgb-array-local/chroma_index-no-row.json').read_text())
def lines(key):return [s for s in asm[key] if re.match(r'^\+[0-9a-f]+: (?:[0-9a-f]{2} ){3}[0-9a-f]{2}',s)]
current=lines('current_asm');target=lines('target_asm');assert len(final)==len(current)==len(target)==217
before=json.loads((root/'coloring-0001-gpr-01-before.json').read_text());after=json.loads((root/'coloring-0001-gpr-01-after.json').read_text());ns={n['virtual_register']:n for n in after['nodes']};bn={n['virtual_register']:n for n in before['nodes']};aliases=before['coalesced_registers']
order=before['simplify_order'];decision=set(order)
def physical(v):return v if v<32 else ns[aliases[v]]['physical_register']
nodes={n:IGNode(n,set(bn[n]['neighbors']),{v:physical(v) for v in bn[n]['neighbors'] if v not in decision},len(bn[n]['neighbors']),False,ns[n]['physical_register']) for n in order}
ig=IG(0,order,nodes,decision);g=validate_g1(ig);assert g.correct==g.total and not g.spill_abstained
assignments={};sites={};skipped=[];checks=0;conflicts=[]
for pos,(fin,line) in enumerate(zip(final,current)):
 off=pos*4
 pp=pre.get(fin['address'])
 if pp is None:skipped.append({'offset':hex(off),'reason':'No same-address precolor instruction'});continue
 if pp['opcode']!=fin['opcode']:skipped.append({'offset':hex(off),'reason':'Opcode changed after precolor'});continue
 po=[o for o in pp['operands'] if o['kind']==0];fo=[o for o in fin['operands'] if o['kind']==0]
 cr=[int(n) for n in re.findall(r'\br(\d+)\b',line.split('\t')[-1])]
 if len(po)!=len(fo) or len(fo)!=len(cr):skipped.append({'offset':hex(off),'reason':'PCode/assembly implicit operand count differs'});continue
 assert [o['reg'] for o in fo]==cr,(hex(off),fo,cr)
 assert [physical(o['reg']) for o in po]==cr,(hex(off),po,cr)
 target_pos={0xd4:0xd8,0xd8:0xd4,0x1f0:0x1f4,0x1f4:0x1f0}.get(off,off)//4
 norm=lambda text: re.sub(r'\b[rf]\d+\b','REG',text.split('\t')[-1])
 assert norm(line)==norm(target[target_pos]),(hex(off),'instruction shape',line,target[target_pos])
 tr=[int(n) for n in re.findall(r'\br(\d+)\b',target[target_pos].split('\t')[-1])]
 assert len(tr)==len(cr),(hex(off),cr,tr)
 for p,t in zip(po,tr):
  v=p['reg'];v=aliases[v] if v>=32 else v
  if v<32:
   assert v==t,(hex(off),'machine register',v,t);continue
  sites.setdefault(v,[]).append(hex(off))
  if v in assignments and assignments[v]!=t:conflicts.append({'offset':hex(off),'vreg':v,'a':assignments[v],'b':t})
  assignments[v]=t;checks+=1
print('Target contradictions:', conflicts)
base=predict_assignments(ig);changes={n:[base[n],t] for n,t in assignments.items() if n in base and base[n]!=t}
result={'valid_complete_coloring_target':not conflicts,'conflicts':conflicts,'scope':'Same-address precolor/final PCode correspondence validated against ordinary candidate assembly. Known two instruction transpositions aligned manually; row addition included. Conflicts invalidate the combined target assignment map. Unmapped nodes are not target proof.','checked_gpr_operands':checks,'mapped_virtuals':len(assignments),'skipped':skipped,'target_assignments':assignments,'changed_assignments':changes,'sites':sites}
Path('/tmp/c016-rgb-array-correspondence.json').write_text(json.dumps(result,indent=2)+'\n')
print('Checked',checks,'GPR operands;',len(assignments),'virtuals; changes',changes,'skipped',skipped)
