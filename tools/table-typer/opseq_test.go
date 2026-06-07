package main

import (
	"strings"
	"testing"
)

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
	if len(funcs[1].instrs) < 2 {
		t.Fatalf("fn_b want >=2 instrs, got %d", len(funcs[1].instrs))
	}
	if funcs[1].instrs[1].opcode != "fsubs" {
		t.Fatalf("fn_b[1] opcode: %q", funcs[1].instrs[1].opcode)
	}
}

func TestParseAsmFileEmpty(t *testing.T) {
	if got := parseAsmFile(""); len(got) != 0 {
		t.Fatalf("empty content: want 0 funcs, got %d", len(got))
	}
	if got := parseAsmFile(".text\n.balign 4\n"); len(got) != 0 {
		t.Fatalf("no-fn content: want 0 funcs, got %d", len(got))
	}
}

func TestOpcodeFrequencies(t *testing.T) {
	funcs := parseAsmFile(sampleAsm)
	freq := opcodeFrequencies(funcs)
	// fn_a: mflr, stw, li, blr ; fn_b: lfs, fsubs
	if freq["mflr"] != 1 || freq["stw"] != 1 || freq["li"] != 1 || freq["blr"] != 1 ||
		freq["lfs"] != 1 || freq["fsubs"] != 1 {
		t.Fatalf("freq: %v", freq)
	}
	if freq["nonexistent"] != 0 {
		t.Fatalf("missing opcode should be 0, got %d", freq["nonexistent"])
	}
}

func TestParseAsmFileSkipsDataAndComments(t *testing.T) {
	const asm = `.fn fn_c, global
/* 80000000 00000000  39 00 00 00 */	li r8, 0x0
/* 80000004 00000004  43 00 00 00 */	.4byte 0x43000000 /* illegal */
/* 80000008 00000008  4E 80 00 20 */	blr /* return */
.endfn fn_c
`
	funcs := parseAsmFile(asm)
	if len(funcs) != 1 || len(funcs[0].instrs) != 2 {
		t.Fatalf("want 2 instrs (.4byte data line skipped), got %d", len(funcs[0].instrs))
	}
	if funcs[0].instrs[0].opcode != "li" || funcs[0].instrs[1].opcode != "blr" {
		t.Fatalf("opcodes: %v", funcs[0].instrs)
	}
	// trailing "/* return */" comment must not leak into operands
	if len(funcs[0].instrs[1].operands) != 0 {
		t.Fatalf("blr should have no operands, got %v", funcs[0].instrs[1].operands)
	}
}

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
	// open upper bound uses the ceiling
	open, _ := parsePattern([]string{"a", "*{5..}", "b"}, 6)
	if open[1].gapMin != 5 || open[1].gapMax != 32 {
		t.Fatalf("open upper: %+v", open[1])
	}
	// operand-bearing concrete token (space-separated operands)
	op, _ := parsePattern([]string{"addi x y _"}, 6)
	if op[0].opcode != "addi" || len(op[0].operands) != 3 || op[0].operands[0] != "x" || op[0].operands[2] != "_" {
		t.Fatalf("operands: %+v", op[0])
	}
	// trailing commas are stripped from operands
	cs, _ := parsePattern([]string{"addi r3, r4, r5"}, 6)
	if len(cs[0].operands) != 3 || cs[0].operands[1] != "r4" {
		t.Fatalf("comma strip: %+v", cs[0])
	}
}

func TestParsePatternErrors(t *testing.T) {
	cases := [][]string{
		{"*", "lfs"},             // leading gap
		{"lfs", "*"},             // trailing gap
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
	// Within ONE start, the first gap branch (g=0) tries "or x x" against
	// "or r5,r6": matchInstr binds x=r5 on operand 0, then fails on operand 1.
	// The second gap branch (g=1) must see x UNBOUND so "or r9,r9" can match.
	// A matcher that mutates a shared vars map (no clone-per-candidate) leaks
	// x=r5 and wrongly fails the whole pattern. This single-start backtracking
	// case is what actually exercises the spec's correctness-critical invariant.
	body := []asmInstr{
		{opcode: "mflr", srcLine: 1},
		{opcode: "or", operands: []string{"r5", "r6"}, srcLine: 2}, // partial-bind then fail
		{opcode: "or", operands: []string{"r9", "r9"}, srcLine: 3}, // clean path must win
	}
	pat, _ := parsePattern([]string{"mflr", "*{0..1}", "or x x"}, 6)
	a := matchPattern(body, pat)
	if !a.ok {
		t.Fatal("should match via the second gap branch (x=r9)")
	}
	if a.endSrcLine != 3 || a.slackConsumed != 1 {
		t.Fatalf("want end line 3 slack 1, got end %d slack %d", a.endSrcLine, a.slackConsumed)
	}
}

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
	toks, warn := derivePattern(body, freq, deriveOpts{slack: 2, maxLandmarks: 2})

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
	// cmpwi is a non-CF landmark but very common (freq 5000 >> broadLandmarkFreq 150),
	// so the pattern lacks a sufficiently-rare landmark and must warn.
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
	if len(toks) != 3 {
		t.Fatalf("expected 3 tokens (landmark, gap, cf-anchor), got %d: %v", len(toks), toks)
	}
	if !strings.Contains(toks[1], "*{0..") {
		t.Fatalf("token1 should be a gap: %q", toks[1])
	}
	if toks[2] != "blr" {
		t.Fatalf("token2 should be the blr anchor: %q", toks[2])
	}
}
