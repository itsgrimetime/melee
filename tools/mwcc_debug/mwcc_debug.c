/*
 * Replaces lmgr326b.dll:
 * - re-exports stubbed license checks (lp_checkin/checkout/errstring)
 * - patches one byte to enable debuglisting on load
 * - installs hooks at the compiled-out PCode listing stubs on load
 * - calls the compiler's own fopen for pcdump.txt on first use
 *
 * The brunt of the work is handled by the compiler's own debugging
 * functionality built into it in formatoperands @ 0x4C4BF0. It handles
 * every opcode with symbol names, register class formatting, alias
 * annotations, etc. We just call it.
 */

typedef unsigned char uint8;
typedef unsigned short uint16;
typedef short int16;
typedef unsigned int uint32;
typedef int int32;

#define NULL ((void *)0)
#define DLL_PROCESS_ATTACH 1

// win32 api (kernel32)
__declspec(dllimport) int __stdcall VirtualProtect(void *addr, uint32 size, uint32 newProtect, uint32 *oldProtect);
__declspec(dllimport) uint32 __stdcall GetEnvironmentVariableA(const char *name, char *buf, uint32 size);

#define PAGE_EXECUTE_READWRITE 0x40

// compiler functions and their virtual addresses for v1.2.5n
static int(__cdecl *debug_printf)(const char *fmt, ...) = (void *)0x44D580;
static void *(__cdecl *mw_fopen)(const char *name, const char *m) = (void *)0x40C690;
static void(__cdecl *mw_formatoperands)(void *pc, char *buf, int showBlocks) = (void *)0x4C4BF0;

// originally @ 004c2560, node traversal, called with (node, pass_name_string)
static void *(__cdecl *mw_pcode_traverse)(void *node, const char *pass_name) = (void *)0x4C2560;

// static variable for capturing pass name from the most recent traverse call
static const char *last_pass_name = NULL;

// most-recent function name from pclistblocks. MWCC calls pclistblocks once
// per debuglisting pass per function, so this is refreshed BEFORE
// buildinterferencegraph (and therefore the coalesce hook) runs for that
// function. Used by the coalesce hook to scope MWCC_DEBUG_FORCE_COALESCE
// overrides to a single function within a multi-function TU.
#define FUNCNAME_BUF_LEN 256
static char g_current_function[FUNCNAME_BUF_LEN] = {0};
static int g_current_function_set = 0;

// important statics
#define PCBASICBLOCKS (*(void **)0x587C74)
#define PCFILE (*(void **)0x580610)
#define DEBUGLISTING (*(char *)0x584226)
#define DEBUG_GUARD (*(int *)0x5882B8)

// PCode structs for v1.2.5n, not exhaustive, just what is needed to walk lists
typedef struct PCode
{
    /* +0x00 */ struct PCode *nextPCode;
    /* +0x04 */ void *_pad[3];
    /* +0x10 */ int32 _pad2;
    /* +0x14 */ int16 op;
} PCode;

typedef struct PCLink
{
    struct PCLink *nextLink;
    void *block; // PCodeBlock*
} PCLink;

typedef struct PCodeLabel
{
    struct PCodeLabel *nextLabel;
    void *block;
    int16 resolved;
    uint16 index;
} PCodeLabel;

typedef struct PCodeBlock
{
    /* +0x00 */ struct PCodeBlock *nextBlock;
    /* +0x04 */ struct PCodeBlock *prevBlock;
    /* +0x08 */ PCodeLabel *labels;
    /* +0x0C */ PCLink *predecessors;
    /* +0x10 */ PCLink *successors;
    /* +0x14 */ PCode *firstPCode;
    /* +0x18 */ PCode *lastPCode;
    /* +0x1C */ int32 blockIndex;
    /* +0x20 */ int32 codeOffset;
    /* +0x24 */ int32 loopWeight;
} PCodeBlock;

#define BLOCK_FLAGS(blk) (*(uint16 *)((char *)(blk) + 0x2E))

// opcode name table, i.e. pcode opcode enum value -> mnemonic

// the compiler's assembly opcodeinfo table is alphabetical and
// is not exhaustive, so this is made to have a direct map that
// also provides pseudo-ops like li, mr, nop, etc. my best guess
// is that this did exist originally but was ifdefed out at some point?

static const char *opcodes[] = {
    "b","bl","bc","bclr","bcctr","bt","btlr","btctr","bf","bflr",
    "bfctr","bdnz","bdnzt","bdnzf","bdz","bdzt","bdzf","blr","bctr","bctrl",
    "blrl","lbz","lbzu","lbzx","lbzux","lhz","lhzu","lhzx","lhzux","lha",
    "lhau","lhax","lhaux","lhbrx","lwz","lwzu","lwzx","lwzux","lwbrx","lmw",
    "stb","stbu","stbx","stbux","sth","sthu","sthx","sthux","sthbrx","stw",
    "stwu","stwx","stwux","stwbrx","stmw","dcbf","dcbst","dcbt","dcbtst","dcbz",
    "add","addc","adde","addi","addic","addic.","addis","addme","addze","divw",
    "divwu","mulhw","mulhwu","mulli","mullw","neg","subf","subfc","subfe","subfic",
    "subfme","subfze","cmpi","cmp","cmpli","cmpl","andi.","andis.","ori","oris",
    "xori","xoris","and","or","xor","nand","nor","eqv","andc","orc",
    "extsb","extsh","cntlzw","rlwinm","rlwnm","rlwimi","slw","srw","srawi","sraw",
    "crand","crandc","creqv","crnand","crnor","cror","crorc","crxor","mcrf",
    "mtxer","mtctr","mtlr","mtcrf","mtmsr","mtspr","mfmsr","mfspr","mfxer","mfctr",
    "mflr","mfcr","mffs","mtfsf","eieio","isync","sync","rfi",
    "li","lis","mr","nop","not","lfs","lfsu","lfsx","lfsux",
    "lfd","lfdu","lfdx","lfdux","stfs","stfsu","stfsx","stfsux",
    "stfd","stfdu","stfdx","stfdux","fmr","fabs","fneg","fnabs",
    "fadd","fadds","fsub","fsubs","fmul","fmuls","fdiv","fdivs",
    "fmadd","fmadds","fmsub","fmsubs","fnmadd","fnmadds","fnmsub","fnmsubs",
    "fres","frsqrte","fsel","frsp","fctiw","fctiwz","fcmpu","fcmpo",
    "lwarx","lswi","lswx","stfiwx","stswi","stswx","stwcx",
    "eciwx","ecowx","dcbi","icbi","mcrfs","mcrxr","mftb",
    "mfsr","mtsr","mfsrin","mtsrin","mtfsb0","mtfsb1","mtfsfi","sc",
    "fsqrt","fsqrts","tlbia","tlbie","tlbld","tlbli","tlbsync",
    "tw","trap","twi","opword","mfrom","dsa","esa",
};

#define OPCODE_NAME_COUNT (sizeof(opcodes) / sizeof(opcodes[0]))

// forward declare
static void enable_debug_output(void);

