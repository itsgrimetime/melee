# opseq Gap-Matching & Derive-From-Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded-gap wildcards to `opseq` and an `opseq --like <func>` mode that auto-derives an editable, gap-tolerant opcode pattern, so matching tolerates scheduler/register noise and patterns no longer have to be hand-authored.

**Architecture:** All work is in the Go tool `tools/table-typer` (package `main`). A new pure-logic file `opseq.go` holds a normalized per-function asm model, opcode-frequency tally, a pattern parser, an instruction matcher, a best-alignment pattern matcher (bounded backtracking + memoization), and the derive heuristic. The existing `case cmdOpSeq:` block in `main.go` is refactored to be a thin shell over these pure functions. Tests live in `opseq_test.go` and feed synthetic in-memory asm so they never invoke `ninja`/`report.json`.

**Tech Stack:** Go 1.23 (`package main`, module `table-typer`), stdlib `flag` via `lukechampine.com/flagg`. Tests are standard `go test`.

**Spec:** `docs/superpowers/specs/2026-06-07-opseq-gap-matching-design.md`

---

## File Structure

- **Create `tools/table-typer/opseq.go`** (package `main`) — all new pure logic:
  - Component 0: `asmInstr`, `asmFunc`, `parseAsmFile`
  - Component 2: `opcodeFrequencies`
  - Component 1: `patToken`, `parsePattern`, `matchInstr`, `alignment`, `matchPattern` (+ `solve`, `cloneVars`, `varSig`)
  - Component 3: `deriveOpts`, `isControlFlow`, `derivePattern`
  - Ranking: `opseqResult`, `sortResults`
- **Create `tools/table-typer/opseq_test.go`** (package `main`) — all unit tests.
- **Modify `tools/table-typer/main.go`** — register new flags (near lines 33-34) and replace the body of `case cmdOpSeq:` (lines ~343-463) with wiring over the new functions. The old `locateFuncDef`, `loadReport`, `findFiles`, and `MatchReport` helpers are reused unchanged.
- **Modify `.claude/skills/opseq/SKILL.md`** — document gap tokens, `--like`, and shell-quoting.

**Convention notes (read before coding):**
- An instruction line in a `.s` file looks like `/* 80037B40 00034720  3B E5 00 00 */\taddi r31, r5, 0x0`. The text after `*/\t` is `<opcode> <operands>`. Operands are space-separated and individually carry a trailing comma (`r31,`).
- Function bodies are delimited by `.fn <name>, <scope>` … `.endfn <name>`. Labels are lines starting with `.L_` and are NOT instructions.
- In a *pattern*, tokens are comma-separated; within one concrete token, opcode and operand-patterns are space-separated. Commas never appear inside a token, which is why gap bounds use `..` (`*{0..3}`) — the existing comma split stays valid.

---

## Task 1: Component 0 — normalized asm model + parser

**Files:**
- Create: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Create `tools/table-typer/opseq_test.go`:

```go
package main

import "testing"

const sampleAsm = `.include "macros.inc"
.file "x.c"
.text
.fn fn_a, global
/* 80000000 00000000  7C 08 02 A6 */	mflr r0
/* 80000004 00000004  90 01 00 04 */	stw r0, 0x4(r1)
.L_80000008:
/* 80000008 00000008  38 00 00 00 */	li r0, 0x0
/* 8000000C 0000000C  4E 80 00 20 */	blr
.endfn fn_a
.fn fn_b, global
/* 80000010 00000010  C0 22 00 00 */	lfs f1, 0x0(r2)
/* 80000014 00000014  EC 21 08 28 */	fsubs f1, f1, f1
.endfn fn_b
`

func TestParseAsmFile(t *testing.T) {
	funcs := parseAsmFile(sampleAsm)
	if len(funcs) != 2 {
		t.Fatalf("want 2 funcs, got %d", len(funcs))
	}
	if funcs[0].name != "fn_a" || funcs[1].name != "fn_b" {
		t.Fatalf("names: %q %q", funcs[0].name, funcs[1].name)
	}
	// fn_a has 4 instructions; the .L_ label must NOT be an instruction.
	if len(funcs[0].instrs) != 4 {
		t.Fatalf("fn_a want 4 instrs, got %d", len(funcs[0].instrs))
	}
	ins := funcs[0].instrs[1]
	if ins.opcode != "stw" {
		t.Fatalf("opcode: %q", ins.opcode)
	}
	if len(ins.operands) != 2 || ins.operands[0] != "r0" || ins.operands[1] != "0x4(r1)" {
		t.Fatalf("operands: %v", ins.operands)
	}
	if ins.srcLine != 6 {
		t.Fatalf("srcLine: want 6, got %d", ins.srcLine)
	}
	if funcs[1].instrs[1].opcode != "fsubs" {
		t.Fatalf("fn_b[1] opcode: %q", funcs[1].instrs[1].opcode)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run TestParseAsmFile ./...`
