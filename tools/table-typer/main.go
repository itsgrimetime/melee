package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"

	"lukechampine.com/flagg"
)

func main() {
	log.SetFlags(0)
	var typeName string
	var fix bool
	var conservative, seqCandidates bool
	root := flagg.Root
	cmdFindFns := flagg.New("findfns", "Find function types to fix")
	cmdFindFns.StringVar(&typeName, "type", "", "Enumerate functions in tables with a known type")
	cmdFindFns.BoolVar(&fix, "fix", false, "Immediately apply fixes instead of listing them")
	cmdFixFns := flagg.New("fixfns", "Fix function types")
	cmdFixFns.BoolVar(&conservative, "conservative", false, "only fix UNK_RET/UNK_PARAMS functions")
	cmdRename := flagg.New("rename", "Rename anonymous functions based on hardcoded patterns")
	cmdRename.StringVar(&typeName, "type", "", "type of struct to derive names from")
	cmdUnk := flagg.New("unk", "Search for UNK_RET functions in asm data")
	cmdOpSeq := flagg.New("opseq", "Search for a sequence of opcodes")
	cmdOpSeq.BoolVar(&seqCandidates, "candidates", false, "list non-matching candidates instead of matching functions")
	var likeTarget string
	var gapCap, deriveSlack, maxLandmarks int
	var withOperands bool
	cmdOpSeq.StringVar(&likeTarget, "like", "", "derive a gap pattern from <func>[:start-end] instead of taking a pattern arg")
	cmdOpSeq.IntVar(&gapCap, "gap-cap", 6, "default max instructions a bare '*' gap may span (clamped to 32)")
	cmdOpSeq.IntVar(&deriveSlack, "slack", 2, "extra gap tolerance added when deriving (--like)")
	cmdOpSeq.IntVar(&maxLandmarks, "max-landmarks", 12, "target landmark count when deriving (--like)")
	cmdOpSeq.BoolVar(&withOperands, "with-operands", false, "include register operands as consistency vars when deriving (--like)")
	cmdDups := flagg.New("dups", "Find duplicated functions")
	cmd := flagg.Parse(flagg.Tree{
		Cmd: root,
		Sub: []flagg.Tree{
			{Cmd: cmdFindFns},
			{Cmd: cmdFixFns},
			{Cmd: cmdRename},
			{Cmd: cmdUnk},
			{Cmd: cmdOpSeq},
			{Cmd: cmdDups},
		},
	})

	// locate root dir
	rootDir := "."
	for i := 0; ; i++ {
		if _, err := os.Stat(filepath.Join(rootDir, "src", "melee")); err == nil {
			break
		} else if i > 10 {
			log.Fatalln("Failed to locate root directory. Please run this tool within the project directory.")
		}
		rootDir = filepath.Join(rootDir, "..")
	}

	// parse source and asm files
	srcDir := filepath.Join(rootDir, "src", "melee")
	hFiles := findFiles(srcDir, ".h")
	cFiles := findFiles(srcDir, ".c")
	if len(hFiles)+len(cFiles) == 0 {
		log.Fatalln("No source files found in", rootDir)
	}
	asmDir := filepath.Join(rootDir, "build", "GALE01", "asm", "melee")
	asmFiles := findFiles(asmDir, ".s")
	if len(asmFiles) == 0 {
		log.Fatalln("No asm files found in", asmDir)
	}
	tables := extractAsmTables(asmFiles)

	visitStructs := func(typeName string, st CStructType, fn func(string, string, int, *CStructValue)) {
		for _, path := range append(hFiles, cFiles...) {
			for _, name := range parseTableDecls(path, typeName) {
				if tab, ok := tables[name]; ok && len(tab)%len(st.Fields) == 0 {
					for index := range len(tab) / len(st.Fields) {
						sv := st.New().(*CStructValue)
						if sv.parse(tab[index*len(st.Fields):][:len(st.Fields)]) {
							fn(path, name, index, sv)
						}
					}
				}
			}
		}
	}
	runTypes := func(typeName string, fn func(string, CStructType)) {
		switch typeName {
		case "":
			fmt.Println("No type specified. Available types:")
			for name := range structTypes {
				fmt.Println(" -", name)
			}
		case "all":
			for name, typ := range structTypes {
				fn(name, typ)
			}
		default:
			tableType, ok := structTypes[typeName]
			if !ok {
				log.Fatalf("Unknown type: %s", typeName)
			}
			fn(typeName, tableType)
		}
	}
	applyRewrites := func(fnTypes map[string]*CFuncValue) {
		fmt.Println("Identified", len(fnTypes), "candidate functions for updating.")
		if len(fnTypes) == 0 {
			fmt.Println("Nothing to do, exiting.")
			return
		}
		totalSigs := 0
		totalFiles := 0
		for _, path := range append(hFiles, cFiles...) {
			fmt.Printf("\rChecking %-70v", path[:min(57, len(path))]+"...")
			sigs := fixSignatures(path, fnTypes, conservative)
			totalSigs += sigs
			if sigs > 0 {
				totalFiles++
				s := "es"
				if sigs == 1 {
					s = ""
				}
				fmt.Printf("%3d fix%s\n", sigs, s)
			}
		}
		fmt.Println()
		fmt.Printf("Fixed %v signatures across %v source files.\n", totalSigs, totalFiles)
	}

	switch cmd {
	case cmdFindFns:
		if cmd.NArg() != 0 {
			cmd.Usage()
			return
		}
		runTypes(typeName, func(typeName string, st CStructType) {
			fnTypes := make(map[string]*CFuncValue)
			visitStructs(typeName, st, func(path, name string, index int, sv *CStructValue) {
				for _, f := range sv.Fields {
					if fn, ok := f.(*CFuncValue); ok {
						fnTypes[fn.Name] = fn
					}
				}
			})
			if fix {
				applyRewrites(fnTypes)
			} else {
				var lines []string
				for name, fn := range fnTypes {
					lines = append(lines, fmt.Sprintf("%s: %s", name, fn))
				}
				sort.Strings(lines)
				for _, line := range lines {
					fmt.Println(line)
				}
			}
		})

	case cmdFixFns:
		if cmd.NArg() != 1 {
			cmd.Usage()
			return
		}
		fixList, err := os.ReadFile(cmd.Arg(0))
		if err != nil {
			log.Fatal(err)
		}
		fnTypes := make(map[string]*CFuncValue)
		for _, line := range bytes.Split(fixList, []byte("\n")) {
			if line = bytes.TrimSpace(line); len(line) == 0 {
				continue
			}
			name, fixed, ok := bytes.Cut(line, []byte(": "))
			if !ok {
				log.Fatalf("Invalid format: %q", line)
			}
			fnTypes[string(name)] = parseCFuncValue(fixed)
		}
		applyRewrites(fnTypes)

	case cmdRename:
		if cmd.NArg() != 0 {
			cmd.Usage()
			return
		}

		canonicalPrefix := func(typeName string, path string) string {
			switch typeName {
			case "ItemStateTable":
				itKind := strings.TrimPrefix(strings.TrimSuffix(filepath.Base(path), filepath.Ext(path)), "it")
				itKind = strings.ToUpper(itKind[:1]) + itKind[1:]
				return fmt.Sprintf("it%s_UnkMotion", itKind)
			case "MinorScene":
				gmKind := strings.TrimPrefix(strings.TrimSuffix(filepath.Base(path), filepath.Ext(path)), "gm")
				gmKind = strings.ToUpper(gmKind[:1]) + gmKind[1:]
				return fmt.Sprintf("gm%s_UnkScene", gmKind)
			case "StageData":
				grKind := strings.TrimPrefix(strings.TrimSuffix(filepath.Base(path), filepath.Ext(path)), "gr")
				grKind = strings.ToUpper(grKind[:1]) + grKind[1:]
				return fmt.Sprintf("gr%s_UnkStage", grKind)
			case "ItemLogicTable":
				itKind := strings.TrimPrefix(strings.TrimSuffix(filepath.Base(path), filepath.Ext(path)), "it")
				itKind = strings.ToUpper(itKind[:1]) + itKind[1:]
				return fmt.Sprintf("it%s_Logic", itKind)
			default:
				panic("unhandled type: " + typeName)
			}
		}

		canonicalFieldNames := func(typeName string) []string {
			switch typeName {
			case "ItemStateTable":
				return []string{"", "Anim", "Phys", "Coll"}
			case "MinorScene":
				return []string{"", "Prep", "Decide"}
			case "StageData":
				return []string{"", "", "", "", "", "OnLoad", "OnStart", "", "", "", "", "", ""}
			case "ItemLogicTable":
				return []string{"", "Spawned", "Destroyed", "PickedUp", "Dropped", "Thrown", "DmgDealt", "DmgReceived", "EnteredAir", "Reflected", "Clanked", "Absorbed", "ShieldBounced", "HitShield", "EvtUnk"}
			default:
				panic("unhandled type: " + typeName)
			}
		}

		runTypes(typeName, func(typeName string, st CStructType) {
			renames := make(map[string]string)
			visitStructs(typeName, st, func(path, name string, index int, sv *CStructValue) {
				prefix := canonicalPrefix(typeName, path)
				fieldNames := canonicalFieldNames(typeName)
				for i, f := range sv.Fields {
					if fn, ok := f.(*CFuncValue); ok && fieldNames[i] != "" {
						renames[fn.Name] = fmt.Sprintf("%s%d_%s", prefix, index, fieldNames[i])
					}
				}
			})
			fmt.Println("Identified", len(renames), "functions to rename.")
			if len(renames) == 0 {
				fmt.Println("Nothing to do, exiting.")
				return
			}

			// if there are conflicts, skip all of them
			inv := make(map[string][]string)
			for k, v := range renames {
				inv[v] = append(inv[v], k)
			}
			for newName, oldNames := range inv {
				if len(oldNames) > 1 {
					fmt.Printf("Skipping %s (conflict: %v)\n", newName, oldNames)
					for _, oldName := range oldNames {
						delete(renames, oldName)
					}
				}
			}

			var replacePairs []string
			for oldName, newName := range renames {
				replacePairs = append(replacePairs, oldName, newName)
			}
			replacer := strings.NewReplacer(replacePairs...)

			totalFiles := 0
			renameFile := func(path string) {
				fmt.Printf("\rChecking %-70v", path[:min(57, len(path))]+"...")
				content, err := os.ReadFile(path)
				if err != nil {
					log.Fatalf("Failed to read file: %v", err)
				}
				contentStr := string(content)
				updated := replacer.Replace(contentStr)
				if updated != contentStr {
					if err := os.WriteFile(path, []byte(updated), 0644); err != nil {
						log.Fatalf("Failed to write file %s: %v", path, err)
					}
					fmt.Printf("\rUpdated %-70v\n", path[:min(57, len(path))])
					totalFiles++
				}
			}

			for _, path := range append(append(hFiles, cFiles...), asmFiles...) {
				renameFile(path)
			}
			renameFile(filepath.Join(rootDir, "config", "GALE01", "symbols.txt"))

			fmt.Println()
			if totalFiles > 0 {
				fmt.Printf("Renamed %d symbols in %d files.\n", len(renames), totalFiles)
			} else {
				fmt.Println("Nothing to rename.")
			}
		})

	case cmdUnk:
		if cmd.NArg() != 0 {
			cmd.Usage()
			return
		}
		fmt.Println("Found", len(tables), "asm tables in", asmDir)
		fnNames := make(map[string]string)
		for name, entries := range tables {
			for _, entry := range entries {
				if entry.Size != 4 {
					continue
				}
				fnNames[entry.Value] = name
			}
		}
		fmt.Println("Found", len(fnNames), "symbols in tables.")
		var tables []string
		seen := make(map[string]struct{})
		findUNKs := func(path string) (n int) {
			content, err := os.ReadFile(path)
			if err != nil {
				log.Fatalf("Failed to read file %s: %v", path, err)
			}
			for name := range fnNames {
				if bytes.Contains(content, fmt.Appendf(nil, "UNK_RET %s", name)) {
					if _, ok := seen[fnNames[name]]; !ok {
						tables = append(tables, fnNames[name])
						seen[fnNames[name]] = struct{}{}
						n++
					}
				}
			}
			return n
		}
		total := 0
		for _, path := range append(hFiles, cFiles...) {
			fmt.Printf("\rChecking %-70v", path[:min(57, len(path))]+"...")
			n := findUNKs(path)
			total += n
			if n > 0 {
				fmt.Printf("%3d found, %4d total\n", n, len(tables))
			}
		}
		sort.Strings(tables)
		fmt.Println("\nFound", len(tables), "asm tables with UNK_RET functions:")
		for _, name := range tables {
			fmt.Println(name)
		}

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
			name, lo, hi, err := parseLikeTarget(likeTarget)
			if err != nil {
				log.Fatalf("--like %q: %v", likeTarget, err)
			}
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
				// File input: treat newlines and commas equivalently so file and
				// inline patterns tokenize identically.
				arg = strings.ReplaceAll(strings.TrimSpace(string(content)), "\n", ",")
			}
			tokens = strings.Split(arg, ",")
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
				asmLoc:    fmt.Sprintf("%s:%d", lf.file, a.startSrcLine),
				fnName:    lf.fn.name,
				size:      report.size(lf.fn.name),
				slack:     a.slackConsumed,
				startLine: a.startSrcLine,
				endLine:   a.endSrcLine,
			})
		}
		sortResults(results)
		for _, res := range results {
			// Print the asm location + C definition, plus the matched span and gap
			// slack so the user can judge how tight each match is.
			fmt.Printf("%s %s [slack %d, lines %d-%d]\n",
				res.asmLoc, locateFuncDef(cFiles, res.fnName), res.slack, res.startLine, res.endLine)
		}

	case cmdDups:
		if cmd.NArg() > 1 {
			cmd.Usage()
			return
		}

		report := loadReport(rootDir)

		normBody := func(lines [][]byte) string {
			var sb strings.Builder
			for _, line := range lines {
				if bytes.HasPrefix(line, []byte(".endfn")) {
					break
				} else if bytes.HasPrefix(line, []byte(".L_")) {
					continue
				}
				_, line, _ = bytes.Cut(line, []byte("*/\t"))
				parts := bytes.Fields(line)
				if len(parts) == 0 {
					continue
				}
				sb.Write(parts[0])
				sb.WriteByte('\n')
			}
			return sb.String()
		}
		fns := make(map[string][]string)
		for _, path := range asmFiles {
			contents, err := os.ReadFile(path)
			if err != nil {
				log.Fatalln("Failed to read file:", path, err)
			}
			groups := bytes.Split(contents, []byte("\n.fn "))
			for _, group := range groups[1:] {
				lines := bytes.Split(group, []byte("\n"))
				name, _, _ := bytes.Cut(lines[0], []byte(","))
				body := normBody(lines[1:])
				fns[body] = append(fns[body], string(name))
			}
		}

		type fnBody struct {
			size       int
			refs       []string
			candidates []string
		}
		candBytes := func(b fnBody) int {
			return len(b.candidates) * b.size
		}
		var bodies []fnBody
		for _, names := range fns {
			var fb fnBody
			for _, name := range names {
				if report.isMatched(name) {
					fb.refs = append(fb.refs, name)
					fb.size = report.size(name)
				} else {
					fb.candidates = append(fb.candidates, name)
					fb.size = report.size(name)
				}
			}
			if len(fb.candidates) > 0 && (len(fb.refs) > 0 || len(fb.candidates) > 1) {
				bodies = append(bodies, fb)
			}
		}

		switch cmd.NArg() {
		case 0:
			sort.Slice(bodies, func(i, j int) bool {
				return candBytes(bodies[i]) > candBytes(bodies[j])
			})
			for _, body := range bodies {
				var name string
				if len(body.refs) > 0 {
					name = body.refs[0]
				} else if len(body.candidates) > 0 {
					name = body.candidates[0]
				}
				fmt.Printf("%v: %v matched, %v unmatched (+%.2f KB)\n", name, len(body.refs), len(body.candidates), float64(candBytes(body))/1024)
			}
		case 1:
			target := cmd.Arg(0)
			for _, body := range bodies {
				if slices.Contains(append(body.refs, body.candidates...), target) {
					for i := range body.refs {
						if body.refs[i] == target {
							body.refs = slices.Delete(body.refs, i, i+1)
							break
						}
					}
					for i := range body.candidates {
						if body.candidates[i] == target {
							body.candidates = slices.Delete(body.candidates, i, i+1)
							break
						}
					}
					if len(body.refs) > 0 {
						fmt.Println("Matched duplicates:", strings.Join(body.refs, ", "))
					}
					if len(body.candidates) > 0 {
						fmt.Println("Unmatched duplicates:", strings.Join(body.candidates, ", "))
					}
					return
				}
			}
			fmt.Printf("Function %q has no duplicates.\n", target)
		}
	}
}