// block listing, this is something that is needed and not provided by the compiler binary.
// really this and the table above are the only additional things needed to make this complete
static void list_block(PCodeBlock *block)
{
    PCode *ist;
    PCLink *link;
    PCodeLabel *label;
    const char *name;

    // block header, stolen from the formatting of MWCC v7.0
    debug_printf(":{%04x}::::LOOPWEIGHT=%d\n", BLOCK_FLAGS(block), block->loopWeight);
    debug_printf("B%d: Succ={", block->blockIndex);
    for (link = block->successors; link; link = link->nextLink)
        if (link->block)
            debug_printf("B%d ", ((PCodeBlock *)link->block)->blockIndex);
    debug_printf("} Pred={");
    for (link = block->predecessors; link; link = link->nextLink)
        if (link->block)
            debug_printf("B%d ", ((PCodeBlock *)link->block)->blockIndex);
    if (block->labels)
    {
        debug_printf("} Labels={");
        for (label = block->labels; label; label = label->nextLabel)
            debug_printf("L%d ", (int)label->index);
    }
    debug_printf("}\n\n");

    // instructions, where formatoperands is the compiler's own function we call
    for (ist = block->firstPCode; ist; ist = ist->nextPCode)
    {
        char buf[500];
        buf[0] = '\0';
        mw_formatoperands(ist, buf, 1);

        name = (ist->op >= 0 && ist->op < (int)OPCODE_NAME_COUNT)
                   ? opcodes[ist->op]
                   : NULL;
        if (name)
            debug_printf("    %-7s %s\n", name, buf);
        else
            debug_printf("    op=0x%x %s\n", (int)ist->op, buf);
    }
}

// hooks

static void __cdecl hook_pclistblocks(const char *func_name)
{
    PCodeBlock *block;
    enable_debug_output();
    if (!PCFILE)
        return;

    // print pass name header captured by traverse hook
    if (last_pass_name)
    {
        debug_printf("\n%s\n", last_pass_name);
        last_pass_name = NULL;
    }
    if (func_name)
    {
        int i;
        // Stash the function name for downstream hooks (coalesce, colorgraph
        // etc.) that need to scope behavior to a specific function. Copy into
        // our own buffer — MWCC's func_name pointer may be reused per call.
        for (i = 0; i < FUNCNAME_BUF_LEN - 1 && func_name[i]; i++)
        {
            g_current_function[i] = func_name[i];
        }
        g_current_function[i] = '\0';
        g_current_function_set = 1;

        debug_printf("%s\n", func_name);
    }

    for (block = (PCodeBlock *)PCBASICBLOCKS; block; block = block->nextBlock)
        list_block(block);
}

static unsigned char traverse_trampoline[16]; // saved prologue and return to execution

// hook @ 004C2560, pcode_traverse
// captures pass name string and calls original.
static void *__cdecl hook_pcode_traverse(void *node, const char *pass_name)
{
    // grab pass name from args, store in static
    last_pass_name = pass_name;

    // call original
    {
        typedef void *(__cdecl * traverse_fn)(void *, const char *);
        return ((traverse_fn)traverse_trampoline)(node, pass_name);
    }
}

static void __cdecl hook_listing_helper(void)
{
    enable_debug_output();
}

static void patch_stub(void *stub_addr, void *target_func)
{
    uint32 old;
    unsigned char *p = (unsigned char *)stub_addr;
    VirtualProtect(stub_addr, 5, PAGE_EXECUTE_READWRITE, &old);
    p[0] = 0xE9;
    *(int32 *)(p + 1) = (int32)((unsigned char *)target_func - (p + 5));
    VirtualProtect(stub_addr, 5, old, &old);
}

static void hook_fn(void *func_addr, void *hook_func,
                    unsigned char *trampoline, int prologue_len)
{
    uint32 old;
    unsigned char *p = (unsigned char *)func_addr;
    int i;

    VirtualProtect(func_addr, prologue_len + 5, PAGE_EXECUTE_READWRITE, &old);
    VirtualProtect(trampoline, 16, PAGE_EXECUTE_READWRITE, &old);

    // copy original prologue to trampoline, volatile because dumb memcopy
    for (i = 0; i < prologue_len; i++)
        ((volatile unsigned char *)trampoline)[i] = ((volatile unsigned char *)p)[i];

    // return to original after prologue
    trampoline[prologue_len] = 0xE9;
    *(int32 *)(trampoline + prologue_len + 1) =
        (int32)(p + prologue_len - (trampoline + prologue_len + 5));

    // write jump to hook
    p[0] = 0xE9;
    *(int32 *)(p + 1) = (int32)((unsigned char *)hook_func - (p + 5));

    VirtualProtect(func_addr, prologue_len + 5, old, &old);
}

// ---------------------------------------------------------------------------
// Coloring decision hook (Tier 2).
//
// Hooks colorgraph(int rclass, IGNode *head) at VA 0x4CE2D0. The function
// walks the IGNode linked list (built by simplifygraph) and assigns each
// virtual register a physical via the Chaitin-style greedy algorithm
// (extracted from MWCC 7.0 source). After the original runs, we re-walk
// the same linked list to dump:
//   - iteration position (order virtuals are colored)
//   - assigned physical register (node->assignedReg)
//   - interferer count (node->arraySize)
//   - flags (fSpilled etc.)
//
// IGNode layout for v1.2.5n (NOT the 7.0 layout — assignedReg is at +0x10).
// Reverse-engineered via Ghidra of FUN_00530C00 (the IG builder at
// VA 0x530C00) which materializes IGNodes from the union-find alias array.
typedef struct IGNode
{
    /* +0x00 */ struct IGNode *next;   // populated by simplifygraph (linked list)
    /* +0x04 */ int _x4;               // init 0
    /* +0x08 */ int _x8;               // init 0
    /* +0x0C */ int16 ig_idx;          // own index in INTERFERENCEGRAPH
    /* +0x0E */ int16 degree;          // initially = arraySize, decremented by simplify
    /* +0x10 */ int16 assignedReg;     // INIT 0xFFFF; for COALESCED nodes (flag 0x4)
                                       // this field holds the ROOT ig_idx until
                                       // colorgraph overwrites it with a physical reg
    /* +0x12 */ uint8 flags;           // bit 0x4 = node was coalesced AWAY
                                       // bit 0x8 = node is a coalesce ROOT
                                       // bit 0x1 = IG_FLAG_SPILLED (added by allocator)
    /* +0x13 */ uint8 _pad13;
    /* +0x14 */ int16 arraySize;       // # of interferer entries
    /* +0x16 */ int16 array[1];        // variable-length: arraySize interferer ig_idxs
} IGNode;

#define IG_FLAG_SPILLED       0x01
#define IG_FLAG_COALESCED_AWAY 0x04
#define IG_FLAG_COALESCE_ROOT  0x08

#define INTERFERENCEGRAPH (*(IGNode ***)0x587E3C)
#define N_IGNODES (*(int *)0x587190)

// Coalesce alias array — union-find parent pointers, one short per virtual,
// indexed by virtual idx. Allocated and populated by FUN_00530E00 (the
// conservative coalescer), then read by FUN_00530C00 (the IG builder) to
// mark coalesced nodes. Each entry holds the parent virtual idx (with path
// compression after FUN_00530E00 finishes). A virtual is its own root iff
// COALESCE_ALIAS[i] == i. Reverse-engineered via Ghidra.
#define COALESCE_ALIAS (*(int16 **)0x58308C)

// Per-class snapshot of n_virtuals from the most recent coalesce hook.
// Used by colorgraph hook as the correct bound when iterating
// INTERFERENCEGRAPH (which is sized to n_virtuals, NOT N_IGNODES — the
// two can diverge by a few entries depending on per-block-count state).
// Reading past the actual IG size returns garbage pointers whose
// dereference hangs wibo (root-caused 2026-05-19). Indexed by rclass.
#define MAX_REGCLASS 4
static int g_last_n_virtuals[MAX_REGCLASS] = {0, 0, 0, 0};

