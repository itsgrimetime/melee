package main

import (
	"fmt"
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
