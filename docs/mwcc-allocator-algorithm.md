# MWCC PowerPC Register Allocator — Algorithm Reference

Extracted from the [MWCC 7.0 source decompilation](https://git.wuffs.org/MWCC/tree/compiler_and_linker/BackEnd/PowerPC/RegisterAllocator) and verified against observed pcdump behavior in our 1.2.5n binary. This document is the answer to "why did MWCC pick this register?" — useful when stuck on register-allocation cascade mismatches.

## TL;DR

MWCC uses Chaitin-style graph coloring:

1. **Compute** `workingMask = volatile-regs (r3..r12) − interferers' assigned regs`
2. **If `workingMask` non-empty:** pick **lowest** set bit (i.e., lowest-numbered caller-save reg the virtual can use)
3. **Else:** call `obtain_nonvolatile_register()`. **Dispense order: r31, r30, r29, r28, r27, then r26, r25, r24, ...** (top-down from r31). Once dispensed, the chosen reg is **added to the volatile pool** and can be reused for subsequent non-interfering virtuals.
4. **If nonvolatile fails too:** spill.

Note: `r0` is **excluded** from the normal volatile pool — it has special meaning in some PowerPC instructions and MWCC assigns it only as a scratch by the codegen, not the coloring pass.

> **Verified via direct binary hook of `colorgraph` in mwcceppc.exe v1.2.5n
> (Tier 2):** the dispense order is unambiguously top-down. The earlier
> "r27 first" hypothesis was wrong — it came from misreading positional
> alignment.

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

Verified via the colorgraph hook in v1.2.5n. The function has 17 virtuals
across two loops. The first six virtuals to request a nonvolatile (in
iteration order, captured by the binary hook) and what they got:

| Iter | Virtual | Got | Why |
|---|---|---|---|
| 3 | r50 | r31 | 1st dispense — TOP of nonvolatile pool |
| 7 | r45 | r30 | 2nd dispense |
| 8 | r44 | r29 | 3rd dispense |
| 13 | r39 | r28 | 4th dispense |
| 14 | r38 | r27 | 5th dispense |
| 20 | r32 | r26 | 6th — r32 has degree 16 (interferes with everything), processed last; by then r27..r31 are in the volatile pool but r32 interferes with all their holders, so the next dispense (r26) is needed |

The cleanup-loop pattern r38→r27, r39→r28, r44→r29, r45→r30, r50→r31 is
NOT "ascending dispense" — it's the artifact of which virtual was processed
in which iteration, combined with TOP-DOWN dispense (r31 → r30 → ... → r26).

**Where does r36 → r27 come from?** r36 doesn't interfere with r38 (whose
live ranges don't overlap), so r36's workingMask later in iteration
includes r27 (which is in the volatile pool from r38's earlier dispense).
r36 ends up picking r27 from workingMask via the lowest-bit rule applied
within callee-save regs in the pool.

**Why didn't r36 get r31 then?** r36 DOES interfere with whoever holds r31
(specifically r50 — wait, our analyzer didn't show that interference;
likely a defect in our positional alignment). The binary hook is the
authoritative source for who interferes with whom.

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