// ---------------------------------------------------------------------------
// Tier 5 — allocator biasing via env var.
//
// MWCC_DEBUG_FORCE_PHYS="virtIdx:physReg[,virtIdx:physReg]*"
//   Example: "36:31"          force virtual #36 to physical r31
//   Example: "36:31,50:27"    force virtual #36 to r31 AND #50 to r27
//
// Applied in the colorgraph hook AFTER MWCC's normal coloring runs but
// BEFORE rewritepcode emits the final instructions. The next pass sees
// the patched assignedReg fields and uses them.
//
// Caveats (the user agrees to these by setting the env var):
//   - Forcing two interfering virtuals to the same physical produces
//     incorrect code (data corruption — multiple live values one reg).
//   - Forcing across register classes (GPR vs FPR) likely crashes.
//   - Used purely for matching investigations / hypothesis testing.
#define MAX_OVERRIDES 32

static struct {
    int virtual_idx;
    int physical;
} g_overrides[MAX_OVERRIDES];
static int g_n_overrides = 0;
static int g_overrides_parsed = 0;

// Iter-based overrides — match by colorgraph iteration position rather
// than ig_idx. Useful when a node has ig_idx that the IG-array scan
// can't recover (e.g., split/spill nodes created post-IG-build with
// no INTERFERENCEGRAPH[] slot, OR cases where the iteration bound
// is wrong). Each entry is (rclass, iter_position, physical_reg).
// Parsed from MWCC_DEBUG_FORCE_PHYS_ITER="class:iter:phys[,...]".
#define MAX_ITER_OVERRIDES 32
static struct {
    int rclass;
    int iter_idx;
    int physical;
} g_iter_overrides[MAX_ITER_OVERRIDES];
static int g_n_iter_overrides = 0;

// Optional function-scope filter for both FORCE_PHYS and FORCE_PHYS_ITER.
// Identical mechanism to g_coalesce_scope_fn. Empty = apply globally
// (legacy). Set via MWCC_DEBUG_FORCE_PHYS_FUNCTION.
static char g_force_phys_scope_fn[FUNCNAME_BUF_LEN] = {0};
static int g_force_phys_scope_fn_set = 0;

static void parse_overrides_from_env(void)
{
    char buf[512];
    uint32 len;
    int i;
    int cur_val;
    int parsing_phys;
    int saved_virt;

    g_overrides_parsed = 1;
    g_n_overrides = 0;
    g_n_iter_overrides = 0;

    // Read optional function-scope filter (shared by FORCE_PHYS +
    // FORCE_PHYS_ITER). Empty → apply globally (legacy behavior).
    len = GetEnvironmentVariableA(
        "MWCC_DEBUG_FORCE_PHYS_FUNCTION",
        g_force_phys_scope_fn, sizeof(g_force_phys_scope_fn));
    g_force_phys_scope_fn_set = (len > 0 && len < sizeof(g_force_phys_scope_fn))
        ? 1 : 0;
    if (!g_force_phys_scope_fn_set) {
        g_force_phys_scope_fn[0] = '\0';
    }

    // Parse MWCC_DEBUG_FORCE_PHYS_ITER="class:iter:phys[,class:iter:phys]*".
    // 3-element tuple parsing — small state machine.
    len = GetEnvironmentVariableA(
        "MWCC_DEBUG_FORCE_PHYS_ITER", buf, sizeof(buf));
    if (len > 0 && len < sizeof(buf)) {
        int field; // 0=class, 1=iter, 2=phys
        int saved_class, saved_iter;
        cur_val = 0;
        field = 0;
        saved_class = saved_iter = -1;
        for (i = 0; i <= (int)len; i++) {
            char c = (i == (int)len) ? '\0' : buf[i];
            if (c >= '0' && c <= '9') {
                cur_val = cur_val * 10 + (c - '0');
            } else if (c == ':') {
                if (field == 0) saved_class = cur_val;
                else if (field == 1) saved_iter = cur_val;
                cur_val = 0;
                field++;
            } else if ((c == ',' || c == '\0') && field == 2
                       && g_n_iter_overrides < MAX_ITER_OVERRIDES) {
                g_iter_overrides[g_n_iter_overrides].rclass = saved_class;
                g_iter_overrides[g_n_iter_overrides].iter_idx = saved_iter;
                g_iter_overrides[g_n_iter_overrides].physical = cur_val;
                g_n_iter_overrides++;
                cur_val = 0;
                field = 0;
                saved_class = saved_iter = -1;
            }
        }
    }

    len = GetEnvironmentVariableA("MWCC_DEBUG_FORCE_PHYS", buf, sizeof(buf));
    if (len == 0 || len >= sizeof(buf)) return;

    // Tiny state machine: read digits into cur_val. ':' transitions to
    // parsing physical (saved virtual). ',' or end commits the pair.
    cur_val = 0;
    parsing_phys = 0;
    saved_virt = -1;
    for (i = 0; i <= (int)len; i++) {
        char c = (i == (int)len) ? '\0' : buf[i];
        if (c >= '0' && c <= '9') {
            cur_val = cur_val * 10 + (c - '0');
        } else if (c == ':') {
            saved_virt = cur_val;
            cur_val = 0;
            parsing_phys = 1;
        } else if ((c == ',' || c == '\0') && parsing_phys && g_n_overrides < MAX_OVERRIDES) {
            g_overrides[g_n_overrides].virtual_idx = saved_virt;
            g_overrides[g_n_overrides].physical = cur_val;
            g_n_overrides++;
            cur_val = 0;
            parsing_phys = 0;
            saved_virt = -1;
        }
        // else: ignore whitespace and stray chars
    }
}

// ---------------------------------------------------------------------------
// Tier 6 — simplification iteration order override.
//
// MWCC_DEBUG_FORCE_ITER_FIRST="virtIdx[,virtIdx]*"
//   Example: "32"          force virtual #32 to be popped first (= colored
//                          first → first crack at top-down dispense for r31)
//   Example: "32,38"       force #32 popped first, #38 second; everything
//                          else preserves its original order
//
// Applied in the simplifygraph hook AFTER MWCC's simplification produces
// the linked list, but BEFORE the existing logging walk. We splice the
// named nodes out of the list and re-insert them at the head in the
// specified order.
//
// Use case: addresses the param-iter-ceiling pattern. Parameters get LOW
// ig_idx and are popped LAST by colorgraph; this lets you experimentally
// promote a parameter to the front of the popping order. If the resulting
// .text matches the matching target, you've confirmed the target is
// reachable via altered iteration order alone (a hypothesis that's
// distinct from "altered coalescing" but reaches the same observable
// effect).
//
// Caveats (the user agrees to these by setting the env var):
//   - The produced binary is a DLL-patched artifact. NOT what real MWCC
//     would emit from any C source. Use for hypothesis testing only.
//   - Reordering preserves correctness (the IG, interferences, and
//     coloring algorithm are unchanged — only the visit order differs).
//     So unlike force-phys, this can't produce data corruption.
//   - But the resulting allocation may not be one that any natural C
//     source would produce, so a force-iter-first match doesn't tell you
//     a corresponding C source exists.
#define MAX_ITER_FIRST 32

static int g_iter_first[MAX_ITER_FIRST];
static int g_n_iter_first = 0;
static int g_iter_first_parsed = 0;

