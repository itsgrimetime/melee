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
