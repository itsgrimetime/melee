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

#define PAGE_EXECUTE_READWRITE 0x40

// compiler functions and their virtual addresses for v1.2.5n
static int(__cdecl *debug_printf)(const char *fmt, ...) = (void *)0x44D580;
static void *(__cdecl *mw_fopen)(const char *name, const char *m) = (void *)0x40C690;
static void(__cdecl *mw_formatoperands)(void *pc, char *buf, int showBlocks) = (void *)0x4C4BF0;

// originally @ 004c2560, node traversal, called with (node, pass_name_string)
static void *(__cdecl *mw_pcode_traverse)(void *node, const char *pass_name) = (void *)0x4C2560;

// static variable for capturing pass name from the most recent traverse call
static const char *last_pass_name = NULL;

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
        debug_printf("%s\n", func_name);

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
// IGNode layout for v1.2.5n (NOT the 7.0 layout — assignedReg is at +0x10):
typedef struct IGNode
{
    /* +0x00 */ struct IGNode *next;
    /* +0x04 */ void *_pad4;
    /* +0x08 */ int useCount;
    /* +0x0C */ int16 _someFlag;
    /* +0x0E */ int16 degree;
    /* +0x10 */ int16 assignedReg; // *** assigned physical reg, or -1 ***
    /* +0x12 */ uint8 flags;
    /* +0x13 */ uint8 _pad13;
    /* +0x14 */ int16 arraySize;
    /* +0x16 */ int16 array[1]; // variable-length neighbor indices
} IGNode;

#define IG_FLAG_SPILLED 0x01

#define INTERFERENCEGRAPH (*(IGNode ***)0x587E3C)
#define N_IGNODES (*(int *)0x587190)

// colorgraph's prologue is 7 bytes (push ebx/esi/edi/ebp + sub esp, 8). Using
// 5 would split the sub esp, 8 (83 ec 08) mid-instruction and corrupt the
// trampoline. trampoline buffer must hold prologue (7) + jump (5) = 12 bytes.
static unsigned char colorgraph_trampoline[24];

// simplifygraph: same shape prologue as colorgraph (7 bytes).
static unsigned char simplifygraph_trampoline[24];

// buildinterferencegraph at 0x530A00: prologue 9 bytes (mov eax,[esp+4] = 4 +
// push ebx = 1 + mov ebx,[esp+0x10] = 4). Trampoline buffer holds prologue
// (9) + JMP (5) = 14, rounded up to 24.
static unsigned char build_ig_trampoline[24];

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
            // Find this node's index in interferencegraph[]. Linear scan;
            // n_nodes is typically <100 so this is cheap.
            int my_idx = -1;
            int n = N_IGNODES;
            if (n > 4096) n = 4096; // defensive cap
            for (j = 0; j < n; j++)
            {
                if (ig_array[j] == node) { my_idx = j; break; }
            }

            debug_printf("%-5d %-7d r%-9d %-7d %-7d 0x%02x%s\n",
                         iter_idx, my_idx, (int)node->assignedReg,
                         (int)node->degree, (int)node->arraySize, (int)node->flags,
                         (node->flags & IG_FLAG_SPILLED) ? "  SPILLED" : "");

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

// simplifygraph hook — captures the worklist construction.
// Returns the head of the linked-list-of-virtuals-to-color. Argument is
// the register class. We just log when it's called + the return head.
static void *__cdecl hook_simplifygraph(int rclass, int n_nodes)
{
    typedef void *(__cdecl * simplifygraph_fn)(int, int);
    void *head;

    // Reset per-class dispense counters at the start of each pass — coloring
    // for a fresh class starts a new dispense sequence.
    if (rclass == 0) dispense_counter_gpr = 0;
    else if (rclass == 1) dispense_counter_fpr = 0;
    else dispense_counter_crf = 0;

    head = ((simplifygraph_fn)simplifygraph_trampoline)(rclass, n_nodes);

    if (PCFILE && DEBUG_GUARD)
    {
        debug_printf("\nSIMPLIFYGRAPH (class=%d n_nodes=%d) head=0x%08x\n",
                     rclass, n_nodes, (uint32)head);
    }
    return head;
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

    // simplifygraph @ 0x4CE400 — DISABLED for now. Adding this hook crashed
    // mwcceppc at 0x4cc3b9 (memory write through a global pointer + index)
    // — possibly the function does some non-prologue work before its 7-byte
    // pure-prologue ends, or a relative branch elsewhere jumps mid-prologue.
    // The colorgraph hook is enough for the headline use case.
    //
    // hook_fn((void *)0x4CE400, hook_simplifygraph,
    //         simplifygraph_trampoline, 7);

    // (obtain_nonvolatile_register hooks intentionally skipped — see comment
    // above; calling-convention mismatch corrupted state.)
}

// debug output setup
static int debug_initialized = 0;

static void enable_debug_output(void)
{
    void *f;
    if (debug_initialized)
        return;
    debug_initialized = 1;
    f = mw_fopen("pcdump.txt", "w");
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
        install_hooks();
    }
    return 1;
}
