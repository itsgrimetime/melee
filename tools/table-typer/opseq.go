package main

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// asmInstr is one instruction line in a .s file. Labels and directives are not
// instructions and are never recorded, so gap budgets count only real ops.
type asmInstr struct {
	opcode   string
	operands []string // operand tokens, trailing commas stripped; empty for zero-operand ops
	srcLine  int      // 1-based line in the .s file (file-global, not per-function)
}

// asmFunc is one .fn/.endfn body.
type asmFunc struct {
	name   string
	instrs []asmInstr
}

// parseAsmFile parses one .s file's content into function bodies.
func parseAsmFile(content string) []asmFunc {
	var funcs []asmFunc
	var cur asmFunc
	inFn := false
	flush := func() {
		if inFn {
			funcs = append(funcs, cur)
		}
		cur = asmFunc{}
		inFn = false
	}
	for i, raw := range strings.Split(content, "\n") {
		line := strings.TrimSpace(raw)
		switch {
		case strings.HasPrefix(line, ".fn "):
			flush()
			name := line[len(".fn "):]
			if c := strings.IndexByte(name, ','); c >= 0 {
				name = name[:c]
			}
			cur = asmFunc{name: strings.TrimSpace(name)}
			inFn = true
		case strings.HasPrefix(line, ".endfn"):
			flush()
		default:
			if !inFn {
				continue
			}
			_, after, found := strings.Cut(line, "*/\t")
			if !found {
				continue // label, directive, comment, or blank
			}
			// Strip any trailing comment (inline data lines and annotated
			// branches can carry "/* ... */" or "# ..." after the mnemonic).
			if c := strings.Index(after, "/*"); c >= 0 {
				after = after[:c]
			}
			if c := strings.Index(after, "#"); c >= 0 {
				after = after[:c]
			}
			fields := strings.Fields(after)
			if len(fields) == 0 {
				continue
			}
			// Skip inline data emitted in instruction-line format (.4byte,
			// .byte, .float, ...): these are not real opcodes and would pollute
			// the frequency table and derive heuristic.
			if strings.HasPrefix(fields[0], ".") {
				continue
			}
			ops := make([]string, 0, len(fields)-1)
			for _, f := range fields[1:] {
				ops = append(ops, strings.TrimSuffix(f, ","))
			}
			cur.instrs = append(cur.instrs, asmInstr{opcode: fields[0], operands: ops, srcLine: i + 1})
		}
	}
	flush()
	return funcs
}

// opcodeFrequencies tallies opcode -> occurrence count across all bodies.
func opcodeFrequencies(funcs []asmFunc) map[string]int {
	freq := make(map[string]int)
	for _, f := range funcs {
		for _, ins := range f.instrs {
			freq[ins.opcode]++
		}
	}
	return freq
}

const gapCeiling = 32

// patToken is one element of a parsed pattern: a concrete opcode (optionally
// with operand-pattern tokens) or a bounded gap.
type patToken struct {
	isGap    bool
	opcode   string   // concrete only
	operands []string // concrete only: "_" wildcard or a consistency-variable name; nil => opcode-only
	gapMin   int      // gap only
	gapMax   int      // gap only
}

// parsePattern turns already-split tokens into pattern tokens. gapCap is the
// upper bound for a bare "*". Errors on out-of-ceiling bounds, bad gap syntax,
// or a leading/trailing gap.
func parsePattern(tokens []string, gapCap int) ([]patToken, error) {
	if gapCap > gapCeiling {
		gapCap = gapCeiling
	}
	var pat []patToken
	for _, t := range tokens {
		t = strings.TrimSpace(t)
		if t == "" {
			continue
		}
		switch {
		case t == "?":
			pat = append(pat, patToken{isGap: true, gapMin: 1, gapMax: 1})
		case t == "*":
			pat = append(pat, patToken{isGap: true, gapMin: 0, gapMax: gapCap})
		case strings.HasPrefix(t, "*{") && strings.HasSuffix(t, "}"):
			lo, hi, found := strings.Cut(t[2:len(t)-1], "..")
			if !found {
				return nil, fmt.Errorf("bad gap %q (use *{m..n} or *{m..})", t)
			}
			min, err := strconv.Atoi(strings.TrimSpace(lo))
			if err != nil || min < 0 {
				return nil, fmt.Errorf("bad gap lower bound in %q", t)
			}
			max := gapCeiling
			if hs := strings.TrimSpace(hi); hs != "" {
				if max, err = strconv.Atoi(hs); err != nil {
					return nil, fmt.Errorf("bad gap upper bound in %q", t)
				}
				if max > gapCeiling {
					return nil, fmt.Errorf("gap upper bound %d in %q exceeds ceiling %d", max, t, gapCeiling)
				}
			}
			if min > max {
				return nil, fmt.Errorf("gap lower bound exceeds upper bound in %q", t)
			}
			pat = append(pat, patToken{isGap: true, gapMin: min, gapMax: max})
		case strings.HasPrefix(t, "*"):
			return nil, fmt.Errorf("bad gap %q (use *, *{m..n}, *{m..}, or ?)", t)
		default:
			fields := strings.Fields(t)
			tok := patToken{opcode: fields[0]}
			for _, f := range fields[1:] {
				tok.operands = append(tok.operands, strings.TrimSuffix(f, ","))
			}
			pat = append(pat, tok)
		}
	}
	if len(pat) == 0 {
		return nil, fmt.Errorf("empty pattern")
	}
	if pat[0].isGap || pat[len(pat)-1].isGap {
		return nil, fmt.Errorf("pattern must begin and end with a concrete opcode (no leading/trailing gap)")
	}
	return pat, nil
}