func findFiles(dir string, ext string) []string {
	var files []string
	err := filepath.WalkDir(dir, func(path string, _ os.DirEntry, err error) error {
		if filepath.Ext(path) == ext {
			files = append(files, path)
		}
		return err
	})
	if err != nil {
		log.Fatalf("Error walking directory: %v", err)
	}
	return files
}

type AsmTableEntry struct {
	Size  int
	Value string
}

func extractAsmTables(paths []string) map[string][]AsmTableEntry {
	tables := make(map[string][]AsmTableEntry)
	for _, path := range paths {
		contents, err := os.ReadFile(path)
		if err != nil {
			log.Fatalln("Failed to read file:", path, err)
		}
		objects := bytes.Split(contents, []byte(".obj "))
		for _, object := range objects {
			if !bytes.Contains(object, []byte("byte")) {
				continue
			}
			lines := strings.Split(string(object), "\n")
			symbol, _, _ := strings.Cut(strings.TrimSpace(lines[0]), ",")
			var entries []AsmTableEntry
			for _, line := range lines[1:] {
				typ, val, _ := strings.Cut(strings.TrimSpace(line), " ")
				var size int
				switch typ {
				case ".byte":
					size = 1
				case ".2byte":
					size = 2
				case ".4byte":
					size = 4
				case ".8byte":
					size = 8
				default:
					continue
				}
				// TODO: support other sizes
				if size != 4 {
					continue
				}
				entries = append(entries, AsmTableEntry{Size: size, Value: val})
			}
			tables[symbol] = entries
		}
	}
	return tables
}