static void parse_iter_first_from_env(void)
{
    char buf[512];
    uint32 len;
    int i;
    int cur_val;
    int has_val;

    g_iter_first_parsed = 1;
    g_n_iter_first = 0;

    len = GetEnvironmentVariableA("MWCC_DEBUG_FORCE_ITER_FIRST", buf, sizeof(buf));
    if (len == 0 || len >= sizeof(buf)) return;

    cur_val = 0;
    has_val = 0;
    for (i = 0; i <= (int)len; i++) {
        char c = (i == (int)len) ? '\0' : buf[i];
        if (c >= '0' && c <= '9') {
            cur_val = cur_val * 10 + (c - '0');
            has_val = 1;
        } else if ((c == ',' || c == '\0') && has_val && g_n_iter_first < MAX_ITER_FIRST) {
            g_iter_first[g_n_iter_first] = cur_val;
            g_n_iter_first++;
            cur_val = 0;
            has_val = 0;
        }
        // else: ignore whitespace and stray chars
    }
}

// ---------------------------------------------------------------------------
// FORCE_COALESCE — override union-find decisions made by the real coalescer.
//
// MWCC_DEBUG_FORCE_COALESCE="virtA=virtB[,virtA=virtB]*"
//   Example: "42=38"        force virtual #42 to coalesce into virtual #38
//   Example: "42=38,50=38"  also force #50 into #38 (three-way merge)
//   Example: "42=42"        un-coalesce #42 (make it its own root again)
//
// Applied in the real-coalesce hook (FUN_00530E00) AFTER the trampoline runs.
// At that point COALESCE_ALIAS is populated with the natural union-find
// result; we patch entries to force the desired mapping. The next pipeline
// phase (FUN_00530C00, the IG builder) reads COALESCE_ALIAS to mark
// coalesced IGNodes, so our override propagates into the IG that
// colorgraph then operates on.
//
// Caveats (the user agrees to these by setting the env var):
//   - Forcing two interfering virtuals to coalesce produces incorrect code
//     (the union should respect the interference matrix at DAT_00583088).
//   - Coalesce is per-(function, register class). The hook applies overrides
//     in every coalesce invocation; pairs that aren't in the current class'
//     virtual-id space simply have no effect (they reference shorts that
//     no operand uses).
//   - Used purely for matching investigations / hypothesis testing.
#define MAX_COALESCE_OVERRIDES 32

static struct {
    int virt;
    int root;
} g_coalesce_overrides[MAX_COALESCE_OVERRIDES];
static int g_n_coalesce_overrides = 0;
static int g_coalesce_overrides_parsed = 0;

// Function scope filter — if set, MWCC_DEBUG_FORCE_COALESCE only applies
// when the currently-compiling function's name (captured by pclistblocks
// into g_current_function) matches. Empty = apply to every coalesce
// invocation (legacy behavior). Set via MWCC_DEBUG_FORCE_COALESCE_FUNCTION.
static char g_coalesce_scope_fn[FUNCNAME_BUF_LEN] = {0};
static int g_coalesce_scope_fn_set = 0;

static void parse_coalesce_overrides_from_env(void)
{
    char buf[512];
    uint32 len;
    int i;
    int cur_val;
    int parsing_root;
    int saved_virt;

    g_coalesce_overrides_parsed = 1;
    g_n_coalesce_overrides = 0;

    // Read optional function-scope filter once at parse time. Empty → apply
    // overrides to every coalesce call (legacy global behavior).
    len = GetEnvironmentVariableA(
        "MWCC_DEBUG_FORCE_COALESCE_FUNCTION",
        g_coalesce_scope_fn, sizeof(g_coalesce_scope_fn));
    g_coalesce_scope_fn_set = (len > 0 && len < sizeof(g_coalesce_scope_fn))
        ? 1 : 0;
    if (!g_coalesce_scope_fn_set) {
        g_coalesce_scope_fn[0] = '\0';
    }

    len = GetEnvironmentVariableA("MWCC_DEBUG_FORCE_COALESCE", buf, sizeof(buf));
    if (len == 0 || len >= sizeof(buf)) return;

    cur_val = 0;
    parsing_root = 0;
    saved_virt = -1;
    for (i = 0; i <= (int)len; i++) {
        char c = (i == (int)len) ? '\0' : buf[i];
        if (c >= '0' && c <= '9') {
            cur_val = cur_val * 10 + (c - '0');
        } else if (c == '=') {
            saved_virt = cur_val;
            cur_val = 0;
            parsing_root = 1;
        } else if ((c == ',' || c == '\0') && parsing_root &&
                   g_n_coalesce_overrides < MAX_COALESCE_OVERRIDES) {
            g_coalesce_overrides[g_n_coalesce_overrides].virt = saved_virt;
            g_coalesce_overrides[g_n_coalesce_overrides].root = cur_val;
            g_n_coalesce_overrides++;
            cur_val = 0;
            parsing_root = 0;
            saved_virt = -1;
        }
        // else: ignore whitespace and stray chars
    }
}

// colorgraph's prologue is 7 bytes (push ebx/esi/edi/ebp + sub esp, 8). Using
// 5 would split the sub esp, 8 (83 ec 08) mid-instruction and corrupt the
// trampoline. trampoline buffer must hold prologue (7) + jump (5) = 12 bytes.
static unsigned char colorgraph_trampoline[24];

// simplifygraph: same shape prologue as colorgraph (7 bytes).
static unsigned char simplifygraph_trampoline[24];

// FUN_00530A80 at 0x530A80: prologue 7 bytes (4× push + sub esp, 0x10).
// Originally MISIDENTIFIED as coalescenodes; per Ghidra RE, this is actually a
// liveness/use-def-marking pass that walks DAT_00587C74 (basic blocks) →
// puVar3[6] (instructions) and sets bit 0x4 on operands that are "first use
// after def" in a forward dataflow scan. Hook kept as-is (entry/exit only)
// for observability; the real coalesce is at FUN_00530E00 (real_coalesce_*).
static unsigned char coalesce_trampoline[24];

// real coalesce at 0x530E00: prologue 7 bytes (4× push + sub esp, 0x18).
// Same shape as colorgraph but a bigger frame. This is the actual Chaitin-
// Briggs conservative coalescer — uses union-find with path compression
// over COALESCE_ALIAS (DAT_0058308C). Reverse-engineered via Ghidra.
static unsigned char real_coalesce_trampoline[24];

// buildinterferencegraph at 0x530A00: prologue 9 bytes (mov eax,[esp+4] = 4 +
// push ebx = 1 + mov ebx,[esp+0x10] = 4). Trampoline buffer holds prologue
// (9) + JMP (5) = 14, rounded up to 24.
static unsigned char build_ig_trampoline[24];

// propagateconstants at 0x52B530: prologue 14 bytes
//   push ebx (1) + push ebp (1) + push 0 imm8 (2) +
//   mov [0x58826c], 0 (10 bytes — opcode+modrm+addr+imm32)
// Trampoline needs prologue (14) + JMP (5) = 19, rounded to 32.
static unsigned char propagateconstants_trampoline[32];

// constpropchanged flag (Tier 3.5) — read this after propagateconstants
// returns to see if anything was actually propagated.
#define CONSTPROP_CHANGED_FLAG (*(int *)0x58826C)

// obtain_nonvolatile_register variants: 8-byte prologue (push ebx + mov ebx,
// [esp+0xc] + movsx eax, bx). Each per-class function needs its own
// trampoline.
static unsigned char obtain_nv_gpr_trampoline[24];
static unsigned char obtain_nv_fpr_trampoline[24];
static unsigned char obtain_nv_crf_trampoline[24];

