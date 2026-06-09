# lmgr326b.dll

This project generates `lmgr326b.dll`, a drop-in replacement .dll for the Metrowerks CodeWarrior v1.2.5n PPC compiler that enables diagnostic logging of its IR optimizer and PPC code generator. 

## Overview

While using ghidra/gdb to try and understand the compiler's decision making process, I found what looked to be dormant debugging code surrounding its IR optimizer and PPC code generator and tried to find information on it. While looking at a significantly newer version (7.0) of MWCC's decompiled [source code](https://git.wuffs.org/MWCC/) targeting `MSL_MacOS`, maintained by Ninji (shoutouts to furries), I saw that there was debugging functionality behind a compiler option `debug_listing` and debugging guards (`CW_ENABLE_IRO_DEBUG`, `CW_ENABLE_PCODE_DEBUG`) surrounding the code that it enabled.

I wanted to know if similar functionality existed in the compiler used for the Super Smash Brothers Melee decomp project. Amazingly, it did seemingly exist when looking for data related to it in the binary, however when trying `#pragma debuglisting on` it didn't have any meaninful output. Ghidra and gdb to the rescue.

The IR optimizer logging functionality was still available, just gated behind a flag that gets forced to `0` during init. I checked the PPC backend listing functions as well (`pclistblocks` et al), but these were compiled as empty stubs. This meant `CW_ENABLE_PCODE_DEBUG` ifdefed the actual code responsible for the PPC backend unlike the IR optimizer, but it turns out the operand formatting function `formatoperands` @ 0x4C4BF0 was still fully intact. It handles every PPC opcode with symbol names, register classes, alias annotations, etc. We just needed to call it.

The `lmgr326b.dll` that we ship with decomp is just a license manager stub that returns `0` for all three of its exported functions. This dll replacement re-exports those same stubs and does everything else to enable the debugging functionality from `DllMain`.

## Building

Building `lmgr326b.dll`:
```
build.bat
```

**Prerequisites**: MSVC x86 `cl.exe` with a usable Windows SDK

The compiler writes `pcdump.txt` to its working directory, and in the case of melee it's going to be the repo root when building via ninja. It overwrites whatever the previous `pcdump.txt` file was, so its debug information contents will be related to whatever the last compiled TU was.

## What it does

When `DllMain` runs:
- patch one byte in the compiler's `copts` init to set `debuglisting = 1` instead of `0` @ 0x42C8E1
- sets another debug output flag at `0x5882B8`
- sets up `jmp` hooks over the stubs
- on the first hook call, it opens `pcdump.txt` using the compiler's `fopen` @ 0x40C690

IR optimizer logging is entirely intact, we just enable it. The PPC backend debugging is done through walking the basic block list and calling `formatoperands` @ 0x4C4BF0 for each instruction. For some reason this function was not stubbed, only `pclistblocks`.

## Contents of pcdump.txt

### IR optimizer output

After enabling `debuglisting`, the IR optimizer's decisions for each compiled function are spelled out for you. This part is entirely the compiler's own code:
- unreachable code removal, dead assignment elimination
- copy/constant propagation, expression propagation
- loop detection, induction variables, unrolling decisions
- common subexpression elimination (CSE)
- jump chaining, branch simplification
- variable range splitting (use-define chains)
- pass iteration counts

All numbers in this section are IR node ids, internal identifying information for statements / expressions in the compiler's intermediate representation. They are not line numbers or instruction offsets.

# PPC backend output

The backend output consists of 9 passes per function showing the PPC code at each stage of the backend. Each pass dumps every basic block with successors, predecessors, labels, flags, and loop weight, followed by each instruction with full operand formatting.

Example:
```
:{0004}::::LOOPWEIGHT=0
B5: Succ={B6 B8 } Pred={B4 } Labels={L5 }

    lis     r152,HA(@774)
    addi    r153,r152,LO(@774)
    mr      r151,r153
    stw     r154,efLib_LoadKind(r0)
    bl      efLib_CreateGenerator; fLink
    cmpi    cr0,r32,1145
    bf      cr0,eq,B8
```

Before register coloring, registers are virtual (r32, r33, ...). After coloring, they are physical (r3, r4, ...). Comparing the BEFORE and AFTER REGISTER COLORING passes will show exactly how the allocator assigned registers. The operand text includes incredibly helpful information like symbol names for memory references, `HA()/LO()` for relocations, block names for branch targets, alias annotations after semicolons. It is a bit unreal.

All of this comes from the compiler's own `formatoperands` function. We just call it.

# IR optimizer output reference

## Layout

```
Starting function <name>
--------------------------------------------------------------------------------
<initial cleanup passes>
*****************
Dumps for pass=0
*****************
<optimization passes for iteration 0>
*****************
Dumps for pass=1
*****************
<optimization passes for iteration 1 - reruns on changed IR>
<variable range splitting at the end>
```

**In order**:
- the optimizer runs multiple iterations (denoted with pass=X)
- each iteration reruns the same set of passes
- if a pass changes the IR, another iteration is likely needed
- the optimizer stops when no more changes occur or the iteration limit is reached
  - this is seemingly usually 2 passes at O4

## Initial cleanup (before pass=0)

`Removing unreachable code at: 397`
- dead code elimination
- node identifier of removed code

`Removing goto next at 448`
- removes redundant gotos that jump to the immediately following block
- artifacts of front IR generation from switch cases
- if/else chains
- etc

## Copy and constant propagation

`Found propagatable assignment at: 8`
- found `x = y` or `x = constant` where x can be substituted at all use sites

`Found propagatable expression assignment at: 963`
- seemingly the same but for expressions like `x = a + b`

`Found expression propagation at 879 from 877`
- an actual propagation happened
  - expression from node 877 was substituted at node 879
  - directly affects register allocation since the intermediate variable may no longer need a register

## Dead code elimination

`Removing dead assignment 323`
- assignment where the result is never used
- often happens after propagation makes the original assignment dead

## Loop analysis

```
header = 343
l1 bit vector=
339-346
```

An example detection of a loop structure.
- `header` is the loop entry point node
- `l1 bit vector` is the set of nodes in the loop body

```
IRO_FindLoops_Unroll:Found loop with header 532
IsLoopUnrollable:No due to LP_INDUCTION_NOT_FOUND
```

An example of a loop unrolling analysis.
- a seemingly common rejection is `LP_INDUCTION_NOT_FOUND` which means no clear loop counter

## Common subexpression elimination (CSE)

```
   3: 5680 FN:191 CE:1 NS:0 Depends: 0,2-3,5,7,49,52,125
```
An example expression table entry.
- `CE:1` means the optimizer found this is a redundant computation
- `FN` is the flow node (basic block)
- `Depends` lists variable ids.

`Replacing common sub at 439 with 431`
- actual CSE replacement
- directly affects final assembly

## Branch optimization

`Removing branch around goto at 355`
- simplifies `if (cond) goto A; goto B; A:` into `if (!cond) goto B;`

`Chaining goto at 5628`
- jump threading
- goto targeting another goto gets redirected to the final destination
- large clusters seemingly suggest switch statements or many early returns?

## Variable range splitting

```
Splitting range for variable: 9
Def set: 70
Use set: 132
All defs: 11,17,24,33,40,51,61,70
All uses: 24-25,32,34-38,41,47,49-53,...
```
An example of splitting a variable's live range into smaller pieces.
- done for better register allocation
- directly relevant to register swaps
- different split points mean different register assignments

# Struct layouts and addresses (v1.2.5n)

For anyone continuing this work, i.e. porting to other CodeWarrior versions, these structure definitions were found with `gdb` and ghidra analysis while referring to the 7.0 decompilation referenced above as a loose guide for what to look for.

## PCode instruction (variable size)
```
+0x00: nextPCode (ptr)
+0x04: prevPCode (ptr)
+0x08: block (PCodeBlock*)
+0x14: op (short) - PCodeInfo.h opcode enum
+0x16: flags (short)
+0x1A: argCount (short)
+0x1C: args[0] (PCodeArg, each 12 bytes)
```

## PCodeBlock (48 bytes)
```
+0x00: nextBlock, +0x04: prevBlock
+0x08: labels (PCodeLabel*), +0x0C: predecessors (PCLink*), +0x10: successors (PCLink*)
+0x14: firstPCode, +0x18: lastPCode
+0x1C: blockIndex, +0x20: codeOffset, +0x24: loopWeight
+0x2E: flags (ushort)
```

## Statics
```
0x587C74: pcbasicblocks (PCodeBlock* linked list head)
0x580610: pcfile (FILE*)
0x584226: debuglisting flag (byte, forced to 0 (instruction @ 0x42C8E1) during init)
0x5882B8: static debug output guard (int)
0x44D580: debug_printf (checks guard, then fprintf to pcfile)
0x40C690: fopen
0x4C4BF0: formatoperands (the big switch, handles every opcode)
```