Expected: FAIL — `undefined: parseAsmFile`.

- [ ] **Step 3: Write minimal implementation**

Create `tools/table-typer/opseq.go`:

```go
package main

import "strings"

// asmInstr is one instruction line in a .s file. Labels and directives are not
// instructions and are never recorded, so gap budgets count only real ops.
type asmInstr struct {
	opcode   string
	operands []string // trailing commas stripped, e.g. ["r0", "0x4(r1)"]
	srcLine  int      // 1-based line within the .s file
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
			fields := strings.Fields(after)
			if len(fields) == 0 {
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run TestParseAsmFile ./...`
Expected: PASS (`ok  	table-typer`).

- [ ] **Step 5: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): normalized per-function asm model + parser"
```

---

## Task 2: Component 2 — corpus opcode frequency

**Files:**
- Modify: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Append to `opseq_test.go`:

```go
func TestOpcodeFrequencies(t *testing.T) {
	funcs := parseAsmFile(sampleAsm)
	freq := opcodeFrequencies(funcs)
	// fn_a: mflr, stw, li, blr ; fn_b: lfs, fsubs
	if freq["mflr"] != 1 || freq["blr"] != 1 || freq["lfs"] != 1 {
		t.Fatalf("freq: %v", freq)
	}
	if freq["nonexistent"] != 0 {
		t.Fatalf("missing opcode should be 0, got %d", freq["nonexistent"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run TestOpcodeFrequencies ./...`
Expected: FAIL — `undefined: opcodeFrequencies`.

- [ ] **Step 3: Write minimal implementation**

Append to `opseq.go`:

```go
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run TestOpcodeFrequencies ./...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): corpus opcode-frequency tally"
```

---

## Task 3: Component 1 — pattern parser (gap tokens + validation)

**Files:**
- Modify: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Append to `opseq_test.go`:

```go
func TestParsePattern(t *testing.T) {
	pat, err := parsePattern([]string{"lfs", "*{0..3}", "fsubs", "?", "bne"}, 6)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(pat) != 5 {
		t.Fatalf("want 5 tokens, got %d", len(pat))
	}
	if pat[0].isGap || pat[0].opcode != "lfs" {
		t.Fatalf("token0: %+v", pat[0])
	}
	if !pat[1].isGap || pat[1].gapMin != 0 || pat[1].gapMax != 3 {
		t.Fatalf("token1 gap: %+v", pat[1])
	}
	if !pat[3].isGap || pat[3].gapMin != 1 || pat[3].gapMax != 1 {
		t.Fatalf("token3 '?': %+v", pat[3])
	}
	// bare "*" uses the cap
	star, _ := parsePattern([]string{"a", "*", "b"}, 6)
	if star[1].gapMax != 6 {
		t.Fatalf("bare * cap: %+v", star[1])
	}
	// operand-bearing concrete token (space-separated operands)
	op, _ := parsePattern([]string{"addi x y _"}, 6)
	if op[0].opcode != "addi" || len(op[0].operands) != 3 || op[0].operands[0] != "x" || op[0].operands[2] != "_" {
		t.Fatalf("operands: %+v", op[0])
	}
}

func TestParsePatternErrors(t *testing.T) {
	cases := [][]string{
		{"*", "lfs"},           // leading gap
		{"lfs", "*"},           // trailing gap
		{"lfs", "*{0..99}", "b"}, // upper bound over ceiling (32)
		{"lfs", "*{3..1}", "b"},  // min > max
		{"lfs", "*{0,3}", "b"},   // comma form rejected (use ..)
		{},                       // empty
	}
	for _, c := range cases {
		if _, err := parsePattern(c, 6); err == nil {
			t.Fatalf("expected error for %v", c)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run TestParsePattern ./...`
Expected: FAIL — `undefined: parsePattern`.

- [ ] **Step 3: Write minimal implementation**

Append to `opseq.go` (add `"fmt"` and `"strconv"` to the import block — change `import "strings"` to a grouped import):

```go
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
```

The import block at the top of `opseq.go` becomes:

```go
import (
	"fmt"
	"strconv"
	"strings"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run TestParsePattern ./...`
Expected: PASS (covers both `TestParsePattern` and `TestParsePatternErrors`).

- [ ] **Step 5: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): gap-token pattern parser with bounds validation"
```

---

## Task 4: Component 1 — single-instruction matcher

**Files:**
- Modify: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Append to `opseq_test.go`:

```go
func TestMatchInstr(t *testing.T) {
	ins := asmInstr{opcode: "addi", operands: []string{"r3", "r4", "0x8"}}

	// opcode-only token matches regardless of operands
	if !matchInstr(ins, patToken{opcode: "addi"}, map[string]string{}) {
		t.Fatal("opcode-only should match")
	}
	// wrong opcode
	if matchInstr(ins, patToken{opcode: "subi"}, map[string]string{}) {
		t.Fatal("wrong opcode should not match")
	}
	// "_" wildcards each operand; count must still match
	if !matchInstr(ins, patToken{opcode: "addi", operands: []string{"_", "_", "_"}}, map[string]string{}) {
		t.Fatal("all-wildcard should match")
	}
	if matchInstr(ins, patToken{opcode: "addi", operands: []string{"_", "_"}}, map[string]string{}) {
		t.Fatal("operand count mismatch should fail")
	}
	// consistency variable binds, then must stay consistent
	vars := map[string]string{}
	if !matchInstr(asmInstr{opcode: "or", operands: []string{"r5", "r5"}}, patToken{opcode: "or", operands: []string{"x", "x"}}, vars) {
		t.Fatal("x=r5 twice should match")
	}
	if vars["x"] != "r5" {
		t.Fatalf("x should bind r5, got %q", vars["x"])
	}
	if matchInstr(asmInstr{opcode: "or", operands: []string{"r5", "r6"}}, patToken{opcode: "or", operands: []string{"x", "x"}}, map[string]string{}) {
		t.Fatal("x=r5 then x=r6 should fail")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run TestMatchInstr ./...`
Expected: FAIL — `undefined: matchInstr`.

- [ ] **Step 3: Write minimal implementation**

Append to `opseq.go`:

```go
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run TestMatchInstr ./...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): single-instruction matcher with operand vars"
```

---

## Task 5: Component 1 — best-alignment pattern matcher

**Files:**
- Modify: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Append to `opseq_test.go`:

```go
func instrs(ops ...string) []asmInstr {
	out := make([]asmInstr, len(ops))
	for i, op := range ops {
		out[i] = asmInstr{opcode: op, srcLine: i + 1}
	}
	return out
}

func TestMatchPattern(t *testing.T) {
	body := instrs("lfs", "mr", "mr", "fsubs", "bne") // gap of 2 between lfs and fsubs

	// exact gap window matches
	pat, _ := parsePattern([]string{"lfs", "*{0..3}", "fsubs", "bne"}, 6)
	a := matchPattern(body, pat)
	if !a.ok {
		t.Fatal("should match")
	}
	if a.slackConsumed != 2 {
		t.Fatalf("slack: want 2, got %d", a.slackConsumed)
	}
	if a.startSrcLine != 1 || a.endSrcLine != 5 {
		t.Fatalf("span: %d-%d", a.startSrcLine, a.endSrcLine)
	}

	// too-tight gap window fails
	tight, _ := parsePattern([]string{"lfs", "*{0..1}", "fsubs", "bne"}, 6)
	if matchPattern(body, tight).ok {
		t.Fatal("gap of 2 should not fit in *{0..1}")
	}
}

func TestMatchPatternPrefersTightest(t *testing.T) {
	// "a ... a b": pattern a,*{0..5},b can align from index 0 (slack 2) or index 2 (slack 0).
	body := instrs("a", "x", "a", "b")
	pat, _ := parsePattern([]string{"a", "*{0..5}", "b"}, 6)
	a := matchPattern(body, pat)
	if !a.ok {
		t.Fatal("should match")
	}
	if a.slackConsumed != 0 {
		t.Fatalf("should pick tightest alignment (slack 0), got %d", a.slackConsumed)
	}
	if a.startSrcLine != 3 {
		t.Fatalf("tightest start is line 3, got %d", a.startSrcLine)
	}
}

func TestMatchPatternVarNoLeak(t *testing.T) {
	// First "or" binds x; a failed candidate must not leak x to the winning path.
	body := []asmInstr{
		{opcode: "or", operands: []string{"r9", "r9"}, srcLine: 1}, // x=r9 would fail at next
		{opcode: "or", operands: []string{"r5", "r5"}, srcLine: 2}, // x=r5 path that should win
		{opcode: "and", operands: []string{"r5", "r5"}, srcLine: 3},
	}
	// pattern: or x x , and x x   (x must be consistent within an alignment)
	pat, _ := parsePattern([]string{"or x x", "and x x"}, 6)
	a := matchPattern(body, pat)
	if !a.ok {
		t.Fatal("alignment from line 2 (x=r5) should succeed")
	}
	if a.startSrcLine != 2 {
		t.Fatalf("want start line 2, got %d", a.startSrcLine)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run TestMatchPattern ./...`
Expected: FAIL — `undefined: matchPattern`.

- [ ] **Step 3: Write minimal implementation**

Append to `opseq.go` (add `"sort"` to the import block):

```go
// alignment is the result of matching a pattern within one function body.
type alignment struct {
	ok            bool
	slackConsumed int // total instructions absorbed by gaps
	startSrcLine  int
	endSrcLine    int
	lastIdx       int // internal: index of the last matched instruction
	bindings      map[string]string
}

// matchPattern returns the tightest (minimum slack) alignment of pat anywhere in
// instrs, or ok=false if none. One result per body (overlapping starts collapse
// to the single best alignment). pat[0] and pat[last] are concrete (guaranteed
// by parsePattern).
func matchPattern(instrs []asmInstr, pat []patToken) alignment {
	memo := map[string]alignment{}
	var best alignment
	for start := range instrs {
		res := solve(instrs, pat, start, 0, map[string]string{}, memo)
		if !res.ok {
			continue
		}
		res.startSrcLine = instrs[start].srcLine
		res.endSrcLine = instrs[res.lastIdx].srcLine
		if !best.ok || res.slackConsumed < best.slackConsumed {
			best = res
		}
	}
	return best
}

// solve returns the best completion of pat[pi:] starting at instrs[ii] under the
// given bindings. Memoized by (ii, pi, binding-signature). vars is never mutated:
// concrete tokens clone before attempting a candidate match.
func solve(instrs []asmInstr, pat []patToken, ii, pi int, vars map[string]string, memo map[string]alignment) alignment {
	if pi == len(pat) {
		return alignment{ok: true, lastIdx: ii - 1, bindings: cloneVars(vars)}
	}
	key := fmt.Sprintf("%d|%d|%s", ii, pi, varSig(vars))
	if m, ok := memo[key]; ok {
		return m
	}
	var best alignment
	tok := pat[pi]
	if tok.isGap {
		maxG := tok.gapMax
		if rem := len(instrs) - ii; maxG > rem {
			maxG = rem
		}
		for g := tok.gapMin; g <= maxG; g++ {
			res := solve(instrs, pat, ii+g, pi+1, vars, memo)
			if res.ok {
				res.slackConsumed += g
				if !best.ok || res.slackConsumed < best.slackConsumed {
					best = res
				}
			}
		}
	} else if ii < len(instrs) {
		v2 := cloneVars(vars)
		if matchInstr(instrs[ii], tok, v2) {
			best = solve(instrs, pat, ii+1, pi+1, v2, memo)
		}
	}
	memo[key] = best
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
```

The import block at the top of `opseq.go` becomes:

```go
import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run TestMatchPattern ./...`
Expected: PASS (all three `TestMatchPattern*` tests).

- [ ] **Step 5: Run the full suite so far**

Run: `cd tools/table-typer && go test ./...`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): best-alignment gap matcher (memoized, var-safe)"
```

---

## Task 6: Result ranking helper + function-boundary test

**Files:**
- Modify: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Append to `opseq_test.go`:

```go
func TestSortResults(t *testing.T) {
	in := []opseqResult{
		{fnName: "big_loose", slack: 3, size: 10},
		{fnName: "small_tight", slack: 0, size: 200},
		{fnName: "tie_small", slack: 1, size: 4},
		{fnName: "tie_big", slack: 1, size: 99},
	}
	sortResults(in)
	got := []string{in[0].fnName, in[1].fnName, in[2].fnName, in[3].fnName}
	want := []string{"small_tight", "tie_small", "tie_big", "big_loose"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("order: got %v want %v", got, want)
		}
	}
}

func TestMatchDoesNotCrossFunctionBoundary(t *testing.T) {
	// "blr" ends fn_a; "lfs" begins fn_b. A pattern spanning both must not match
	// because matchPattern is only ever called per-body.
	funcs := parseAsmFile(sampleAsm)
	pat, _ := parsePattern([]string{"blr", "*{0..4}", "fsubs"}, 6)
	for _, f := range funcs {
		if matchPattern(f.instrs, pat).ok {
			t.Fatalf("pattern should not match within a single body (%s)", f.name)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run 'TestSortResults|TestMatchDoesNotCross' ./...`
Expected: FAIL — `undefined: opseqResult` / `undefined: sortResults`.

- [ ] **Step 3: Write minimal implementation**

Append to `opseq.go`:

```go
// opseqResult is one ranked match for display.
type opseqResult struct {
	asmLoc string // "path/to/file.s:LINE"
	fnName string
	slack  int
	size   int
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run 'TestSortResults|TestMatchDoesNotCross' ./...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): result ranking by slack then size"
```

---

## Task 7: Component 3 — derive-from-target heuristic

**Files:**
- Modify: `tools/table-typer/opseq.go`
- Test: `tools/table-typer/opseq_test.go`

- [ ] **Step 1: Write the failing test**

Append to `opseq_test.go`:

```go
func TestIsControlFlow(t *testing.T) {
	for _, op := range []string{"b", "bl", "beq", "bne", "bdnz", "bctr", "blr", "mtctr", "mtlr", "beq+", "bne-"} {
		if !isControlFlow(op) {
			t.Fatalf("%q should be control-flow", op)
		}
	}
	for _, op := range []string{"addi", "lfs", "stw", "fsubs"} {
		if isControlFlow(op) {
			t.Fatalf("%q should not be control-flow", op)
		}
	}
}

func TestDerivePattern(t *testing.T) {
	// lfs is rare (freq 1), addi is common (freq 100); bne is control-flow.
	body := instrs("lfs", "addi", "addi", "bne")
	freq := map[string]int{"lfs": 1, "addi": 100, "bne": 50}
	toks, warn := derivePattern(body, freq, deriveOpts{slack: 2, maxLandmarks: 12})

	// Control-flow (bne) kept; rarest non-CF (lfs) kept; common addi dropped to gap.
	joined := strings.Join(toks, ",")
	if !strings.Contains(joined, "lfs") || !strings.Contains(joined, "bne") {
		t.Fatalf("expected lfs and bne as landmarks: %q", joined)
	}
	if strings.Contains(joined, "addi") {
		t.Fatalf("common addi should have been gapped out: %q", joined)
	}
	if !strings.Contains(joined, "*{0..") {
		t.Fatalf("expected a gap token between landmarks: %q", joined)
	}
	if warn != "" {
		t.Fatalf("rare lfs present: expected no broad-pattern warning, got %q", warn)
	}
}

func TestDeriveSpecificityGuardWarns(t *testing.T) {
	// All ops are common control-flow: no rare non-CF landmark -> warning.
	body := instrs("cmpwi", "beq", "bl", "b")
	freq := map[string]int{"cmpwi": 5000, "beq": 6000, "bl": 9000, "b": 9000}
	_, warn := derivePattern(body, freq, deriveOpts{slack: 2, maxLandmarks: 12})
	if warn == "" {
		t.Fatal("expected a broad-pattern warning")
	}
}

func TestDeriveWithOperands(t *testing.T) {
	body := []asmInstr{
		{opcode: "lwz", operands: []string{"r3", "0x4(r31)"}, srcLine: 1},
		{opcode: "blr", srcLine: 2},
	}
	freq := map[string]int{"lwz": 1, "blr": 1}
	toks, _ := derivePattern(body, freq, deriveOpts{slack: 1, maxLandmarks: 12, withOperands: true})
	// lwz's register operand becomes a consistency variable; the displacement becomes "_".
	if !strings.HasPrefix(toks[0], "lwz ") {
		t.Fatalf("token0 should carry operands: %q", toks[0])
	}
	if strings.Contains(toks[0], "0x4(r31)") {
		t.Fatalf("displacement should be replaced by _: %q", toks[0])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/table-typer && go test -run 'TestIsControlFlow|TestDerive' ./...`
Expected: FAIL — `undefined: isControlFlow` / `undefined: derivePattern` / `undefined: deriveOpts`.

- [ ] **Step 3: Write minimal implementation**

Append to `opseq.go` (add `"regexp"` to the import block):

```go
// broadLandmarkFreq: if the rarest landmark occurs more often than this in the
// corpus, the derived pattern is considered broad and a warning is emitted.
const broadLandmarkFreq = 150

var registerRe = regexp.MustCompile(`^([rf][0-9]+|cr[0-7])$`)

var controlFlowOps = map[string]bool{
	"b": true, "ba": true, "bl": true, "bla": true,
	"beq": true, "bne": true, "blt": true, "ble": true, "bgt": true, "bge": true,
	"bso": true, "bns": true, "bdnz": true, "bdz": true,
	"bctr": true, "bctrl": true, "blr": true, "blrl": true,
	"mtctr": true, "mtlr": true,
}

// isControlFlow reports whether opcode is a branch/structural op kept as an
// anchor. Branch-prediction hints (beq+, bne-) are stripped first.
func isControlFlow(opcode string) bool {
	return controlFlowOps[strings.TrimRight(opcode, "+-")]
}

type deriveOpts struct {
	slack        int
	maxLandmarks int
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
// variables (a, b, c, …) and everything else becomes "_".
func landmarkToken(ins asmInstr, withOperands bool, regVars map[string]string) string {
	if !withOperands || len(ins.operands) == 0 {
		return ins.opcode
	}
	parts := []string{ins.opcode}
	for _, op := range ins.operands {
		if registerRe.MatchString(op) {
			v, ok := regVars[op]
			if !ok {
				v = string(rune('a' + len(regVars)))
				regVars[op] = v
			}
			parts = append(parts, v)
		} else {
			parts = append(parts, "_")
		}
	}
	return strings.Join(parts, " ")
}
```

The import block at the top of `opseq.go` becomes:

```go
import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools/table-typer && go test -run 'TestIsControlFlow|TestDerive' ./...`
Expected: PASS (all `TestDerive*` and `TestIsControlFlow`).

- [ ] **Step 5: Run the full suite**

Run: `cd tools/table-typer && go test ./...`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): control-flow-anchored + rarity derive heuristic"
```

---

## Task 8: Wire flags and rewrite the `cmdOpSeq` handler

**Files:**
- Modify: `tools/table-typer/main.go` (flag registration near lines 33-34; handler body lines ~343-463)

This task has no new unit test (it is IO/CLI wiring over already-tested pure functions); it is verified by `go build` and a manual smoke run. The pure logic it calls is covered by Tasks 1–7.

- [ ] **Step 1: Register the new flags**

In `main.go`, find (around line 33-34):

```go
	cmdOpSeq := flagg.New("opseq", "Search for a sequence of opcodes")
	cmdOpSeq.BoolVar(&seqCandidates, "candidates", false, "list non-matching candidates instead of matching functions")
```

Replace with:

```go
	cmdOpSeq := flagg.New("opseq", "Search for a sequence of opcodes")
	cmdOpSeq.BoolVar(&seqCandidates, "candidates", false, "list non-matching candidates instead of matching functions")
	var likeTarget string
	var gapCap, deriveSlack, maxLandmarks int
	var withOperands bool
	cmdOpSeq.StringVar(&likeTarget, "like", "", "derive a gap pattern from <func>[:start-end] instead of taking a pattern arg")
	cmdOpSeq.IntVar(&gapCap, "gap-cap", 6, "default max instructions a bare '*' gap may span")
	cmdOpSeq.IntVar(&deriveSlack, "slack", 2, "extra gap tolerance added when deriving (--like)")
	cmdOpSeq.IntVar(&maxLandmarks, "max-landmarks", 12, "target landmark count when deriving (--like)")
	cmdOpSeq.BoolVar(&withOperands, "with-operands", false, "include register operands as consistency vars when deriving (--like)")
```

- [ ] **Step 2: Replace the `case cmdOpSeq:` body**

In `main.go`, replace the entire `case cmdOpSeq:` block (from `case cmdOpSeq:` through the closing of its `for _, res := range results { … }` loop, currently lines ~343-463) with:

```go
	case cmdOpSeq:
		report := loadReport(rootDir)

		// Build the normalized model once: located function bodies + frequency.
		type locatedFunc struct {
			file string
			fn   asmFunc
		}
		var all []locatedFunc
		var modelFuncs []asmFunc
		for _, path := range asmFiles {
			content, err := os.ReadFile(path)
			if err != nil {
				log.Fatalln("Failed to read file:", path, err)
			}
			for _, fn := range parseAsmFile(string(content)) {
				all = append(all, locatedFunc{file: path, fn: fn})
				modelFuncs = append(modelFuncs, fn)
			}
		}

		// Determine the pattern tokens: either derived (--like) or from the arg.
		var tokens []string
		if likeTarget != "" {
			if cmd.NArg() != 0 {
				log.Fatalln("--like takes no positional pattern argument")
			}
			name, lo, hi := parseLikeTarget(likeTarget)
			var target *asmFunc
			for i := range all {
				if all[i].fn.name == name {
					target = &all[i].fn
					break
				}
			}
			if target == nil {
				log.Fatalf("function %q not found in asm", name)
			}
			body := target.instrs
			if lo > 0 || hi > 0 {
				var sub []asmInstr
				for _, ins := range body {
					if ins.srcLine >= lo && ins.srcLine <= hi {
						sub = append(sub, ins)
					}
				}
				if len(sub) == 0 {
					log.Fatalf("line range %d-%d selects no instructions in %q", lo, hi, name)
				}
				body = sub
			}
			freq := opcodeFrequencies(modelFuncs)
			var warn string
			tokens, warn = derivePattern(body, freq, deriveOpts{slack: deriveSlack, maxLandmarks: maxLandmarks, withOperands: withOperands})
			fmt.Printf("derived pattern: %s\n", strings.Join(tokens, ","))
			if warn != "" {
				fmt.Printf("warning: %s\n", warn)
			}
		} else {
			if cmd.NArg() != 1 {
				if cmd.NArg() > 1 {
					log.Fatalln("opseq takes a single pattern argument — did the shell expand it? Quote it, e.g. opseq 'lfs,*{0..3},fsubs'")
				}
				cmd.Usage()
				return
			}
			arg := cmd.Arg(0)
			if content, err := os.ReadFile(arg); err == nil {
				for _, line := range strings.Split(strings.TrimSpace(string(content)), "\n") {
					tokens = append(tokens, line)
				}
			} else {
				tokens = strings.Split(arg, ",")
			}
		}

		pat, err := parsePattern(tokens, gapCap)
		if err != nil {
			log.Fatalln("invalid pattern:", err)
		}

		var results []opseqResult
		for _, lf := range all {
			if seqCandidates == report.isMatched(lf.fn.name) {
				continue
			}
			a := matchPattern(lf.fn.instrs, pat)
			if !a.ok {
				continue
			}
			results = append(results, opseqResult{
				asmLoc: fmt.Sprintf("%s:%d", lf.file, a.startSrcLine),
				fnName: lf.fn.name,
				size:   report.size(lf.fn.name),
				slack:  a.slackConsumed,
			})
		}
		sortResults(results)
		for _, res := range results {
			fmt.Printf("%s %s\n", res.asmLoc, locateFuncDef(res.fnName))
		}
```

Note: `locateFuncDef` is a closure defined earlier in the original handler. Keep its definition (move it above this block if needed); it is unchanged. If the compiler reports `locateFuncDef` unused-or-undefined after the rewrite, ensure its `func locateFuncDef(name string) string { … }` definition (original lines ~407-439) remains present above the result loop.

- [ ] **Step 3: Add the `parseLikeTarget` helper to `opseq.go`**

Append to `opseq.go`:

```go
// parseLikeTarget splits "<func>" or "<func>:lo-hi" into the name and an
// inclusive absolute asm-line range (0,0 when no range is given).
func parseLikeTarget(s string) (name string, lo, hi int) {
	name = s
	if i := strings.LastIndexByte(s, ':'); i >= 0 {
		name = s[:i]
		if a, b, ok := strings.Cut(s[i+1:], "-"); ok {
			lo, _ = strconv.Atoi(strings.TrimSpace(a))
			hi, _ = strconv.Atoi(strings.TrimSpace(b))
		}
	}
	return name, lo, hi
}
```

- [ ] **Step 4: Add a test for `parseLikeTarget`**

Append to `opseq_test.go`:

```go
func TestParseLikeTarget(t *testing.T) {
	n, lo, hi := parseLikeTarget("fn_foo")
	if n != "fn_foo" || lo != 0 || hi != 0 {
		t.Fatalf("plain: %q %d %d", n, lo, hi)
	}
	n, lo, hi = parseLikeTarget("fn_foo:120-145")
	if n != "fn_foo" || lo != 120 || hi != 145 {
		t.Fatalf("ranged: %q %d %d", n, lo, hi)
	}
}
```

- [ ] **Step 5: Build and run the full test suite**

Run: `cd tools/table-typer && go build ./... && go test ./...`
Expected: build succeeds; all tests PASS.

- [ ] **Step 6: Manual smoke test against a real build**

This requires built asm. Run from the worktree root:

```bash
python tools/worktree-doctor.py --fix   # only if build/ is missing orig inputs
python configure.py && ninja
cd tools/table-typer && go run . opseq 'lfs,*{0..3},fsubs'
```

Expected: prints zero or more `path.s:LINE src.c:LINE` lines, no crash. Then:

```bash
go run . opseq --like pl_80037B2C
```

Expected: prints a `derived pattern: …` line (comma-separated landmarks with `*{0..N}` gaps) followed by ranked matches.

- [ ] **Step 7: Commit**

```bash
git add tools/table-typer/main.go tools/table-typer/opseq.go tools/table-typer/opseq_test.go
git commit -m "feat(opseq): wire gap matching + --like derive into the CLI"
```

---

## Task 9: Documentation + capability index

**Files:**
- Modify: `.claude/skills/opseq/SKILL.md`

- [ ] **Step 1: Document gap tokens and `--like`**

In `.claude/skills/opseq/SKILL.md`, add a section after the existing "## Usage" examples (and update the Tips section to mention quoting). Insert:

````markdown
## Gap-tolerant patterns

Tokens are comma-separated. Between landmarks you can insert a **bounded gap** to
tolerate scheduler/register noise. Quote the pattern — `*`, `?`, and `{}` are
shell metacharacters:

```bash
melee-agent opseq 'lfs,*{0..3},fsubs,bne'   # up to 3 instructions between lfs and fsubs
melee-agent opseq 'cmplwi,*,bne'            # bare * = up to --gap-cap (default 6)
melee-agent opseq 'mtctr,?,bctr'            # ? = exactly one instruction
```

Rules: bounds use `..` (not a comma); the upper bound is capped at 32; a pattern
must begin and end with a real opcode (no leading/trailing gap). Results are
ranked tightest-match-first.

## Derive a pattern from a function (`--like`)

Stop hand-authoring. Point `--like` at a function (optionally a line range) and
opseq derives an editable, gap-tolerant pattern — keeping control-flow anchors
(loops/returns/switches) plus the rarest distinctive ops, gapping out filler:

```bash
melee-agent opseq --like fn_80247510
melee-agent opseq --like fn_80247510:80247540-80247590   # just the stuck region
melee-agent opseq --like fn_80247510 --with-operands     # also bind register-reuse
```

Flags: `--gap-cap N` (bare `*` width, default 6), `--slack N` (derive tolerance,
default 2), `--max-landmarks N` (default 12), `--with-operands`. The derived
pattern is printed so you can tweak it and re-run it manually.
````

- [ ] **Step 2: Update the Tips section to require quoting**

In the same file, in the "## Tips" list, add:

```markdown
- Always single-quote patterns that contain `*`, `?`, or `{}` so the shell does
  not expand them: `melee-agent opseq 'lfs,*{0..3},fsubs'`.
```

- [ ] **Step 3: Regenerate the capability index**

Run: `melee-agent capabilities generate`
Expected: regenerates the capability brief/index; `git status` shows the index file(s) changed (if any).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/opseq/SKILL.md
git add -A   # include any regenerated capability index files
git commit -m "docs(opseq): document gap tokens, --like, and shell quoting"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage:**
- Component 0 (normalized model) → Task 1. ✔
- Component 1 (gap matcher: tokens, ceiling, no leading/trailing gap, best-alignment, vars clone, memo) → Tasks 3, 4, 5. ✔
- Component 2 (frequency) → Task 2. ✔
- Component 3 (derive: control-flow anchors, rarity fill, cap precedence, specificity guard, `--with-operands`, range) → Tasks 7, 8. ✔
- Component 4 (ranking by slack then size; one result per function) → Task 6 + Task 8 wiring. ✔
- Function-boundary safety → Task 6 test + Task 8 per-body matching. ✔
- CLI surface + shell guard → Task 8. ✔
- Docs + capabilities → Task 9. ✔

**Placeholder scan:** No TBD/TODO; every code step shows full code; every command shows expected output.

**Type consistency:** `asmInstr`/`asmFunc` (Task 1) reused everywhere; `patToken` (Task 3) consumed by `matchInstr` (Task 4) and `solve`/`matchPattern` (Task 5); `alignment.slackConsumed`/`startSrcLine`/`endSrcLine` (Task 5) consumed by Task 8 wiring; `opseqResult`/`sortResults` (Task 6) consumed by Task 8; `deriveOpts`/`derivePattern` (Task 7) consumed by Task 8; `parseLikeTarget` (Task 8). Names are consistent across tasks.