// Per-class dispense counter — written by obtain_nv hooks, read for logging.
static int dispense_counter_gpr = 0;
static int dispense_counter_fpr = 0;
static int dispense_counter_crf = 0;

// hook @ 0x4CE2D0, colorgraph
static int __cdecl hook_colorgraph(int rclass, IGNode *head)
{
    typedef int(__cdecl * colorgraph_fn)(int, IGNode *);
    int result;
    IGNode *node;
    int iter_idx;

    // Call original first — it does the actual coloring
    result = ((colorgraph_fn)colorgraph_trampoline)(rclass, head);

    // Tier 5 — apply allocator overrides. Two override mechanisms,
    // both gated by the optional MWCC_DEBUG_FORCE_PHYS_FUNCTION scope:
    //   (a) ig_idx-based (g_overrides): match by node->ig_idx (read
    //       directly from the IGNode's own-index field at offset 0x0C).
    //       Earlier versions used a linear INTERFERENCEGRAPH[] scan
    //       which could return -1 for nodes that didn't appear in the
    //       expected slot (wrong bound, or post-IG-build split/spill
    //       nodes); the direct field read is reliable.
    //   (b) iter-based (g_iter_overrides): match by (rclass, iter_idx)
    //       — colorgraph iteration position. Fallback for cases where
    //       ig_idx is unknown or unreliable.
    {
        // Function-scope check (shared by both mechanisms).
        int scope_skip = 0;
        if (g_force_phys_scope_fn_set) {
            if (!g_current_function_set) {
                scope_skip = 1;
            } else {
                int sj;
                for (sj = 0; sj < FUNCNAME_BUF_LEN; sj++) {
                    if (g_current_function[sj] != g_force_phys_scope_fn[sj]) {
                        scope_skip = 1;
                        break;
                    }
                    if (g_current_function[sj] == '\0') break;
                }
            }
            if (scope_skip && PCFILE && DEBUG_GUARD
                && (g_n_overrides > 0 || g_n_iter_overrides > 0)) {
                debug_printf("\n[FORCE_PHYS] scope skip (fn=%s, scope=%s)\n",
                             g_current_function_set ? g_current_function
                                                    : "<unset>",
                             g_force_phys_scope_fn);
            }
        }

        if (!scope_skip && (g_n_overrides > 0 || g_n_iter_overrides > 0))
        {
            int local_iter = 0;
            for (node = head; node; node = node->next)
            {
                int idx = (int)node->ig_idx;  // direct field read; no linear scan
                int k;

                // (a) ig_idx-based overrides
                for (k = 0; k < g_n_overrides; k++)
                {
                    if (g_overrides[k].virtual_idx == idx)
                    {
                        int old_phys = (int)node->assignedReg;
                        node->assignedReg = (int16)g_overrides[k].physical;
                        if (PCFILE && DEBUG_GUARD)
                        {
                            debug_printf("\n[FORCE_PHYS] ig_idx=%d: r%d -> r%d\n",
                                         idx, old_phys, g_overrides[k].physical);
                        }
                        break;
                    }
                }

                // (b) iter-based overrides for this class + iter position
                for (k = 0; k < g_n_iter_overrides; k++)
                {
                    if (g_iter_overrides[k].rclass == rclass
                        && g_iter_overrides[k].iter_idx == local_iter)
                    {
                        int old_phys = (int)node->assignedReg;
                        node->assignedReg = (int16)g_iter_overrides[k].physical;
                        if (PCFILE && DEBUG_GUARD)
                        {
                            debug_printf("\n[FORCE_PHYS_ITER] class=%d iter=%d "
                                         "(ig_idx=%d): r%d -> r%d\n",
                                         rclass, local_iter, idx,
                                         old_phys,
                                         g_iter_overrides[k].physical);
                        }
                        break;
                    }
                }

                local_iter++;
            }
        }
    }

    // Dump per-virtual decisions in iteration order. Now also walks the
    // interferer array (node->array, arraySize entries of short indices)
    // so agents can see exactly which other virtuals constrained the choice.
    if (PCFILE && DEBUG_GUARD)
    {
        IGNode **ig_array;
        int j;
        int total_nodes;
        ig_array = INTERFERENCEGRAPH;
        total_nodes = N_IGNODES;
        debug_printf("\nCOLORGRAPH DECISIONS (class=%d, result=%d, n_nodes=%d)\n",
                     rclass, result, total_nodes);
        debug_printf("%-5s %-7s %-10s %-7s %-7s %s\n",
                     "iter", "ig_idx", "assignedReg", "degree", "nIntfr", "flags");
        iter_idx = 0;
        for (node = head; node; node = node->next)
        {
            // Read the node's own index from its IGNode field (offset 0x0C).
            // FUN_00530C00 writes this when materializing the IG from the
            // union-find array, and colorgraph doesn't overwrite it.
            // Previously we did a linear INTERFERENCEGRAPH[] scan here,
            // which returned -1 when the IG-array bound was wrong or the
            // node was created post-IG-build (split/spill). Direct field
            // read is reliable.
            int my_idx = (int)node->ig_idx;

            // Decode flag bits for human-readable annotation. Note: bit 0x4
            // (COALESCED_AWAY) never appears here because such nodes are NOT
            // in the simplification/coloring linked list — they get visited
            // in the separate "COALESCED ALIASES" pass below.
            {
                const char *spilled = (node->flags & IG_FLAG_SPILLED) ? "  SPILLED" : "";
                const char *root = (node->flags & IG_FLAG_COALESCE_ROOT) ? "  [ROOT]" : "";
                debug_printf("%-5d %-7d r%-9d %-7d %-7d 0x%02x%s%s\n",
                             iter_idx, my_idx, (int)node->assignedReg,
                             (int)node->degree, (int)node->arraySize,
                             (int)node->flags, spilled, root);
            }

            // Dump interferer indices. Each entry in node->array is a short
            // index into interferencegraph[]. We also resolve to the
            // assignedReg of each interferer so agents can see what physicals
            // were excluded from this node's workingMask.
            if (node->arraySize > 0)
            {
                int n_intfr = node->arraySize;
                if (n_intfr > 64) n_intfr = 64; // cap output to keep readable
                debug_printf("      interferers:");
                for (j = 0; j < n_intfr; j++)
                {
                    int idx = (int)node->array[j];
                    int phys = -1;
                    if (idx >= 0 && idx < N_IGNODES && ig_array[idx])
                        phys = (int)ig_array[idx]->assignedReg;
                    debug_printf(" %d=r%d", idx, phys);
                }
                if ((int)node->arraySize > n_intfr)
                    debug_printf(" ...(%d more)", (int)node->arraySize - n_intfr);
                debug_printf("\n");
            }

            iter_idx++;
            if (iter_idx >= 1000) // safety cap against cyclic next-pointers
            {
                debug_printf("(iteration cap reached at %d nodes)\n", iter_idx);
                break;
            }
        }

        // COALESCED ALIASES — for each IGNode with flag bit 0x4 set, dump
        // its (alias → root) mapping. These nodes were merged away during
        // FUN_00530E00 (the conservative coalescer) and don't appear in the
        // simplification linked list, so colorgraph never visits them. The
        // root's ig_idx is stored in the alias node's assignedReg field by
        // FUN_00530C00 and remains there (colorgraph only overwrites
        // assignedReg for nodes it processes — i.e. the roots).
        //
        // IMPORTANT: iterate up to g_last_n_virtuals[rclass] (stashed by
        // the coalesce hook), NOT N_IGNODES. The two can diverge by a few
        // entries — N_IGNODES is sometimes the block count or includes
        // extra state, and reading past the actual IG buffer's end returns
        // garbage pointers that hang wibo on dereference.
        {
            int found = 0;
            int cap = ((int)rclass >= 0 && (int)rclass < MAX_REGCLASS)
                ? g_last_n_virtuals[rclass]
                : 0;
            if (cap > 4096) cap = 4096; // defensive cap
            for (j = 0; j < cap; j++)
            {
                IGNode *n = ig_array[j];
                if (n == 0) continue;
                if ((n->flags & IG_FLAG_COALESCED_AWAY) == 0) continue;
                if (found == 0)
                {
                    debug_printf("\nCOALESCED ALIASES (alias_idx -> root_idx [root_phys]):\n");
                }
                {
                    int root_idx = (int)n->assignedReg;
                    int root_phys = -1;
                    if (root_idx >= 0 && root_idx < cap && ig_array[root_idx])
                    {
                        root_phys = (int)ig_array[root_idx]->assignedReg;
                    }
                    debug_printf("  %d -> %d [r%d]\n", j, root_idx, root_phys);
                }
                found++;
                if (found >= 256)
                {
                    debug_printf("  ...(capped at 256)\n");
                    break;
                }
            }
        }

        // (Full IG snapshot moved to buildinterferencegraph hook — it dumps
        // the pre-simplification graph, which is strictly more informative
        // than the post-coalescing state we'd see here.)
    }

    return result;
}

