# Tier 3: targeted source mutations + orchestrated search — design

A set of primitives that build on Tier 0/1/2 by making the permuter's
search **informed by mwcc-debug's analysis**. Given a stuck function,
generate a small set of high-probability seed mutations from the pattern
catalog + the actual virtual-register conflicts, then run permuter on
each seed.

Where Tier 2 says "evaluate candidates better," Tier 3 says
**"generate better candidates to start with."**

## Why Tier 3 now

Tier 2 plumbing exists, but permuter still searches a huge space
randomly. For really-stuck functions (95%+ match, blocked on register
cascade), the right mutation often involves a specific named variable
that random walks rarely target. Tier 3 closes that gap by:

1. Identifying WHICH variable is blocking (via the existing pattern
   catalog + a new symbol bridge)
2. Generating N targeted mutations directly on that variable
3. Using each as a permuter starting point

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│ debug tier3-search -f FN  (orchestrator)                      │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ debug guide / stuck  (existing — detect pattern, ID virtuals) │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Symbol bridge  (new — virtual reg ↔ source variable)          │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Mutator library  (new — AST-based targeted mutations)         │
│   - mutate type-change                                        │
│   - mutate alias-split                                        │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Multi-start permuter  (uses Tier 2 scoring)                   │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Best result + diff                                            │
└───────────────────────────────────────────────────────────────┘
```

Each layer is independently useful — CLI'd as its own command so the
agent can use them composably.

## Components

### 1. Symbol bridge (new module)

`tools/melee-agent/src/mwcc_debug/symbol_bridge.py`

Bridges between source-level variable names and MWCC's virtual register
numbers. The matching agent reasons about variables; mwcc-debug reasons
about virtuals. This bridge connects them.

**Public API:**

```python
@dataclass
class VarBinding:
    var_name: str         # source-level local name
    virtual: int          # virtual register number (== ig_idx in MWCC IG)
    decl_line: int        # line in source where declared
    confidence: str       # "exact" | "best-guess" | "ambiguous"


def find_virtual_for_var(
    source: str,
    fn_name: str,
    var_name: str,
    pre_pass: Pass,           # from parser.py
) -> Optional[VarBinding]: ...


def find_var_for_virtual(
    source: str,
    fn_name: str,
    virtual: int,
    pre_pass: Pass,
) -> Optional[VarBinding]: ...


def list_bindings(
    source: str,
    fn_name: str,
    pre_pass: Pass,
) -> list[VarBinding]: ...
```

**Mechanism:** parse the function via pycparser, walk local decls in
order. MWCC assigns virtual register numbers in declaration order
starting at 32. The N-th local declaration becomes virtual r(32+N).
Parameters take a separate range determined by the C ABI (r3-r10 on
PPC), so they're handled separately.

For ambiguous cases (e.g., decl-shadowing, complex initializers), the
bridge does best-effort matching via use-site alignment (similar to
`match-iter-first`'s structural matcher).

**CLI:** `debug var-to-virtual -f FN <var-name>` and
`debug virtual-to-var -f FN <ig-idx>`. Both also have `--json` for
tooling.

### 2. Mutator library (new module)

`tools/melee-agent/src/mwcc_debug/mutators.py`

AST-based source mutations targeting specific variables. Uses pycparser
for parse + reconstruct.

**Two mutators in v1:**

**`mutate_type_change`** — changes a local's type. Handles primitive
types (`u8` ↔ `u32`, `s32` → `s8`, etc.) and pointer types.

```python
def mutate_type_change(
    source: str,
    fn_name: str,
    var_name: str,
    new_type: str,
) -> str: ...
```

**`mutate_alias_split`** — introduces a fresh local copy of a variable
before its N-th use, and rewrites that use to reference the fresh local.
Models the alias-split pattern from the catalog.

```python
def mutate_alias_split(
    source: str,
    fn_name: str,
    var_name: str,
    use_index: int,        # 0-indexed; 0 = first use, etc.
    new_name: Optional[str] = None,  # default: var_name + "_alias"
) -> str: ...
```

Both return new source strings; callers are responsible for writing.

**CLI:** `debug mutate type-change -f FN --var V --type T [--apply]` and
`debug mutate alias-split -f FN --var V --at N [--apply]`. Default: write
to stdout. `--apply` writes back to the source file.

Errors (variable not found, parse failure, ambiguous variable) raise
typer.Exit with a clear message and a non-zero code.

### 3. Multi-start orchestrator

`debug tier3-search -f FN [--budget N] [--per-seed-iters M]`

Coordinated search using everything above + the Tier 2 permuter.

**Workflow:**

1. Resolve pcdump + target (auto-derive if needed; reuse `permute`'s
   logic).
2. Run `guide` to detect patterns. For each high-severity suggestion,
   identify the source variable via symbol bridge.
3. Generate up to N seed variants:
   - For each (pattern, variable) pair, apply 1-3 targeted mutations
     via the mutator library
   - Stage each variant inside `nonmatchings/<fn>/tier3_seed_<idx>/`
   - Skip seeds that fail to compile
4. For each surviving seed, run a permuter session with our blended
   scorer (`--per-seed-iters` iterations, default 200).
5. Track best score across seeds + the unmutated baseline.
6. Report the best result with its diff and which seed produced it.

**Caveats:**

- Single-process inside the orchestrator (seeds run sequentially) to
  keep pcdump.txt non-racing. Future: parallel seeds via per-thread cwd.
- Default budget: 5 seeds × 200 iterations = 1000 total iterations,
  ~17 minutes at 1s per scoring call. Tunable.

## Data flow

```
guide output       symbol bridge      mutator library
─────────────  ─►  ─────────────  ─►  ────────────────
  "r36 should     "r36 is variable    "Generate variant
   be r31"        cooldown_timer       with cooldown_timer
                  at line 42"          aliased before its
                                       3rd use"

