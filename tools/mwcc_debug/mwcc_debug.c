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

static void install_hooks(void)
{
    // stub hooks
    patch_stub((void *)0x4C4BD0, hook_pclistblocks);
    patch_stub((void *)0x4BE830, hook_listing_helper);

    // trampoline @ 004C2560, real function, not a stub so properly set it up
    hook_fn((void *)0x4C2560, hook_pcode_traverse,
            traverse_trampoline, 5);
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