// buildinterferencegraph hook — runs once per (function, register class).
// After the original returns, the interferencegraph[] global is populated
// with all edges MWCC computed before simplification/coalescing. Dumping
// it here captures the "raw" interference data — strictly more information
// than the colorgraph-time snapshot, which is post-coalescing.
static int __cdecl hook_build_ig(void *proc, int rclass, int unknown)
{
    typedef int(__cdecl * build_ig_fn)(void *, int, int);
    int result;

    result = ((build_ig_fn)build_ig_trampoline)(proc, rclass, unknown);

    if (PCFILE && DEBUG_GUARD)
    {
        // Just log that construction completed. Iterating interferencegraph[]
        // from this hook point causes crashes (Rosetta exception address
        // 0x6c2e1xxx) — likely because findrematerializations reallocates
        // the array near the end of buildinterferencegraph and stale
        // pointers can exist at certain indices.
        //
        // The full pre-simplification adjacency-list data is still
        // accessible via the colorgraph hook's per-iter interferer dumps
        // — those run AFTER simplification but capture the same edges
        // for active virtuals (just not the simplified-out leaves).
        debug_printf("\nIG CONSTRUCTED (class=%d, n_nodes=%d)\n",
                     rclass, N_IGNODES);
    }
    return result;
}

// propagateconstants hook (Tier 3.5) — fires once per (function, optimization
// round) when MWCC's constant propagation pass runs. Reads the
// CONSTPROP_CHANGED_FLAG (set by propagateconstantstoblock arms when any
// constant was propagated) so we know whether this pass actually did
// anything.
//
// The headline use case: for scroll_offset-in-mnVibration-style cases, we
// expect CP to NOT fire (because the cleanup-loop "use of scroll_offset"
// got inlined to a literal-0 instruction at PCode gen — there's nothing
// for CP to propagate). This empirically confirms our mechanism theory.
static void __cdecl hook_propagateconstants(void)
{
    typedef void(__cdecl * fn_t)(void);
    int changed_before, changed_after;

    changed_before = CONSTPROP_CHANGED_FLAG;
    ((fn_t)propagateconstants_trampoline)();
    changed_after = CONSTPROP_CHANGED_FLAG;

    if (PCFILE && DEBUG_GUARD)
    {
        debug_printf("\nCONSTPROP RAN (changed_flag: before=%d after=%d)\n",
                     changed_before, changed_after);
    }
}

// simplifygraph hook (Tier 2.5) — captures the simplification order, the
// per-node initial degrees, and which nodes got the "spilled" flag added by
// simplifygraph itself.
//
// MWCC 1.2.5n signature (from RE of call sites + prologue at 0x4CE400):
//   IGNode *simplifygraph(int rclass, int n_colors, int n_class_regs);
//
//   - rclass: register class id (0=GPR, 1=FPR, ...)
//   - n_colors: number of colors available (=count of unallocated phys regs
//     in the class, returned by the n_available helper just before this call)
//   - n_class_regs: total physical regs in the class (typically 32 — comes
//     from a per-class count global at [0x58849a] et al)
//
// The function:
//   1. Iterates interferencegraph[] for the given class
//   2. Finds nodes with degree < n_colors (Chaitin "trivially colorable")
//   3. Removes them from the graph (decrements interferer degrees)
//   4. When stuck, picks a "potential spill" by heuristic (degree-based here,
//      not spill-cost — the 1.2.5n version is simpler than 7.0)
//   5. Returns the head of the simplified linked list (popped LIFO into
//      colorgraph; head = colored first)
//
// Snapshot strategy: BEFORE the trampoline call, we save per-node flags +
// degree into a static array (indexed by ig_idx). AFTER the call, we walk
// the returned linked list to surface the iteration order and diff against
// the snapshot to identify spill markers.
#define MAX_SIMPLIFY_SNAPSHOT 512

static struct {
    int16 degree_before;
    uint8 flags_before;
    uint8 _pad;
} g_simplify_snapshot[MAX_SIMPLIFY_SNAPSHOT];
static int g_simplify_snapshot_n = 0;

static void *__cdecl hook_simplifygraph(int rclass, int n_colors, int n_class_regs)
{
    typedef void *(__cdecl * simplifygraph_fn)(int, int, int);
    IGNode *head;
    IGNode *node;
    int order_idx;
    IGNode **ig;
    int ig_n;

    head = (IGNode *)((simplifygraph_fn)simplifygraph_trampoline)(
        rclass, n_colors, n_class_regs);

    // Tier 6 — apply iter-first overrides if any. Splice the named virtuals
    // out of their current positions and re-insert them at the head, in the
    // order given. The original relative order of other nodes is preserved.
    if (g_n_iter_first > 0 && head != 0)
    {
        IGNode **ig_local = INTERFERENCEGRAPH;
        int ig_n_local = N_IGNODES;
        if (ig_n_local > 1024) ig_n_local = 1024;
        if (ig_n_local < 0) ig_n_local = 0;
        // For each requested virtual (in reverse so the FIRST listed ends
        // up at the absolute head), find the IGNode in the list and move
        // it to the head.
        int k;
        for (k = g_n_iter_first - 1; k >= 0; k--)
        {
            int want_idx = g_iter_first[k];
            if (want_idx < 0 || want_idx >= ig_n_local) continue;
            if (!ig_local) continue;
            IGNode *want = ig_local[want_idx];
            if (!want) continue;
            if (want == head) continue;  // already at head
            // Walk the list, find the predecessor of `want` (if any),
            // unlink, prepend.
            IGNode *prev = head;
            while (prev && prev->next != want)
                prev = prev->next;
            if (!prev) continue;  // `want` isn't in this class's list
            prev->next = want->next;
            want->next = head;
            head = want;
            if (PCFILE && DEBUG_GUARD)
            {
                debug_printf("\n[FORCE_ITER_FIRST] moved ig_idx %d to head "
                             "of class %d's simplification list\n",
                             want_idx, rclass);
            }
        }
    }

    if (PCFILE && DEBUG_GUARD)
    {
        // Read IG state AFTER simplifygraph returns. Reading before crashes
        // (likely because INTERFERENCEGRAPH isn't reliably in shape for cross-
        // function reads at function-start time — possibly find_remat
        // realloc is still racing or the pointer is mid-update). After the
        // trampoline call the IG is in its final state for this class.
        ig = INTERFERENCEGRAPH;
        ig_n = N_IGNODES;
        if (ig_n > 1024) ig_n = 1024;
        if (ig_n < 0) ig_n = 0;

        debug_printf("\nSIMPLIFY GRAPH (class=%d, n_colors=%d, n_class_regs=%d)\n",
                     rclass, n_colors, n_class_regs);
        debug_printf("%-5s %-7s %-7s %-8s %-9s %s\n",
                     "iter", "ig_idx", "degree", "arraySize", "flags", "notes");

        order_idx = 0;
        for (node = head; node; node = node->next)
        {
            int idx = -1;
            int j;
            const char *spill_note;
            for (j = 0; j < ig_n; j++)
            {
                if (ig && ig[j] == node) { idx = j; break; }
            }
            spill_note = (node->flags & 0x08) ? "SPILLED" : "";
            debug_printf("%-5d %-7d %-7d %-8d 0x%-7x %s\n",
                         order_idx, idx,
                         (int)node->degree,
                         (int)node->arraySize,
                         (int)node->flags,
                         spill_note);
            order_idx++;
            if (order_idx > 256) break;
        }
    }
    return head;
}