mutator output    permuter run        scorer (Tier 2)
─────────────  ─►  ─────────────  ─►  ──────────────────
  Variant source   200 iterations    Per-iter scores;
  written to       on this variant   final best per seed
  nonmatchings/
  tier3_seed_0/
```

## Files

**New:**
- `tools/melee-agent/src/mwcc_debug/symbol_bridge.py`
- `tools/melee-agent/src/mwcc_debug/mutators.py`
- `tools/melee-agent/tests/test_mwcc_debug_symbol_bridge.py`
- `tools/melee-agent/tests/test_mwcc_debug_mutators.py`
- `tools/melee-agent/tests/test_mwcc_debug_tier3_search.py`
  (integration; uses live build artifacts when available)
- `docs/mwcc-debug-tier3-tutorial.md`
  (how-to for the matching agent)

**Modified:**
- `tools/melee-agent/src/cli/debug.py` — 4 new CLI commands
  (~200 lines added):
  - `var-to-virtual`
  - `virtual-to-var`
  - `mutate type-change` and `mutate alias-split` (Typer subcommands)
  - `tier3-search`
- `docs/mwcc-debug-permuter-integration.md` — add Tier 3 section
- `.claude/skills/mwcc-debug/SKILL.md` — add Tier 3 command discovery

## Testing strategy

**Symbol bridge:**
- Unit: synthetic functions with known decl order → known virtual
  numbers. Includes edge cases: decl-shadowing, conditional decls in
  nested blocks, no-init vs initialized decls.
- Integration: a known Melee function (e.g., fn_80247510) with verified
  variable → virtual mappings.

**Mutators:**
- Unit: small synthetic functions, mutate, parse mutated output, check
  AST structure.
- Integration: real Melee TU, mutate, run through `compile.sh` (via
  fix-perm-compile), verify the .o builds.

**Orchestrator:**
- End-to-end: known stuck function, run `tier3-search`, verify some
  seed produces a non-baseline score. (May not improve match in tests
  — just verify the pipeline works.)

## Out of scope (Tier 4+)

- **Predict-before-compile** — model the score of a mutation without
  actually compiling. Needs a learned cost model or analytical IG-walk.
- **Mutation chaining** — apply 2+ mutations to one seed. Permuter
  already handles this stochastically; targeted chaining is research.
- **Subexpression-extract / chained-init / drop-variadic-cast
  mutators** — additional pattern coverage. Add when v1 mutators prove
  useful and the patterns are observed in agent feedback.
- **Cross-TU mutations** — changes affecting headers or callees. Out of
  scope.
- **Inline ASM / pragma-driven mutations** — too risky to automate.

## Risk

- **AST manipulation fragility.** pycparser doesn't handle some
  real-world C constructs (GCC attributes, K&R-style decls). Mutators
  should fall back gracefully — log + skip the mutation, don't crash.
- **Bridge accuracy.** Virtual register numbering depends on MWCC's
  internal scan order. Our best-guess via decl-order alignment is
  accurate for typical cases but can be wrong for unusual functions
  (e.g., functions with goto-based decl reordering). Confidence
  reporting is essential.
- **Compile failures from mutations.** Mutators may produce
  syntactically valid but semantically invalid C (e.g., type-changing
  a variable whose uses require the original type). Pipeline must
  silently skip failed seeds.
- **Time budget.** Default tier3-search budget of ~17 minutes is
  longer than most existing commands. Document clearly.

## Open questions

- **Parameter virtuals.** Should mutators support modifying parameter
  types? In v1: no — too invasive (changes callers). Locals only.
- **Mutation diversity.** Should we run BOTH widening AND shrinking
  variants for the same variable, or pick one based on analysis? In
  v1: try both; let the score sort.
- **Memoization.** Some mutations may produce identical sources
  across seed combinations. Detect + dedupe? In v1: no — extra
  complexity, minor cost.

## Success metric

A "really stuck" function that vanilla permuter couldn't crack in 5000
iterations should converge under tier3-search in <1000 total scoring
calls (sum across all seeds). One concrete observed case where this
happens is enough validation for v1.
