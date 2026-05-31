"""
Part 12: register-swap patterns from Discord #match-help + #general mining.

Patterns discovered by extracting Discord conversations about regswaps,
regalloc, stmw/lmw, addi/mr, declaration order, and self-assignment from
the gc-wii-decomp archive DB, then having parallel agents identify
distinct tricks not yet in the mismatch DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "melee-agent" / "src"))

from mismatch_db.models import (
    Example,
    Fix,
    Pattern,
    PatternDB,
    Provenance,
    ProvenanceEntry,
    Signal,
)
from mismatch_db.schema import init_db, DEFAULT_DB_PATH


PATTERNS = [
    Pattern(
        id="delayed-load-past-null-check",
        name="MWCC delays dereference until AFTER null guard on parent pointer",
        description=(
            "When source code loads `myPtrArray[N]` BEFORE a null check on "
            "`myPtrArray`, MWCC may delay the load until inside the "
            "null-guarded branch. Symptom: target asm has the lwz/lbz "
            "appearing after the null check, but your C has it before. "
            "Move the load inside the if-body to match."
        ),
        root_cause=(
            "Loading through a possibly-null pointer is UB. MWCC's "
            "optimizer hoists the load down past the null check, treating "
            "the pre-check load as dead. Source must mirror this."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["cmplwi r3,0", "beq", "lwz"]},
                description="Null check before the dereference",
            ),
        ],
        examples=[
            Example(
                function="generic null-guarded deref",
                before=(
                    "// Load before null check — MWCC may delay it:\n"
                    "int val = myPtrArray[3];\n"
                    "if (myPtrArray) {\n"
                    "    return val + 3;\n"
                    "}\n"
                    "return -1;\n"
                ),
                after=(
                    "// Load inside guard - matches MWCC's hoisted form:\n"
                    "if (myPtrArray) {\n"
                    "    int val = myPtrArray[3];\n"
                    "    return val + 3;\n"
                    "}\n"
                    "return -1;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target asm loads through a pointer AFTER the null "
                    "check, move the load inside the null-guarded branch. "
                    "MWCC treats pre-check loads through possibly-null "
                    "pointers as UB and hoists them down."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lwz", "lbz", "cmplwi", "beq"],
        categories=["branch", "register", "loop"],
        provenance=Provenance(),
        notes="Discord 2021-12-20 (revosucks).",
    ),
    Pattern(
        id="comma-operator-load-rebind",
        name="`(0, expr)` comma-operator trick to rebind call result to fresh register",
        description=(
            "Wrap a function call or expression in `(0, expr)` to force "
            "MWCC to treat the result as a fresh temporary, reseating its "
            "register binding. Permuter-discovered fix. The discarded `0` "
            "creates an extra evaluation point that changes register flow."
        ),
        root_cause=(
            "Comma operator evaluates both sides; result is the right "
            "operand. The literal `0` on the left forces an extra "
            "evaluation step that the compiler materializes in a register "
            "before discarding, perturbing register allocation."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz", "actual": "lwz"},
                description="Same opcode but different register destination",
            ),
        ],
        examples=[
            Example(
                function="permuter-discovered fix",
                before=(
                    "int shop_level = mSP_GetShopLevel();\n"
                ),
                after=(
                    "// Comma-operator wraps to rebind register:\n"
                    "int shop_level = (0, mSP_GetShopLevel());\n"
                ),
                context="Permuter fix reaching 99.89%",
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "For stubborn regswaps around a function call result, "
                    "wrap the call in `(0, expr)`. The discarded literal "
                    "shifts register allocation. Fakematch-adjacent but "
                    "reliable when permuter finds it."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=[],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord 2023-10-19 (.cuyler) - permuter-discovered.",
    ),
    Pattern(
        id="else-return-null-extra-branch-fix",
        name="Add explicit `else return NULL;` for extra `b` that fixes trailing regswaps",
        description=(
            "Adding an explicit `else return NULL;` (or `return nullptr;`) "
            "at the bottom of an early-out chain fixes most regswaps in "
            "the trailing block at the cost of an extra unconditional `b`. "
            "Use when float regswaps in the tail won't budge any other way."
        ),
        root_cause=(
            "Explicit else-return forces an extra basic block at the tail. "
            "The extra `b` changes which registers are live going into the "
            "trailing code, often re-allocating in the desired order."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["b epilogue", "epilogue:"]},
                description="Extra unconditional branch before epilogue",
            ),
        ],
        examples=[
            Example(
                function="generic early-out",
                before=(
                    "if (cond) {\n"
                    "    return found;\n"
                    "}\n"
                    "// Implicit fall-through to NULL return\n"
                    "return NULL;\n"
                ),
                after=(
                    "if (cond) {\n"
                    "    return found;\n"
                    "} else {\n"
                    "    return NULL;\n"
                    "}\n"
                    "// Extra `b` emitted; trailing regswaps resolve\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "Try wrapping a trailing `return NULL` (or similar) in "
                    "an explicit `else` branch. The extra `b` instruction "
                    "in asm can fix multiple trailing regswaps at once. "
                    "Use as fallback when other regswap tricks fail."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["b"],
        categories=["control-flow", "register"],
        provenance=Provenance(),
        notes="Discord 2022-09-17 (vetroidmania).",
    ),
    Pattern(
        id="deferred-inline-reorders-source-functions",
        name="`-inline deferred` reorders function bodies — match by reversing source",
        description=(
            "When a TU is compiled with `-inline deferred`, MWCC reorders "
            "function bodies in the .text section (later definitions emit "
            "FIRST). To match, you must physically reverse the order of "
            "function definitions in the source file. Misalignment shows "
            "as widespread regswaps that look unrelated."
        ),
        root_cause=(
            "Deferred inlining processes the whole TU before emitting. The "
            "emission order is reversed vs source order. If you put the "
            "callee BEFORE the caller in source, but the asm has the "
            "caller first, the source order is wrong."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<funcA at offset N>", "actual": "<funcB at offset N>"},
                description="Function bodies in wrong positions within .text",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Source order doesn't match deferred-inline output:\n"
                    "void helper(void) { ... }\n"
                    "void caller(void) { helper(); }\n"
                ),
                after=(
                    "// Reversed - matches -inline deferred:\n"
                    "void caller(void);  // forward decl\n"
                    "void caller(void) { helper(); }\n"
                    "void helper(void) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If multiple functions in a TU have unrelated "
                    "regswaps, and the project uses -inline deferred, "
                    "try reversing the source order of function "
                    "definitions. Add forward declarations as needed."
                ),
                success_rate=0.9,
            ),
        ],
        opcodes=[],
        categories=["calling-conv", "data-layout"],
        provenance=Provenance(),
        notes="Discord 2025-05-18 (chippy).",
    ),
    Pattern(
        id="asymmetric-temp-extraction-across-branches",
        name="Asymmetric temp extraction — extract in ONE branch only",
        description=(
            "Counterintuitively, pulling a repeated subexpression into a "
            "temp in ONE branch of an if/else (or one case of a chain) "
            "while leaving the other branches inline can fix regswaps. "
            "Symmetric extraction often regresses; asymmetric matches."
        ),
        root_cause=(
            "Each branch has different register pressure. Extracting a "
            "temp in only the heavier-pressure branch lets MWCC commit to "
            "a register early there, while the lighter branch keeps the "
            "field load fused with its consumer."
        ),
        signals=[],
        examples=[
            Example(
                function=".cuyler now_sec pattern",
                before=(
                    "// Symmetric — both branches inline:\n"
                    "if (a) { use(obj->now_sec); }\n"
                    "else if (b) { use(obj->now_sec); }\n"
                ),
                after=(
                    "// Asymmetric — temp only in if:\n"
                    "if (a) {\n"
                    "    int t = obj->now_sec;\n"
                    "    use(t);\n"
                    "} else if (b) {\n"
                    "    use(obj->now_sec);  // inline\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When symmetric extraction or symmetric inlining "
                    "doesn't match, try asymmetric: temp in one branch, "
                    "inline in the other. Resists intuition but works."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=[],
        categories=["register", "branch"],
        provenance=Provenance(),
        notes="Discord 2023-10-01 (.cuyler).",
    ),
    Pattern(
        id="redefine-file-macro-regswap",
        name="`#define __FILE__ \"name\"` redefine cascades into regswaps",
        description=(
            "Redefining `__FILE__` at the top of a TU (often to strip a "
            "path or insert a custom assert string) changes the .rodata "
            "layout, which shifts SDA eligibility and relocation types. "
            "These changes cascade into register allocation downstream — "
            "fixing a string layout sometimes unblocks regswaps."
        ),
        root_cause=(
            "MWCC's regalloc considers literal-pool size when picking "
            "registers. Changing __FILE__ shifts the pool, which can "
            "tip variables into different SDA-eligibility states, which "
            "rebalances callee-saved register usage."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lwz @sda21", "actual": "addis+lwz @ha/@l"},
                description="SDA vs non-SDA addressing affecting reg flow",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// At top of file:\n"
                    "#undef __FILE__\n"
                    "#define __FILE__ \"Navi.cpp\"\n"
                    "\n"
                    "// Rest of file...\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If asserts use `__FILE__` and the asm shows specific "
                    "string-table layout you can't reproduce, try "
                    "redefining `__FILE__` at TU scope to match the "
                    "expected file name string."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=[],
        categories=["data-layout", "register"],
        provenance=Provenance(),
        notes="Discord 2025-05-18 (.cuyler); epochflame examples.",
    ),
    Pattern(
        id="inlining-reverses-regalloc-order",
        name="Same function: inlined vs out-of-line uses opposite register order",
        description=(
            "MWCC sometimes allocates registers in OPPOSITE order at an "
            "inline site vs at an out-of-line call. If the function "
            "matches as `static inline` but not as a separate function "
            "(or vice versa), the difference may be inline-vs-out "
            "register allocation. Toggle inlining with `auto_inline` "
            "pragma or size threshold."
        ),
        root_cause=(
            "Inlining changes the surrounding register-pressure context. "
            "MWCC's allocator picks registers based on what's already "
            "live, so the same function body gets different assignments "
            "depending on inline state."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "stw r29", "actual": "stw r30"},
                description="Register order flipped between inline/out-of-line",
            ),
        ],
        examples=[
            Example(
                function="m8 observation",
                context=(
                    "If out-of-line version matches but inlined doesn't "
                    "(or vice versa), force the other state to test."
                ),
                after=(
                    "// Force inlining:\n"
                    "static inline T func(...) { ... }\n"
                    "\n"
                    "// Force out-of-line:\n"
                    "#pragma auto_inline off\n"
                    "static T func(...) { ... }\n"
                    "#pragma auto_inline on\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When a function is close to matching but registers "
                    "are flipped, toggle its inline state. Inlined vs "
                    "out-of-line can have opposite r3/r4/r5 or r29-r31 "
                    "assignments."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["stmw", "stw"],
        categories=["inline", "register"],
        provenance=Provenance(),
        notes="Discord 2023-11-04 (m8).",
    ),
    Pattern(
        id="volatile-int-forces-addic-dot",
        name="`volatile int` on a global forces `addic.` codegen instead of `cmpwi`",
        description=(
            "When a global int counter is decremented and tested in one "
            "expression (`if (counter--)`), MWCC may emit separate "
            "`addi`/`cmpwi` instead of the expected fused `addic. r,r,-1`. "
            "Marking the global as `volatile int` forces the `addic.` "
            "form — likely matching what devs had with a debug watch."
        ),
        root_cause=(
            "Volatile semantics force the read-modify-write to be visible. "
            "MWCC emits `addic.` (add immediate carrying, dot = set CR0) "
            "to do both the decrement and zero-test in one instruction. "
            "Non-volatile gets optimized differently."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "addic.", "actual": "addi+cmpwi"},
                description="Fused decrement-and-test vs separate ops",
            ),
        ],
        examples=[
            Example(
                function="snIntCount counter",
                before=(
                    "int snIntCount;\n"
                    "// emits: lwz, addi, stw, cmpwi r,0, beq\n"
                    "if (snIntCount--) { ... }\n"
                ),
                after=(
                    "volatile int snIntCount;\n"
                    "// emits: lwz, addic. r,r,-1, stw, beq\n"
                    "if (snIntCount--) { ... }\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If target uses `addic.` for a decrement-and-test on "
                    "a global, mark the global as `volatile int`. Forces "
                    "the fused instruction."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["addic.", "addi", "cmpwi"],
        categories=["type", "branch", "register"],
        provenance=Provenance(),
        notes="Discord 2023-03-08 (estexnt, heartpiece).",
    ),
    Pattern(
        id="stripped-debug-macro-leaves-side-effect",
        name="Debug macro stripped to `__VA_ARGS__` leaves expression that affects regalloc",
        description=(
            "A debug `PRINT(fmt, ...)` macro stripped to `__VA_ARGS__` "
            "(rather than removed entirely) leaves the arguments as "
            "discarded expressions. MWCC still evaluates them, perturbing "
            "register allocation. Common when matching release builds "
            "compiled from debug-printf-rich source."
        ),
        root_cause=(
            "`#define PRINT(fmt, ...) __VA_ARGS__` keeps the args alive "
            "as expression statements. The compiler emits the loads but "
            "no consumer, which still affects register lifetimes."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "lwz", "context": "load with no consumer"},
                description="Dead load from a stripped debug macro",
            ),
        ],
        examples=[
            Example(
                function="Pikmin precedent (kiwidev/mrkol)",
                after=(
                    "// In a header:\n"
                    "#define PRINT(fmt, ...) __VA_ARGS__\n"
                    "\n"
                    "// In source:\n"
                    "PRINT(\"name=%s\", obj->name);\n"
                    "// Even with PRINT 'stripped', obj->name is "
                    "evaluated\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has extra loads with no apparent consumer "
                    "in C, look for debug PRINT/LOG macros stripped to "
                    "`__VA_ARGS__`. The stripped expressions still affect "
                    "regalloc."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz"],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord 2025-01-12 (mrkol, kiwidev).",
    ),
    Pattern(
        id="pool-disabling-static-double-in-inline",
        name="`static const double` inside inline disables data pooling for the TU",
        description=(
            "An MSL-style `static const double _half = 0.5;` inside an "
            "inline function (like the Newton-Raphson sqrt body) disables "
            "MWCC's data pooling for the rest of the emission until later "
            "data declarations re-enable it. Header inclusion order "
            "becomes load-bearing: include order changes the pool state."
        ),
        root_cause=(
            "MWCC bug in versions before CW 3.0: encountering a function-"
            "scope `static const` of a wide type (double, etc.) disables "
            "the global literal-pool optimization. Subsequent f32/f64 "
            "constants get their own .rodata symbols instead of being "
            "pooled."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "lfs N(rPool)", "actual": "lis+lfs @ha/@l"},
                description="Pooled vs unpooled float constant load",
            ),
        ],
        examples=[
            Example(
                function="MSL sqrtf inline",
                context=(
                    "Including a header with `static inline float sqrtf` "
                    "(containing `static const double _half = 0.5`) "
                    "BEFORE pooled float data disables pooling for "
                    "everything after."
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If asm shows unpooled (individual @ha/@l) loads of "
                    "f32/f64 constants you expected to be pooled, check "
                    "header inclusion order. Headers containing inlines "
                    "with `static const double` must be included AFTER "
                    "the pooled data declarations."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lfs", "lfd", "addis"],
        categories=["float", "data-layout"],
        provenance=Provenance(),
        notes="Discord 2024-11-09 (revo/cuyler/chippy); fixed in CW 3.0.",
    ),
    Pattern(
        id="register-keyword-respected-by-mwcc",
        name="`register` keyword still respected by MWCC for allocation hints",
        description=(
            "Modern compilers ignore the `register` keyword, but MWCC "
            "(1.2.5n) honors it as an allocation hint. Useful when a loop "
            "temp like a `next` pointer is being aggressively reused and "
            "you need it in its own register: "
            "`register UnkStruct* next = obj->unk0;`"
        ),
        root_cause=(
            "Older C compilers respected `register` as a 'try to keep this "
            "in a register' hint. MWCC inherits this behavior. Also "
            "required for some inline-asm operand bindings."
        ),
        signals=[],
        examples=[
            Example(
                function="generic loop",
                after=(
                    "// register hint for a tight loop temp:\n"
                    "for (cur = list_head; cur != NULL; cur = next) {\n"
                    "    register UnkStruct* next = cur->next;  // hint\n"
                    "    process(cur);\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When a loop temp is being reused / collapsed in your "
                    "code but target keeps it in a dedicated register, "
                    "try adding `register` keyword. MWCC respects it as "
                    "a hint."
                ),
                success_rate=0.5,
            ),
        ],
        opcodes=["lwz", "mr"],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord 2022-05-16 (revo).",
    ),
    Pattern(
        id="savegpr-restgpr-5-store-threshold",
        name="5+ callee-saved register stores trigger `_savegpr_N`/`_restgpr_N` slide calls",
        description=(
            "MWCC's threshold for using `bl _savegpr_N` slide functions "
            "(instead of inline `stw r27...` series) is approximately 5 "
            "register saves. Below 5: inline stw/lwz; 5 or more: slide "
            "call. Diagnostic for predicting whether a function should "
            "use savegpr/restgpr helpers."
        ),
        root_cause=(
            "Slide functions trade a `bl` for ~3 instructions vs ~5 inline "
            "stores. At 5+ saves, the slide is shorter. MWCC's prologue "
            "emitter picks based on this threshold."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "bl _savegpr_N", "actual": "stw r27..stw r31"},
                description="Slide call vs inline stores",
            ),
        ],
        examples=[
            Example(
                function="generic",
                after=(
                    "// 5+ callee-saved -> slide call expected:\n"
                    "void f(void) {\n"
                    "    // body using r27, r28, r29, r30, r31\n"
                    "}\n"
                    "// emits: bl _savegpr_27 ... bl _restgpr_27\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target uses `bl _savegpr_N`/`_restgpr_N`, the "
                    "function saves 5+ callee-saved regs. When it uses "
                    "individual stw/lwz, fewer than 5. Match by adjusting "
                    "callee-saved usage."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["bl", "stw", "lwz"],
        categories=["stack", "calling-conv"],
        provenance=Provenance(),
        notes="Discord 2024-10-28 (muff1n1634, ieee802dot11ac).",
    ),
    Pattern(
        id="ternary-float-zero-rewrite-as-if-else",
        name="`f32 x = cond ? y : 0.0f;` silently rewritten as if-else with init",
        description=(
            "MWCC rewrites `f32 x = cond ? y : 0.0f;` into "
            "`f32 x = 0.0f; if (cond) x = y;`. The rewrite changes float "
            "register allocation. If target asm shows an unconditional "
            "`lfs f?, _zero` followed by a conditional load of y, the "
            "source must use the explicit if-else form, not the ternary."
        ),
        root_cause=(
            "MWCC pre-computes the constant operand of a fp-zero ternary "
            "into a register, then conditionally overwrites if needed. "
            "Equivalent to the if-else form but with explicit init."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lfs fN, _zero", "cmpwi", "beq", "lfs fN, value"]},
                description="Unconditional zero load + conditional overwrite",
            ),
        ],
        examples=[
            Example(
                function="generic",
                before=(
                    "// Ternary - gets rewritten:\n"
                    "f32 thing = x ? y : 0.0f;\n"
                ),
                after=(
                    "// Explicit if-else - matches:\n"
                    "f32 thing = 0.0f;\n"
                    "if (x) thing = y;\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has unconditional zero load + conditional "
                    "overwrite for a float, use explicit `T x = 0.0f; if "
                    "(cond) x = y;` rather than `T x = cond ? y : 0.0f;`."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lfs", "cmpwi", "beq"],
        categories=["float", "branch"],
        provenance=Provenance(),
        notes="Discord (mrkol).",
    ),
    Pattern(
        id="gobj-duplicate-expression-vs-temp",
        name="Duplicate `gobj->member` expression instead of caching in temp",
        description=(
            "When a parameter is read once then passed to several callees, "
            "MWCC may assign it to the 'wrong' register. Duplicating the "
            "dereference at each callsite (re-reading `arg->member`) "
            "forces a second load and a different register selection. "
            "Opposite of the usual 'cache in a temp' advice."
        ),
        root_cause=(
            "Cached value lives in one register chosen at the cache "
            "point. Each duplicate read lets MWCC pick a fresh register "
            "for that specific call site's argument register."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz rA,off(gobj)", "bl foo", "lwz rB,off(gobj)", "bl bar"]},
                description="Two loads at different registers vs one cached",
            ),
        ],
        examples=[
            Example(
                function="generic ninji pattern",
                before=(
                    "// Cache picks wrong reg for second callee:\n"
                    "SomeType* p = gobj->member;\n"
                    "foo(p);\n"
                    "bar(p);\n"
                ),
                after=(
                    "// Duplicate dereference - separate loads:\n"
                    "foo(gobj->member);\n"
                    "bar(gobj->member);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When register assignment is wrong at a specific call "
                    "site, duplicate the dereference of the gobj pointer "
                    "rather than caching it. Each call gets its own load "
                    "into the proper argument register."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz", "mr"],
        categories=["register", "calling-conv"],
        provenance=Provenance(),
        notes="Discord (ninji).",
    ),
    Pattern(
        id="discarded-addressof-forces-stack-spill",
        name="`(void)(&local);` forces stack spill of the local",
        description=(
            "Using `(void)(&local);` (discard the address-of expression) "
            "forces MWCC to spill the local to the stack rather than "
            "keeping it in a register only. Useful when target frame "
            "layout has a stack slot that your code doesn't allocate."
        ),
        root_cause=(
            "Taking the address of a local requires the local to have a "
            "memory location (escape analysis). Even a discarded `&local` "
            "is enough to force allocation in the frame. The `(void)` "
            "cast drops the result."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "stw", "context": "spill of register-resident local"},
                description="Extra stack store appears for the local",
            ),
        ],
        examples=[
            Example(
                function="gamemasterplc BoardPlayerGetCurr fix",
                after=(
                    "PlayerState* player_temp;\n"
                    "player_temp = SpacePlayerGetCurr();\n"
                    "(void) (&player_temp);  // forces stack spill\n"
                    "return boardPlayerMdl[player_temp->player_idx];\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target spills a local you keep in a register, "
                    "add `(void) (&local);` as a statement to force the "
                    "spill via address-of."
                ),
                success_rate=0.75,
            ),
        ],
        opcodes=["stw", "lwz"],
        categories=["stack", "register"],
        provenance=Provenance(),
        related_patterns=["discard-expression-statement-regalloc"],
        notes="Discord (gamemasterplc).",
    ),
    Pattern(
        id="wrong-return-type-affects-distant-regalloc",
        name="Function declared with wrong return type (`void` vs `int`) affects regalloc around its call",
        description=(
            "Changing a callee's declared return type — even when the "
            "caller discards the return — changes register allocation "
            "AROUND the call. If declared `int`, r3 is live-out (compiler "
            "preserves it). If declared `void`, r3 is dead and freed. "
            "Toggle the prototype's return type when stuck on regswaps "
            "near a discarded call."
        ),
        root_cause=(
            "MWCC's liveness analyzer trusts function prototypes. An "
            "int-returning callee makes r3 live across the call; a void "
            "callee frees r3 immediately. The choice cascades through "
            "subsequent register pressure."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<r3 preserved>", "actual": "<r3 reused>"},
                description="r3 liveness differs across call",
            ),
        ],
        examples=[
            Example(
                function="LoadTexture prototype toggle",
                before=(
                    "void LoadTexture(int id);  // r3 freed\n"
                    "// Caller code regswaps around the call\n"
                ),
                after=(
                    "s32 LoadTexture(int id);  // r3 stays live\n"
                    "// Caller discards return but regs match now\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If a function call has regswaps in surrounding code, "
                    "try changing its declared return type between `void` "
                    "and `s32` (or another non-void). Affects r3 liveness "
                    "across the call."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=[],
        categories=["calling-conv", "register"],
        provenance=Provenance(),
        notes="Discord (gamemasterplc).",
    ),
    Pattern(
        id="explicit-narrow-cast-on-return",
        name="`return (ushort) i;` explicit narrowing cast — collapses implicit cast that shifts regs",
        description=(
            "When a function returns a small unsigned type (`u16`/`u8`) "
            "and the body is `return i;` with `i` as the narrow type, "
            "MWCC inserts an implicit cast that shifts every register by "
            "one. Explicit cast `return (ushort) i;` collapses the cast."
        ),
        root_cause=(
            "Implicit narrowing cast at return materializes the masked "
            "value in a separate register before move-to-r3. Explicit "
            "cast lets MWCC fold the mask into the existing register."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "clrlwi", "context": "narrowing at return"},
                description="Extra mask + register shift",
            ),
        ],
        examples=[
            Example(
                function="GetFreeChannel ninji+chippy fix",
                before=(
                    "u16 GetFreeChannel(void) {\n"
                    "    u16 i;\n"
                    "    for (i = 0; i < 4; ++i) {\n"
                    "        if (free(i)) return i;  // implicit cast\n"
                    "    }\n"
                    "    return 0;\n"
                    "}\n"
                ),
                after=(
                    "u16 GetFreeChannel(void) {\n"
                    "    u16 i;\n"
                    "    for (i = 0; i < 4; ++i) {\n"
                    "        if (free(i)) return (u16) i;  // explicit\n"
                    "    }\n"
                    "    return 0;\n"
                    "}\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When a narrow-type return causes cascading regswaps, "
                    "add an explicit `(u16)`/`(u8)` cast on the returned "
                    "value. The cast on a same-type value still affects "
                    "codegen."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["clrlwi"],
        categories=["type", "register"],
        provenance=Provenance(),
        notes="Discord (ninji, chippy).",
    ),
    Pattern(
        id="r6-r6-literal-self-assign-elision",
        name="`r6 = r6 = 0x18;` self-assign-to-literal elides register copy",
        description=(
            "In a conditional that picks between an expression and a "
            "literal, writing `r6 = r6 = 0x18;` (chained self-assign to "
            "literal) keeps both branches in the same register without "
            "emitting `mr`. Different from the simple self-assign trick: "
            "the chained form is specifically for literal+self-assign."
        ),
        root_cause=(
            "MWCC parses `a = b = expr` as `b = expr; a = b;`. When `a` "
            "and `b` are the same variable, the trivial self-assign is "
            "elided AFTER the literal load. Eliminates the move that "
            "would otherwise appear in the else-branch."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "li", "actual": "mr+li"},
                description="Direct literal load vs move-then-load",
            ),
        ],
        examples=[
            Example(
                function="camthesaxman pattern",
                before=(
                    "if (r6 < 0x18) r6 = r4 + 1;\n"
                    "else r6 = 0x18;\n"
                ),
                after=(
                    "if (r6 < 0x18) r6 = r4 + 1;\n"
                    "else r6 = r6 = 0x18;  // self-assign chain\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When else-branch has an extra `mr` before a literal "
                    "load, try `x = x = LITERAL;` chained self-assign. "
                    "Forces direct literal load into the same register."
                ),
                success_rate=0.6,
            ),
        ],
        opcodes=["li", "mr"],
        categories=["register", "branch"],
        provenance=Provenance(),
        related_patterns=["self-assignment-for-regalloc", "subfic-implies-chained-assignment"],
        notes="Discord 2022-01-23 (camthesaxman).",
    ),
    Pattern(
        id="decl-init-vs-decl-then-assign-struct-copy",
        name="`T x = expr;` vs `T x; x = expr;` differ for struct types (copy elision)",
        description=(
            "For struct-typed locals, `T x = expr;` (declaration with "
            "initializer) and `T x; x = expr;` (split form) generate "
            "different code. The split form may introduce an extra "
            "struct-copy / temp. Counter-pattern: assignment from a "
            "function returning a struct is sometimes worse in the joined "
            "form. Test both."
        ),
        root_cause=(
            "MWCC's copy-elision heuristics differ for direct-init vs "
            "assign. Direct-init can place the new struct directly in the "
            "target's stack slot; assign-after-decl may copy from a temp."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz", "stw", "lwz", "stw"]},
                description="Extra struct copy via stw/lwz pairs",
            ),
        ],
        examples=[
            Example(
                function="ninji + camthesaxman 2023-01-03",
                before=(
                    "// Split - may emit extra copy:\n"
                    "Vec v;\n"
                    "v = compute_vec();\n"
                ),
                after=(
                    "// Direct-init - copy elided:\n"
                    "Vec v = compute_vec();\n"
                ),
            ),
            Example(
                function="compound literal counter-case",
                before=(
                    "// Sometimes split is better:\n"
                    "Vec v = (Vec){1, 0, 1};\n"
                ),
                after=(
                    "// Try split if direct emits extra copy:\n"
                    "Vec v;\n"
                    "v = (Vec){1, 0, 1};\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "For struct locals with extra-copy regswaps, toggle "
                    "between direct-init `T x = expr;` and split "
                    "`T x; x = expr;`. The right form depends on whether "
                    "expr is a function call or compound literal."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz", "stw"],
        categories=["struct", "register"],
        provenance=Provenance(),
        notes="Discord 2023-01-03 (ninji, camthesaxman).",
    ),
    Pattern(
        id="const-aggregate-forces-double-copy",
        name="`const T agg = func(...)` forces double load/store pair when copied",
        description=(
            "Declaring an aggregate (e.g., `lldiv_t`) as `const` forces "
            "MWCC to emit paired load/store sequences when copying it. "
            "Matches asm that has more memory traffic than the source "
            "appears to require."
        ),
        root_cause=(
            "`const` forces the compiler to materialize the value in "
            "memory (where const can be enforced) rather than keep it in "
            "registers. Subsequent uses copy via memory, generating "
            "paired stw/lwz or stfd/lfd."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["stfd", "lfd", "stfd"]},
                description="Double f64 copy pair",
            ),
        ],
        examples=[
            Example(
                function=".cuyler lldiv_t fix",
                before=(
                    "// Mutable - no extra copy:\n"
                    "lldiv_t r = lldiv(a, b);\n"
                ),
                after=(
                    "// const - extra copy via stack:\n"
                    "const lldiv_t r = lldiv(a, b);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When asm has paired load/store for a struct that "
                    "your source doesn't seem to copy, try declaring the "
                    "struct as `const`. Forces memory materialization."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["stfd", "lfd", "stw", "lwz"],
        categories=["struct", "type", "register"],
        provenance=Provenance(),
        notes="Discord 2023-02-23 (.cuyler).",
    ),
    Pattern(
        id="parenthesize-addition-for-eval-order",
        name="`(A + B) - 1` vs `(A - 1) + B` — explicit parens fix eval order",
        description=(
            "For `A + B - 1`, MWCC evaluates left-to-right by default. "
            "Parenthesizing `(A - 1) + B` forces the constant fold first, "
            "avoiding a temporary register. Eliminates an `mr` (register "
            "copy) by reordering the `addi`/`add`."
        ),
        root_cause=(
            "Without parens, left-to-right means A+B first (var+var, "
            "needs temp), then `-1` (immediate). With parens, A-1 first "
            "(folds to one addi), then +B (another addi). Saves the temp."
        ),
        signals=[
            Signal(
                type="extra_instruction",
                data={"opcode": "mr", "context": "intermediate temp"},
                description="Extra mr for unparenthesized eval order",
            ),
        ],
        examples=[
            Example(
                function="altafen pattern",
                before=(
                    "result = arg0 + one_var - 1;\n"
                    "// emits: add (temp); addi -1\n"
                ),
                after=(
                    "result = (arg0 - 1) + one_var;\n"
                    "// emits: addi -1; add (no extra mr)\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target has fewer adds/mrs than your source, "
                    "parenthesize to force constant folds to happen "
                    "first. `(A-1)+B` is cleaner than `A+B-1`."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["addi", "add", "mr"],
        categories=["register"],
        provenance=Provenance(),
        notes="Discord 2022-04-01 (altafen).",
    ),
    Pattern(
        id="wrong-typed-static-blocks-r3-release",
        name="Static prototype mismatch (declared `int`, actually `void`) blocks r3 release",
        description=(
            "Marking a `void`-returning function as `static int` (or any "
            "non-void) prevents MWCC from freeing r3 after the call. r3 "
            "stays live across the call boundary, blocking subsequent "
            "allocations and forcing later loads into higher registers. "
            "Cascading regswap fix: correct the prototype."
        ),
        root_cause=(
            "Wrong return type lies to the liveness analyzer. The "
            "compiler assumes r3 holds a meaningful value across the call "
            "and won't reassign it. Real `void` correctly frees r3."
        ),
        signals=[
            Signal(
                type="opcode_mismatch",
                data={"expected": "<r3 freed>", "actual": "<r3 live>"},
                description="r3 liveness mismatch across call",
            ),
        ],
        examples=[
            Example(
                function=".cuyler 2023-10-11 fix",
                before=(
                    "// Wrong: declared int but is void\n"
                    "static int mMkRm_NoMarkLetter_Hint(...);\n"
                ),
                after=(
                    "// Correct:\n"
                    "static void mMkRm_NoMarkLetter_Hint(...);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "If r3 is unexpectedly live across a void-call, check "
                    "the prototype. Mistyped as int/s32 will keep r3 live. "
                    "Always match return type to the actual function."
                ),
                success_rate=0.95,
            ),
        ],
        opcodes=[],
        categories=["calling-conv", "register"],
        provenance=Provenance(),
        related_patterns=["wrong-return-type-affects-distant-regalloc"],
        notes="Discord 2023-10-11 (.cuyler).",
    ),
    Pattern(
        id="inverted-arg-order-vec-setter",
        name="Inline setter with REVERSED arg order to match z-y-x load sequence",
        description=(
            "An inline vector setter that takes args in REVERSE order "
            "(`set(z, y, x)` storing to `x, y, z`) generates the load "
            "sequence matching asm that loads vector components in "
            "z->y->x order. Counter-intuitive but matches Nintendo-style "
            "vector setter codegen."
        ),
        root_cause=(
            "MWCC evaluates argument expressions left-to-right. Reversed "
            "param order means z-load first, then y-load, then x-load, "
            "matching the target's load schedule."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz z", "lwz y", "lwz x", "stw x", "stw y", "stw z"]},
                description="Loads in reverse, stores in normal order",
            ),
        ],
        examples=[
            Example(
                function="shibboleet SMG pattern",
                after=(
                    "// Reverse param order:\n"
                    "static inline void set(int z, int y, int x)\n"
                    "{\n"
                    "    obj->vec.x = x;\n"
                    "    obj->vec.y = y;\n"
                    "    obj->vec.z = z;\n"
                    "}\n"
                    "\n"
                    "// Called as:\n"
                    "obj->set(a->z, a->y, a->x);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When inline setter's load order is reversed vs your "
                    "C, try reversing the parameter order. Caller passes "
                    "args in reverse field order; body stores in normal "
                    "order."
                ),
                success_rate=0.85,
            ),
        ],
        opcodes=["lwz", "stw"],
        categories=["inline", "calling-conv", "struct"],
        provenance=Provenance(),
        notes="Discord 2023-03-07 (shibboleet, SMG project).",
    ),
    Pattern(
        id="local-shadows-global-load-order",
        name="Local alias of a global forces early load of the global",
        description=(
            "Assigning a global to a local variable BEFORE a function "
            "call (where the call also touches the global) forces MWCC "
            "to emit an early load of the global. Distinct from "
            "pre-loaded-root-variable: this is about NAMED globals, not "
            "derived pointers."
        ),
        root_cause=(
            "Local alias creates an early use of the global, which "
            "anchors the lwz at the local's assignment point. Without "
            "the local, MWCC may delay or reorder the load relative to "
            "other instructions."
        ),
        signals=[
            Signal(
                type="instruction_sequence",
                data={"sequence": ["lwz rN,glob@sda21(r13)", "<other>", "bl func"]},
                description="Early load of global before call",
            ),
        ],
        examples=[
            Example(
                function="lbArchive_LoadSections pattern",
                before=(
                    "// Direct use - load deferred:\n"
                    "LoadSections(mn_804D6BB8, args);\n"
                ),
                after=(
                    "// Local alias - load happens earlier:\n"
                    "HSD_Archive* archive = mn_804D6BB8;\n"
                    "LoadSections(archive, args);\n"
                ),
            ),
        ],
        fixes=[
            Fix(
                description=(
                    "When target loads a global earlier than your code "
                    "does, alias it to a local: `T* x = global;` then "
                    "use `x` later. The local declaration anchors the "
                    "load at its position."
                ),
                success_rate=0.7,
            ),
        ],
        opcodes=["lwz"],
        categories=["register", "data-layout"],
        provenance=Provenance(),
        related_patterns=["pre-loaded-root-variable-load-order"],
        notes="Discord; lbArchive_LoadSections pattern from MEMORY.md.",
    ),
]


def main():
    db_path = DEFAULT_DB_PATH
    conn = init_db(db_path)
    db = PatternDB(conn)

    inserted = 0
    updated = 0

    for pattern in PATTERNS:
        existing = db.get(pattern.id)
        if existing is not None:
            print(f"  EXISTS: {pattern.id} — deleting and re-inserting")
            conn.execute("DELETE FROM patterns WHERE id = ?", (pattern.id,))
            conn.execute("DELETE FROM pattern_signals WHERE pattern_id = ?", (pattern.id,))
            conn.commit()
            db.insert(pattern)
            updated += 1
        else:
            db.insert(pattern)
            print(f"  ADDED:  {pattern.id}")
            inserted += 1

    print()
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print(f"Total patterns in DB now: {len(db.list_all())}")


if __name__ == "__main__":
    main()