// matchInstr reports whether ins satisfies concrete token tok under the current
// variable bindings. It may add bindings to vars; callers that need rollback
// must pass a clone (see solve). An opcode-only token (no operands) treats
// operands as don't-care.
func matchInstr(ins asmInstr, tok patToken, vars map[string]string) bool {
	if ins.opcode != tok.opcode {
		return false
	}
	if len(tok.operands) == 0 {
		return true
	}
	if len(ins.operands) != len(tok.operands) {
		return false
	}
	for i, p := range tok.operands {
		if p == "_" {
			continue
		}
		actual := ins.operands[i]
		if bound, ok := vars[p]; ok {
			if bound != actual {
				return false
			}
		} else {
			vars[p] = actual
		}
	}
	return true
}

// maxSolveNodes bounds the matcher's search per function body. Opcode-only
// patterns never approach it (their binding signature is empty, so the memo is
// fully effective). Patterns with consistency variables (e.g. --with-operands)
// can otherwise search exponentially many binding-distinct states; this cap makes
// the matcher abort that body gracefully instead of hanging. (A future
// optimization could decouple structural matching from binding verification to
// stay polynomial; for now the budget guarantees termination.)
//
// Tests may lower this to a small value to exercise the abort path quickly.
var maxSolveNodes = 2_000_000

// alignment is the result of matching a pattern within one function body.
type alignment struct {
	ok            bool
	aborted       bool // search budget exhausted before this body finished; result may be incomplete
	slackConsumed int  // total instructions absorbed by gaps
	startSrcLine  int
	endSrcLine    int
	lastIdx       int // internal: index of the last matched instruction
	bindings      map[string]string
}

// matcher holds the per-body search state so the node budget can be tracked
// across the recursion and across start positions.
type matcher struct {
	instrs  []asmInstr
	pat     []patToken
	memo    map[string]alignment
	nodes   int
	aborted bool
	keyBuf  []byte // reused scratch buffer for memo key construction (avoids fmt.Sprintf alloc)
}

// memoKey returns a unique string key for the (ii, pi, vars) triple. It reuses
// m.keyBuf to avoid a heap allocation on every call.
func (m *matcher) memoKey(ii, pi int, vars map[string]string) string {
	m.keyBuf = m.keyBuf[:0]
	m.keyBuf = strconv.AppendInt(m.keyBuf, int64(ii), 10)
	m.keyBuf = append(m.keyBuf, '|')
	m.keyBuf = strconv.AppendInt(m.keyBuf, int64(pi), 10)
	m.keyBuf = append(m.keyBuf, '|')
	m.keyBuf = append(m.keyBuf, varSig(vars)...)
	return string(m.keyBuf)
}

// matchPattern returns the tightest (minimum slack) alignment of pat anywhere in
// instrs, or ok=false if none. One result per body (overlapping starts collapse
// to the single best alignment). pat[0] and pat[last] are concrete (guaranteed
// by parsePattern). If the search budget is exhausted, the returned alignment's
// aborted flag is set and its match result may be incomplete.
func matchPattern(instrs []asmInstr, pat []patToken) alignment {
	m := &matcher{instrs: instrs, pat: pat, memo: map[string]alignment{}}
	var best alignment
	for start := range instrs {
		res := m.solve(start, 0, map[string]string{})
		if res.ok {
			res.startSrcLine = instrs[start].srcLine
			res.endSrcLine = instrs[res.lastIdx].srcLine
			if !best.ok || res.slackConsumed < best.slackConsumed {
				best = res
			}
		}
		if m.aborted {
			break
		}
	}
	if best.ok {
		best.bindings = cloneVars(best.bindings)
	}
	best.aborted = m.aborted
	return best
}

