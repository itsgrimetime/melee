# hsd_803B3408 follow-up, 2026-09-06

The current source originates in merged PR3350 and remains 98.7788%, 868 bytes, 152-byte frame. No new source improvement retained in this pass. Baseline and final ordinary checkdiff agree.

Whole-function hashed donor search across indexed projects peaked at0.403; 32-instruction windows peaked at0.588. No structural twin found. Existing historical note #254 says retail IRO already confirmed the parenthesized chroma address grouping survives the frontend but is reassociated during initial PCode lowering.

New/checked source families and exact results (all reverted):

| Probe | Match % |
|---|---:|
| bitfields | 70.691246 |
| src-row-unsigned | 98.68664 |
| chroma-x-unsigned | 98.7788 |
| chroma-pointer | 97.32719 |
| chroma-offset-helper | 98.5576 |
| luma-base-before | 98.6636 |
| luma-base-after-zero | 98.6636 |
| luma-counter-int | 98.7788 |
| luma-index-unsigned | 98.7788 |
| offset-first | 91.258064 |
| dst-order | 98.7788 |

Bitfield union changed channel extraction and added8frame bytes. Explicit row pointer breaks the target single scalar-index address calculation. Inline row-offset helper adds8frame bytes without fixing addition grouping. Early reuse of chroma_index changes its CSE/lifetime substantially and regresses. Reversing dst_row operands is neutral. Moving invariant luma base out of the loop condition regresses; int/u32 pixel counter is neutral.

Residual: commuted row add at+0xb4, chroma scalar-index reassociation at+0xc4/+0xc8, downstream GPR cascade, and luma setup li/addi order at+0x1f0/+0x1f4. Next useful source lever should change lowering dependencies, not merely add parentheses. Dump is a baseline artifact; recapture after source changes before deriving allocation targets.

A final subtract-negative operand-order probe regressed96.65899% and was reverted.
