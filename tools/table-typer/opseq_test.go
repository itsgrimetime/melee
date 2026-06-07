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
