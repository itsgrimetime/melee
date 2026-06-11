#!/usr/bin/env python3
"""Reconstruct TARGET register webs directly from target asm (checkdiff json).

CFG from branch structure; per-GPR reaching-def analysis; webs = union-find of
defs sharing uses. Output per web: reg, def/use positions, extent, blocks,
crossing-calls flag.  Usage: target_web_reconstructor.py <checkdiff.json> [--reg N]
"""
import json, re, sys
from collections import defaultdict

def parse_asm(asm_lines):
    out = []
    for ln in asm_lines:
        m = re.match(r'\+([0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*\t(\S+)\s*(.*)', ln)
        if m and 'R_PPC' not in ln.split(':', 1)[1][:30]:
            out.append((int(m.group(1), 16), m.group(2), m.group(3).strip()))
    return out

DEF_FIRST = {'li','lis','lwz','lbz','lhz','lha','mr','addi','addis','add','subf','sub',
             'rlwinm','rlwinm.','clrlwi','clrlwi.','slwi','srawi','srwi','extsb','extsh',
             'neg','or','or.','and','and.','xor','nor','andi.','ori','oris','xori','mulli',
             'mullw','divw','divwu','subfic','addic','addic.','addze','rlwimi','mflr','nand'}
LOAD_UPDATE = {'lwzu','lbzu','lhzu'}
STORES = {'stw','stb','sth','stmw'}
STORE_UPDATE = {'stwu','stbu','sthu'}
CMP = {'cmpw','cmpwi','cmplw','cmplwi','cmpi','cmp'}
BRANCH = {'b','bne','beq','blt','bgt','ble','bge','bdnz','bso','bns'}
VOLATILE = list(range(0, 13))  # r0,r3-r12 treated volatile (r1/r2 ignored anyway)

def regs_of(ops):
    return [int(x) for x in re.findall(r'\br(\d+)\b', ops)]

def def_use(mn, ops):
    """Return (defs, uses) register lists for one instruction."""
    rs = regs_of(ops)
    if mn in BRANCH or mn.startswith('bc'):
        return [], []
    if mn == 'bl':
        return [0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], [3, 4, 5, 6, 7, 8, 9, 10]
    if mn == 'blr':
        return [], [3]
    if mn in CMP or mn.endswith('.') and mn[:-1] in CMP:
        return [], rs
    if mn in STORES:
        if mn == 'stmw':
            base = rs[0]
            return [], list(range(base, 32)) + rs[1:]
        return [], rs
    if mn in STORE_UPDATE:
        return [rs[1]], rs
    if mn in LOAD_UPDATE:
        return [rs[0], rs[1]], rs[1:]
    if mn == 'lmw':
        return list(range(rs[0], 32)), rs[1:]
    if mn in ('mtlr', 'mtctr'):
        return [], rs
    if mn == 'rlwimi':                       # read-modify-write dest
        return [rs[0]], rs
    if mn in DEF_FIRST or (mn.endswith('.') and mn[:-1] in DEF_FIRST):
        return [rs[0]] if rs else [], rs[1:]
    return [], rs                            # conservative: treat all as uses