// Hook for FUN_00530A80 — entry/exit logging only.
//
// HISTORICAL NOTE: This function was misidentified as `coalescenodes` based
// on its position in buildinterferencegraph's call chain. Per Ghidra RE
// (2026-05-19), it is actually a LIVENESS / use-def-marking pass that
// walks the per-block PCode and flags operand uses with bit 0x4. It is NOT
// the coalescer. The real coalescer is FUN_00530E00 (`hook_real_coalesce`
// below). The hook is retained here as a low-cost observability point in
// the pipeline.
//
// Pipeline reminder (see Ghidra decompile of FUN_00530A00):
//   1. FUN_005301B0 — per-block bitset allocation (DAT_00587E74)
//   2. FUN_00530A80 — liveness use-def marker  ← this hook
//   3. FUN_00531290 — buildinterferencematrix (DAT_00583088)
//   4. FUN_00530E00 — REAL conservative coalesce (union-find DAT_0058308C)
//   5. FUN_00530C00 — materializes INTERFERENCEGRAPH (DAT_00587E3C)
//
// INTERFERENCEGRAPH is unsafe to read here — it holds stale pointers from
// the prior function's compilation until Phase 5 rewrites it.
static int __cdecl hook_dataflow_marker(int rclass, int n_nodes)
{
    typedef int(__cdecl * fn_t)(int, int);
    int result;
    int n;

    if (PCFILE && DEBUG_GUARD) {
        n = N_IGNODES;
        debug_printf("\n[DATAFLOW] enter class=%d n_nodes=%d N_IGNODES_pre=%d\n",
                     rclass, n_nodes, n);
    }

    result = ((fn_t)coalesce_trampoline)(rclass, n_nodes);

    if (PCFILE && DEBUG_GUARD) {
        n = N_IGNODES;
        debug_printf("[DATAFLOW] exit result=%d N_IGNODES_post=%d\n",
                     result, n);
    }
    return result;
}

// ---------------------------------------------------------------------------
// Real coalesce hook (FUN_00530E00) — the actual Chaitin-Briggs conservative
// coalescer for MWCC 1.2.5n. Reverse-engineered via Ghidra.
//
// Signature: __cdecl(uint rclass, uint n_virtuals)
//   rclass = register class (0=FP, 1=GPR, others=CR/special)
//   n_virtuals = total virtual-register count for this (function, class)
//
// What it does:
//   1. Allocates COALESCE_ALIAS = short[n_virtuals] at DAT_0058308C
//   2. Initializes COALESCE_ALIAS[i] = i for all i (each virtual its own root)
//   3. For each move-class PCode instruction:
//        - Find roots of src/dst via union-find with path-walking
//        - If same root → redundant move → free
//        - If different roots AND no interference (DAT_00583088) → UNION
//          (lower idx becomes new root; phys-reg-aware logic for moves
//          involving virtuals < 0x20)
//   4. Rewrites all operands to use root virtuals (path compression)
//
// On hook exit, COALESCE_ALIAS[i] holds the FINAL root for each virtual
// (post-compression). We dump these mappings and, if MWCC_DEBUG_FORCE_COALESCE
// is set, patch entries to force additional/different unifications.
//
// Note: FUN_00530C00 (the next pipeline phase) reads COALESCE_ALIAS to mark
// IGNodes with flag bit 0x4 (coalesced-away) / 0x8 (coalesce-root) and to
// store the root idx in the assignedReg field. Our overrides therefore
// propagate into the IG that colorgraph operates on.
static void __cdecl hook_real_coalesce(unsigned int rclass, unsigned int n_virtuals)
{
    typedef void(__cdecl * fn_t)(unsigned int, unsigned int);
    int i;
    int distinct_roots;
    int forced_count;
    int16 *alias;

    if (PCFILE && DEBUG_GUARD) {
        debug_printf("\n[COALESCE] enter class=%d n_virtuals=%d\n",
                     rclass, n_virtuals);
    }

    // Stash for the colorgraph hook to use as the IG iteration bound.
    if ((int)rclass >= 0 && (int)rclass < MAX_REGCLASS) {
        g_last_n_virtuals[rclass] = (int)n_virtuals;
    }

    // Run the original — this populates COALESCE_ALIAS.
    ((fn_t)real_coalesce_trampoline)(rclass, n_virtuals);

    if (!g_coalesce_overrides_parsed) {
        parse_coalesce_overrides_from_env();
    }

    alias = COALESCE_ALIAS;
    if (alias == 0 || n_virtuals == 0) {
        if (PCFILE && DEBUG_GUARD) {
            debug_printf("[COALESCE] exit (alias=null or n=0)\n");
        }
        return;
    }

    // Dump the natural coalesce result. Show only non-trivial bindings
    // (where root != self) to keep the output focused.
    if (PCFILE && DEBUG_GUARD) {
        int dumped = 0;
        debug_printf("[COALESCE] natural mappings (virt -> root):\n");
        for (i = 0; i < (int)n_virtuals; i++) {
            int root = (int)alias[i];
            if (root != i) {
                debug_printf("  %d -> %d\n", i, root);
                dumped++;
                if (dumped >= 256) {
                    debug_printf("  ...(capped at 256)\n");
                    break;
                }
            }
        }
        if (dumped == 0) {
            debug_printf("  (none — no virtuals coalesced)\n");
        }
    }

    // Apply FORCE_COALESCE overrides. Three filters guard each entry:
    //   1. Function-scope filter — if MWCC_DEBUG_FORCE_COALESCE_FUNCTION is
    //      set, skip the entire override block when the current function
    //      (captured by hook_pclistblocks into g_current_function) doesn't
    //      match. Prevents one function's override from corrupting an
    //      earlier or later function in the same TU.
    //   2. Bounds check — virt and root must be in [0, n_virtuals); pairs
    //      for the wrong register class are silently skipped.
    //   3. (No-op if the user happens to specify virt == root.)
    forced_count = 0;
    {
        int scope_skip = 0;
        if (g_coalesce_scope_fn_set) {
            // Need a match between g_current_function and g_coalesce_scope_fn
            if (!g_current_function_set) {
                scope_skip = 1;
            } else {
                int j;
                for (j = 0; j < FUNCNAME_BUF_LEN; j++) {
                    if (g_current_function[j] != g_coalesce_scope_fn[j]) {
                        scope_skip = 1;
                        break;
                    }
                    if (g_current_function[j] == '\0') break;
                }
            }
            if (scope_skip && PCFILE && DEBUG_GUARD) {
                debug_printf("[FORCE_COALESCE] scope skip (fn=%s, scope=%s)\n",
                             g_current_function_set ? g_current_function : "<unset>",
                             g_coalesce_scope_fn);
            }
        }
        if (!scope_skip && g_n_coalesce_overrides > 0) {
            for (i = 0; i < g_n_coalesce_overrides; i++) {
                int v = g_coalesce_overrides[i].virt;
                int r = g_coalesce_overrides[i].root;
                if (v < 0 || v >= (int)n_virtuals) continue;
                if (r < 0 || r >= (int)n_virtuals) continue;
                if (PCFILE && DEBUG_GUARD) {
                    debug_printf("[FORCE_COALESCE] alias[%d]: %d -> %d\n",
                                 v, (int)alias[v], r);
                }
                alias[v] = (int16)r;
                forced_count++;
            }
        }
    }

    // Count distinct roots (post-override) for a quick summary line.
    distinct_roots = 0;
    for (i = 0; i < (int)n_virtuals; i++) {
        if ((int)alias[i] == i) distinct_roots++;
    }

    if (PCFILE && DEBUG_GUARD) {
        debug_printf("[COALESCE] exit class=%d n_virtuals=%d distinct_roots=%d forced=%d\n",
                     rclass, n_virtuals, distinct_roots, forced_count);
    }
}


