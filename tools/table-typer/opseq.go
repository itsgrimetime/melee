package main

import "strings"

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