// solve returns the best completion of pat[pi:] starting at instrs[ii] under the
// given bindings. Memoized by (ii, pi, binding-signature). vars is never mutated:
// concrete tokens clone before attempting a candidate match. Aborts (setting
// m.aborted) once the node budget is exhausted.
func (m *matcher) solve(ii, pi int, vars map[string]string) alignment {
	if m.nodes >= maxSolveNodes {
		m.aborted = true
		return alignment{}
	}
	m.nodes++
	if pi == len(m.pat) {
		return alignment{ok: true, lastIdx: ii - 1, bindings: cloneVars(vars)}
	}
	key := m.memoKey(ii, pi, vars)
	if mm, ok := m.memo[key]; ok {
		return mm
	}
	var best alignment
	tok := m.pat[pi]
	if tok.isGap {
		maxG := tok.gapMax
		if rem := len(m.instrs) - ii; maxG > rem {
			maxG = rem // not enough instructions left; if gapMin > maxG the loop is a no-op
		}
		for g := tok.gapMin; g <= maxG; g++ {
			res := m.solve(ii+g, pi+1, vars)
			if res.ok {
				res.slackConsumed += g
				if !best.ok || res.slackConsumed < best.slackConsumed {
					best = res
				}
			}
			if m.aborted {
				return best // bail out; do not cache a partial result
			}
		}
	} else if ii < len(m.instrs) {
		v2 := cloneVars(vars)
		if matchInstr(m.instrs[ii], tok, v2) {
			best = m.solve(ii+1, pi+1, v2)
		}
	}
	if !m.aborted {
		m.memo[key] = best // never cache results computed under an abort
	}
	return best
}

func cloneVars(v map[string]string) map[string]string {
	c := make(map[string]string, len(v))
	for k, val := range v {
		c[k] = val
	}
	return c
}

