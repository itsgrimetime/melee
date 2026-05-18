# MWCC PowerPC Register Allocator — Algorithm Reference

Extracted from the [MWCC 7.0 source decompilation](https://git.wuffs.org/MWCC/tree/compiler_and_linker/BackEnd/PowerPC/RegisterAllocator) and verified against observed pcdump behavior in our 1.2.5n binary. This document is the answer to "why did MWCC pick this register?" — useful when stuck on register-allocation cascade mismatches.

## TL;DR

MWCC uses Chaitin-style graph coloring:

1. **Compute** `workingMask = volatile-regs (r3..r12) − interferers' assigned regs`
2. **If `workingMask` non-empty:** pick **lowest** set bit (i.e., lowest-numbered caller-save reg the virtual can use)
3. **Else:** call `obtain_nonvolatile_register()`. **Dispense order: r27, r28, r29, r30, r31, then r26, r25, r24, ...** (NOT top-down from r31 as one might assume). Once dispensed, the chosen reg is **added to the volatile pool** and can be reused for subsequent non-interfering virtuals.
4. **If nonvolatile fails too:** spill.

Note: `r0` is **excluded** from the normal volatile pool — it has special meaning in some PowerPC instructions and MWCC assigns it only as a scratch by the codegen, not the coloring pass.

## Why this matters

Most "stuck at 99%" register cascades come down to the allocator picking one specific physical reg instead of another. Understanding the algorithm tells you what changes to your C source might shift the decision:

- **Adding an interferer that occupies the "wrong" reg** can push the allocator to pick a different physical for your virtual.
- **Changing virtual numbering** (via declaration order, intermediate variables) can shift iteration order, which affects who gets first pick.
- **Eliminating a call** between two points removes caller-save kill and lets a virtual use r3..r12 instead of being forced to nonvolatile.

## Source (paraphrased from MWCC 7.0 Coloring.c)

```c
static int colorgraph(IGNode *node) {
    reset_nonvolatile_registers(coloring_class);
    volatileRegs = volatile_registers(coloring_class);

    while (node) {
        workingMask = volatileRegs;
        for (array = node->array, i = 0; i < node->arraySize; i++) {
            otherNode = interferencegraph[*(array++)];
            reg = otherNode->x14;  // x14 = assigned physical
            if (reg != -1 && reg < n_real_registers[coloring_class])
                workingMask &= ~(1 << reg);
        }

        if (workingMask) {
            for (i = 0; i < n_real_registers[coloring_class]; i++) {
                if (workingMask & (1 << i)) {
                    node->x14 = i;     // lowest set bit
                    break;
                }
            }
        } else {
            reg = obtain_nonvolatile_register(coloring_class);
            if (reg != -1) {
                volatileRegs |= 1 << (node->x14 = reg);  // sticky add
            } else {
                node->flags |= fSpilled;
            }
        }

        node = node->next;
    }
}
```

The IGNode (interference-graph node) wraps a virtual register with:
- `x14`: assigned physical register index (-1 = unassigned)
- `array`: indices of interfering nodes in `interferencegraph[]`
- `arraySize`: number of interferers
- `next`: linked-list pointer (built by `simplifygraph`)
- `flags`: includes `fSpilled` and `fPairLow`/`fPairHigh` for 64-bit values

## Concrete example: `mnVibration_80248644`

This function has two loops that allocate distinct sets of virtuals:

**Cleanup loop** (processed early in coloring iteration):
| Virtual | Live range | Crosses call? | workingMask result | Decision | Got |
|---|---|---|---|---|---|
| r38 | 2..14 | yes | empty (all callers killed) | `obtain_nonvolatile_register()` → idx 0 | r27 |
| r39 | 1..34 | yes | empty | obtain → idx 1 | r28 |
| r44 | 5..16 | yes | empty | obtain → idx 2 | r29 |
| r45 | 4..15 | yes | empty | obtain → idx 3 | r30 |
| r50 | 6..12 | yes | empty | obtain → idx 4 | r31 |

**J loop** (processed later, after cleanup-loop assignments are in the volatile pool):
| Virtual | Interferes with | workingMask | Decision | Got |
|---|---|---|---|---|
| r36 | r38, r35, r39, r41, r42 | (still empty due to call-crossing) | obtain — but r27 reusable (r38 doesn't interfere with r36 in subsequent context) | r27 |
| r35 | r32, r36, r39, r41, r42, r53, r54 | empty after interferers + call | obtain | r29 |

**r32** (special — lives entire function, interferes with everything):
| Virtual | Live range | workingMask | Decision | Got |
|---|---|---|---|---|
| r32 | 0..52 | empty | obtain — by now r27..r31 in pool but r32 interferes with their holders. Next dispense returns r26. | r26 |

The earlier "callee-save top-down from r31" intuition was wrong: r27 is dispensed FIRST. The reason cleanup-loop virtuals look like r27→r28→r29→r30→r31 is that they're allocated in that strict sequence, not picked freely.

## Using this in investigations

When stuck on a cascade:

1. Run `melee-agent debug pcdump <c-file> --output dump.txt`
2. Run `melee-agent debug analyze dump.txt --function <name>` to see live ranges + interferers
3. Run `melee-agent debug simulate dump.txt --function <name> --all` to see what the algorithm would predict + reasoning trace
4. Compare against actual:
   - **If simulator matches:** the algorithm is fully constrained. To change the outcome, change the C source to alter interferences, live ranges, or iteration order.
   - **If simulator diverges:** likely an iteration-order issue. Look at virtuals processed earlier than expected and ask why they take a different path.

## Limitations of the simulator vs. real binary

The simulator approximates because:

- **Iteration order** — we sort by ascending interferer count; real MWCC uses Chaitin simplification with spill-cost tie-breaking, which we can't replay without instrumenting the binary.
- **r0 handling** — MWCC assigns r0 as a non-coloring scratch in some cases; we don't model this and predict r3 instead.
- **Call interference** — we model "virtual lives across a call → loses caller-save"; real graph also includes ABI argument pinning for outgoing calls.
- **Pair registers** — for 64-bit (f64 pairs, long long), the IGNode has `fPairLow`/`fPairHigh` flags; we don't model.

When matches don't agree, treat the simulator output as a hypothesis to be tested, not ground truth.

## Future work

See [docs/mwcc-debug-future-ideas.md](mwcc-debug-future-ideas.md). The natural next step is **Tier 2 proper**: hook MWCC's actual `colorgraph` in `mwcceppc.exe` from the patched DLL, log every decision with workingMask + chosen + iteration index. That would let us replace the simulator's approximations with ground-truth observations.