def build(json_path, which='target_asm'):
    d = json.load(open(json_path))
    A = parse_asm(d[which])
    n = len(A)
    # block leaders
    leaders = {0}
    off2idx = {A[i][0]: i for i in range(n)}
    for i, (off, mn, ops) in enumerate(A):
        m = re.search(r'<[^+>]*\+0x([0-9a-f]+)>', ops)
        if (mn in BRANCH or mn.startswith('bc')) and m:
            t = int(m.group(1), 16)
            if t in off2idx: leaders.add(off2idx[t])
            if i + 1 < n: leaders.add(i + 1)
    leaders = sorted(leaders)
    block_of = {}
    blocks = []
    for bi, lo in enumerate(leaders):
        hi = leaders[bi + 1] if bi + 1 < len(leaders) else n
        blocks.append((lo, hi))
        for k in range(lo, hi): block_of[k] = bi
    succ = defaultdict(set)
    for bi, (lo, hi) in enumerate(blocks):
        last = A[hi - 1]
        mn, ops = last[1], last[2]
        m = re.search(r'<[^+>]*\+0x([0-9a-f]+)>', ops)
        if mn == 'b' and m and int(m.group(1), 16) in off2idx:
            succ[bi].add(block_of[off2idx[int(m.group(1), 16)]])
        elif (mn in BRANCH or mn.startswith('bc')) and m and int(m.group(1), 16) in off2idx:
            succ[bi].add(block_of[off2idx[int(m.group(1), 16)]])
            if hi < n: succ[bi].add(block_of[hi])
        elif mn not in ('blr',):
            if hi < n: succ[bi].add(block_of[hi])
    # per-instruction def/use
    DU = [def_use(mn, ops) for off, mn, ops in A]
    # reaching defs per reg, block-level (def-site = instr idx)
    GEN = [dict() for _ in blocks]   # reg -> last def idx in block
    KILL = [set() for _ in blocks]   # regs killed
    for bi, (lo, hi) in enumerate(blocks):
        for k in range(lo, hi):
            for r in DU[k][0]:
                GEN[bi][r] = k
                KILL[bi].add(r)
    IN = [defaultdict(set) for _ in blocks]
    OUT = [defaultdict(set) for _ in blocks]
    changed = True
    while changed:
        changed = False
        for bi in range(len(blocks)):
            newin = defaultdict(set)
            for pi in range(len(blocks)):
                if bi in succ[pi]:
                    for r, s in OUT[pi].items(): newin[r] |= s
            newout = defaultdict(set)
            for r, s in newin.items():
                if r not in KILL[bi]: newout[r] |= s
            for r, k in GEN[bi].items(): newout[r].add(k)
            if newin != IN[bi] or newout != OUT[bi]:
                IN[bi], OUT[bi] = newin, newout
                changed = True
    # attribute uses to reaching defs; union-find defs sharing a use
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    web_uses = defaultdict(set)
    for bi, (lo, hi) in enumerate(blocks):
        cur = {r: set(s) for r, s in IN[bi].items()}
        for k in range(lo, hi):
            defs, uses = DU[k]
            for r in uses:
                if r < 13 and r not in (0,): pass
                rdefs = cur.get(r, set())
                if rdefs:
                    base = None
                    for dsite in rdefs:
                        if base is None: base = dsite
                        else: union(dsite, base)
                    web_uses[find(base)].add(k)
            for r in defs:
                cur[r] = {k}
    # collect webs
    webs = defaultdict(lambda: {'defs': set(), 'uses': set(), 'reg': None})
    for k in range(n):
        for r in DU[k][0]:
            if r >= 32: continue
            root = find(k)
            webs[root]['defs'].add(k)
            webs[root]['reg'] = r
    for root, uses in web_uses.items():
        webs[find(root)]['uses'] |= uses
    out = []
    for root, w in webs.items():
        if w['reg'] is None: continue
        sites = sorted(w['defs'] | w['uses'])
        lo, hi = sites[0], sites[-1]
        crossing = any(A[k][1] == 'bl' for k in range(lo, hi + 1))
        out.append({'reg': w['reg'], 'defs': sorted(w['defs']), 'uses': sorted(w['uses']),
                    'lo_off': A[lo][0], 'hi_off': A[hi][0], 'n_sites': len(sites),
                    'crossing_calls': crossing})
    return A, out

if __name__ == '__main__':
    path = sys.argv[1]
    A, webs = build(path)
    cs = [w for w in webs if 13 <= w['reg'] <= 31]
    print(f"instructions: {len(A)}, total webs: {len(webs)}, callee-save webs: {len(cs)}")
    for w in sorted(cs, key=lambda x: -x['n_sites'])[:40]:
        print(f"  r{w['reg']:2d} sites={w['n_sites']:3d} extent=+{w['lo_off']:x}..+{w['hi_off']:x} "
              f"calls={'Y' if w['crossing_calls'] else 'n'}")