// obtain_nonvolatile_register hooks: TRIED, didn't work — likely a calling
// convention mismatch (the disassembly suggests it reads [esp+0xc] which is
// past 2 args, hinting at a non-__cdecl convention or different arg count).
// Wrapping these with int(__cdecl)(int, int) corrupted state and produced
// all-r-1 assignedReg in subsequent colorgraph runs. Skipping for now —
// the dispense order is still derivable post-hoc from the colorgraph
// linked-list walk (each "obtain" call corresponds to a node where the
// inferred workingMask was empty).

static void install_hooks(void)
{
    // stub hooks
    patch_stub((void *)0x4C4BD0, hook_pclistblocks);
    patch_stub((void *)0x4BE830, hook_listing_helper);

    // trampoline @ 004C2560, real function, not a stub so properly set it up
    hook_fn((void *)0x4C2560, hook_pcode_traverse,
            traverse_trampoline, 5);

    // colorgraph @ 004CE2D0, register-coloring entry point (Tier 2 hook).
    // Prologue is 7 bytes: push ebx/esi/edi/ebp (1 each) + sub esp, 8 (3).
    hook_fn((void *)0x4CE2D0, hook_colorgraph,
            colorgraph_trampoline, 7);

    // buildinterferencegraph @ 0x530A00 (Tier 3 hook) — runs before
    // colorgraph for each (function, register class). After it returns,
    // interferencegraph[] is populated with all edges MWCC computed for
    // this class. Prologue 9 bytes: mov eax,[esp+4] (4) + push ebx (1) +
    // mov ebx,[esp+0x10] (4).
    hook_fn((void *)0x530A00, hook_build_ig,
            build_ig_trampoline, 9);

    // propagateconstants @ 0x52B530 (Tier 3.5 hook) — runs once per
    // function before coloring. Prologue 14 bytes: push ebx + push ebp +
    // push 0 (imm8) + mov [0x58826c], 0 (10 bytes).
    hook_fn((void *)0x52B530, hook_propagateconstants,
            propagateconstants_trampoline, 14);

    // simplifygraph @ 0x4CE400 (Tier 2.5 hook) — runs between IG construction
    // and colorgraph for each (function, register class) pair. Captures the
    // simplification order and per-node {flags, degree} delta. Earlier attempt
    // (with 2-arg signature) crashed because the real function takes 3 args:
    // (class, n_colors, n_class_regs). The 7-byte prologue is
    //   push ebx (1) + push esi (1) + push edi (1) + push ebp (1) +
    //   sub esp, 0x10 (3)
    // — same shape as colorgraph but a larger local-frame.
    hook_fn((void *)0x4CE400, hook_simplifygraph,
            simplifygraph_trampoline, 7);

    // FUN_00530A80 @ 0x530A80 — was misidentified as coalescenodes; it's
    // actually a liveness use-def marker. Kept as observability for the
    // 2nd phase of buildinterferencegraph. Prologue 7 bytes.
    hook_fn((void *)0x530A80, hook_dataflow_marker,
            coalesce_trampoline, 7);

    // FUN_00530E00 @ 0x530E00 — THE REAL conservative coalescer (union-find
    // over COALESCE_ALIAS). 4th phase of buildinterferencegraph. Prologue
    // 7 bytes (4× push + sub esp, 0x18). Hook dumps the alias array and
    // applies MWCC_DEBUG_FORCE_COALESCE overrides.
    hook_fn((void *)0x530E00, hook_real_coalesce,
            real_coalesce_trampoline, 7);

    // (obtain_nonvolatile_register hooks intentionally skipped — see comment
    // above; calling-convention mismatch corrupted state.)
}

// debug output setup
static int debug_initialized = 0;

static void enable_debug_output(void)
{
    void *f;
    char path_buf[260];
    uint32 path_len;
    const char *path;

    if (debug_initialized)
        return;
    debug_initialized = 1;

    // Read MWCC_DEBUG_PCDUMP_PATH env var; default to "pcdump.txt" so
    // existing callers that invoke the patched compiler directly without
    // setting the env var still work. CLI callers (pcdump-local,
    // score-source) set this to a unique per-PID path so parallel runs
    // don't contaminate each other's output.
    path_len = GetEnvironmentVariableA(
        "MWCC_DEBUG_PCDUMP_PATH", path_buf, sizeof(path_buf));
    path = (path_len > 0 && path_len < sizeof(path_buf))
        ? (const char *)path_buf
        : "pcdump.txt";

    f = mw_fopen(path, "w");
    if (f)
    {
        PCFILE = f;
        DEBUGLISTING = 1;
        DEBUG_GUARD = 1;
    }
}

// original license stubs
__declspec(dllexport) int __cdecl lp_checkin(void) { return 0; }
__declspec(dllexport) int __cdecl lp_checkout(void) { return 0; }
__declspec(dllexport) int __cdecl lp_errstring(void) { return 0; }

// dll entry 
int __stdcall DllMain(void *hModule, uint32 reason, void *reserved)
{
    (void)hModule;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
    {
        uint32 old;
        // patch copt for debug @ 0x42C8E1
        VirtualProtect((void *)0x42C8E1, 1, PAGE_EXECUTE_READWRITE, &old);
        *(uint8 *)0x42C8E1 = 0x01;
        VirtualProtect((void *)0x42C8E1, 1, old, &old);

        DEBUG_GUARD = 1;
        parse_overrides_from_env();
        parse_iter_first_from_env();
        install_hooks();
    }
    return 1;
}