func varSig(v map[string]string) string {
	if len(v) == 0 {
		return ""
	}
	keys := make([]string, 0, len(v))
	for k := range v {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var b strings.Builder
	for _, k := range keys {
		b.WriteString(k)
		b.WriteByte('=')
		b.WriteString(v[k])
		b.WriteByte(';')
	}
	return b.String()
}

// opseqResult is one ranked match for display.
type opseqResult struct {
	asmLoc    string // "path/to/file.s:STARTLINE"
	fnName    string
	slack     int
	size      int
	startLine int
	endLine   int
}

// sortResults orders by tightest match first (least gap slack), then smallest
// function (the historical tiebreak).
func sortResults(rs []opseqResult) {
	sort.SliceStable(rs, func(i, j int) bool {
		if rs[i].slack != rs[j].slack {
			return rs[i].slack < rs[j].slack
		}
		return rs[i].size < rs[j].size
	})
}

// broadLandmarkFreq: if the rarest landmark occurs more often than this in the
// corpus, the derived pattern is considered broad and a warning is emitted.
const broadLandmarkFreq = 150

var registerRe = regexp.MustCompile(`^([rf][0-9]+|cr[0-7])$`)

var controlFlowOps = map[string]bool{
	"b": true, "ba": true, "bl": true, "bla": true,
	"beq": true, "bne": true, "blt": true, "ble": true, "bgt": true, "bge": true,
	"bso": true, "bns": true, "bdnz": true, "bdz": true,
	"bctr": true, "bctrl": true, "blr": true, "blrl": true,
	"bclr": true, "bcctr": true, "bcctrl": true,
	"mtctr": true, "mtlr": true,
}

// isControlFlow reports whether opcode is a branch/structural op kept as an
// anchor. Branch-prediction hints (beq+, bne-) are stripped first.
func isControlFlow(opcode string) bool {
	return controlFlowOps[strings.TrimRight(opcode, "+-")]
}

type deriveOpts struct {
	// slack is added to each inter-landmark gap window (*{0..gap+slack}) to
	// tolerate minor codegen differences between similar functions.
	slack int
	// maxLandmarks is the target cap for total landmarks (CF anchors + rarity
	// fill). CF anchors are always kept, so the actual count may exceed this.
	maxLandmarks int
	// withOperands, when set, renders register operands as consistency variables
	// (v0, v1, …) on landmark tokens instead of bare opcodes.
	withOperands bool
}

// derivePattern builds a gap-tolerant pattern from a function body: control-flow
// anchors are always kept, the rarest non-control-flow ops fill toward
// maxLandmarks, and everything else collapses to bounded gaps. Returns the
// pattern tokens (for display via comma-join and for re-parsing) and a warning
// string (empty unless the specificity guard fires).
func derivePattern(instrs []asmInstr, freq map[string]int, opts deriveOpts) ([]string, string) {
	kept := make(map[int]bool)
	for i, ins := range instrs {
		if isControlFlow(ins.opcode) {
			kept[i] = true
		}
	}

	// Rarity fill: rarest non-control-flow ops first, up to the cap.
	type idxFreq struct{ idx, f int }
	var cand []idxFreq
	for i, ins := range instrs {
		if !kept[i] {
			cand = append(cand, idxFreq{i, freq[ins.opcode]})
		}
	}
	sort.Slice(cand, func(a, b int) bool {
		if cand[a].f != cand[b].f {
			return cand[a].f < cand[b].f
		}
		return cand[a].idx < cand[b].idx
	})
	for _, c := range cand {
		if len(kept) >= opts.maxLandmarks {
			break
		}
		kept[c.idx] = true
	}

	// Specificity guard: ensure at least one non-control-flow landmark (force the
	// rarest in, even past the cap), then warn if the rarest landmark is common.
	hasNonCF := false
	for i := range kept {
		if !isControlFlow(instrs[i].opcode) {
			hasNonCF = true
			break
		}
	}
	if !hasNonCF && len(cand) > 0 {
		kept[cand[0].idx] = true
	}

	// Ordered landmark indices.
	idxs := make([]int, 0, len(kept))
	for i := range kept {
		idxs = append(idxs, i)
	}
	sort.Ints(idxs)

	warning := ""
	minFreq, rarest := 1<<62, ""
	for _, i := range idxs {
		if f := freq[instrs[i].opcode]; f < minFreq {
			minFreq, rarest = f, instrs[i].opcode
		}
	}
	if rarest != "" && minFreq > broadLandmarkFreq {
		warning = fmt.Sprintf("derived pattern is broad: rarest landmark %q occurs %d times; results may be noisy", rarest, minFreq)
	}

	// Emit tokens with bounded gaps between consecutive landmarks.
	regVars := map[string]string{}
	var toks []string
	prev := -1
	for _, i := range idxs {
		if prev >= 0 {
			gap := i - prev - 1
			window := gap + opts.slack
			if window > gapCeiling {
				window = gapCeiling
			}
			if window > 0 {
				toks = append(toks, fmt.Sprintf("*{0..%d}", window))
			}
		}
		toks = append(toks, landmarkToken(instrs[i], opts.withOperands, regVars))
		prev = i
	}
	return toks, warning
}

// landmarkToken renders one landmark as a pattern token. With operands off it is
// just the opcode; with operands on, register operands become stable consistency
// variables (v0, v1, v2, …) and everything else becomes "_".
func landmarkToken(ins asmInstr, withOperands bool, regVars map[string]string) string {
	if !withOperands || len(ins.operands) == 0 {
		return ins.opcode
	}
	parts := []string{ins.opcode}
	for _, op := range ins.operands {
		if registerRe.MatchString(op) {
			v, ok := regVars[op]
			if !ok {
				v = fmt.Sprintf("v%d", len(regVars)) // safe past 26 distinct registers
				regVars[op] = v
			}
			parts = append(parts, v)
		} else {
			parts = append(parts, "_")
		}
	}
	return strings.Join(parts, " ")
}

// locateFuncDef returns "path:line" of the C definition (or placeholder) for
// name across cFiles, or a not-found note. This is the original cmdOpSeq closure
// lifted to package level (using strings instead of bytes) so the handler and
// tests can share it.
func locateFuncDef(cFiles []string, name string) string {
	for _, path := range cFiles {
		content, err := os.ReadFile(path)
		if err != nil {
			return err.Error()
		}
		for i, line := range strings.Split(string(content), "\n") {
			off := strings.Index(line, name)
			if off == -1 {
				continue
			}
			if off == 0 || strings.Contains(line, "/// #"+name) {
				return fmt.Sprintf("%s:%d", path, i+1)
			}
			// look for a type immediately prior
			parts := strings.Fields(line[:off])
			ok := len(parts) > 0
			for _, p := range parts {
				c := p[0]
				if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c == '_' || c == '*') {
					ok = false
					break
				}
			}
			if ok {
				return fmt.Sprintf("%s:%d", path, i+1)
			}
		}
	}
	return "(no definition or placeholder for " + name + ")"
}

// parseLikeTarget splits "<func>" or "<func>:lo-hi" into the name and an
// inclusive absolute asm-line range. A ":" with a malformed range is an error
// (function symbols never contain ":"). No ":" means no range (lo=hi=0).
func parseLikeTarget(s string) (name string, lo, hi int, err error) {
	i := strings.LastIndexByte(s, ':')
	if i < 0 {
		return s, 0, 0, nil
	}
	name = s[:i]
	a, b, ok := strings.Cut(s[i+1:], "-")
	if !ok {
		return name, 0, 0, fmt.Errorf("range %q must be lo-hi", s[i+1:])
	}
	if lo, err = strconv.Atoi(strings.TrimSpace(a)); err != nil {
		return name, 0, 0, fmt.Errorf("range lower bound in %q: %v", s, err)
	}
	if hi, err = strconv.Atoi(strings.TrimSpace(b)); err != nil {
		return name, 0, 0, fmt.Errorf("range upper bound in %q: %v", s, err)
	}
	return name, lo, hi, nil
}