type MatchReportFunction struct {
	Name         string  `json:"name"`
	Size         int     `json:"size,string"`
	MatchPercent float64 `json:"fuzzy_match_percent"`
}

type MatchReport struct {
	matches map[string]MatchReportFunction
}

func (mr *MatchReport) isMatched(fnName string) bool {
	f, ok := mr.matches[fnName]
	return ok && f.MatchPercent == 100
}

func (mr *MatchReport) size(fnName string) int {
	return mr.matches[fnName].Size
}

func loadReport(root string) *MatchReport {
	// ensure report is up-to-date
	errChan := make(chan error, 1)
	go func() { errChan <- exec.Command("ninja", "-C", root).Run() }()
	var err error
	select {
	case err = <-errChan:
	case <-time.After(2 * time.Second):
		fmt.Println("Waiting for ninja to finish...")
		err = <-errChan
	}
	if err != nil {
		log.Fatalln("ninja failed, rerun manually")
	}

	content, err := os.ReadFile(filepath.Join(root, "build", "GALE01", "report.json"))
	if err != nil {
		log.Fatalf("Failed to read report file: %v", err)
	}
	var report struct {
		Units []struct {
			Name      string
			Functions []MatchReportFunction
		}
	}
	if err := json.Unmarshal(content, &report); err != nil {
		log.Fatalf("Failed to unmarshal report file: %v", err)
	}
	matches := make(map[string]MatchReportFunction)
	for _, unit := range report.Units {
		for _, fn := range unit.Functions {
			matches[fn.Name] = fn
		}
	}
	return &MatchReport{matches: matches}
}
