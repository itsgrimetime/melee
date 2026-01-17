/**
 * PowerPC ASM instruction parser for detailed diff analysis
 */

export interface ParsedInstruction {
    raw: string;
    hexBytes: string;
    mnemonic: string;
    operands: Operand[];
    isBranch: boolean;
    branchTarget?: string;
}

export interface Operand {
    type: 'register' | 'immediate' | 'memory' | 'label' | 'condition';
    value: string;
    raw: string;
}

export interface InstructionDiff {
    target: ParsedInstruction | null;
    current: ParsedInstruction | null;
    status: 'match' | 'mismatch' | 'target-only' | 'current-only';
    diffType?: 'r' | 'i' | 'o' | 's';  // r=register, i=immediate, o=opcode, s=stack
    mismatchedParts: Array<{
        partType: 'mnemonic' | 'operand';
        targetValue: string;
        currentValue: string;
        operandIndex?: number;
    }>;
}

// Branch instructions in PowerPC
const BRANCH_MNEMONICS = new Set([
    'b', 'bl', 'ba', 'bla',
    'bc', 'bcl', 'bca', 'bcla',
    'bclr', 'bclrl', 'bcctr', 'bcctrl',
    'beq', 'bne', 'blt', 'bgt', 'ble', 'bge',
    'beq+', 'bne+', 'blt+', 'bgt+', 'ble+', 'bge+',
    'beq-', 'bne-', 'blt-', 'bgt-', 'ble-', 'bge-',
    'beqlr', 'bnelr', 'bltlr', 'bgtlr', 'blelr', 'bgelr',
    'bdnz', 'bdz', 'bdnz+', 'bdz+', 'bdnz-', 'bdz-',
]);

/**
 * Parse a single ASM line into structured form
 */
export function parseInstruction(line: string): ParsedInstruction | null {
    // Skip function labels
    if (line.startsWith('<') || line.trim() === '') {
        return null;
    }

    // Skip relocation entries (e.g., "R_PPC_ADDR16_HA")
    const trimmed = line.trim();
    if (trimmed.startsWith('R_')) {
        return null;
    }

    // Format: "  hex_bytes \t mnemonic operands"
    const tabSplit = line.split('\t');
    if (tabSplit.length < 2) {
        return null;
    }

    const hexBytes = tabSplit[0].trim();

    // Also check if hexBytes looks like relocation (edge case)
    if (hexBytes.startsWith('R_')) {
        return null;
    }

    const asmPart = tabSplit.slice(1).join('\t').trim();

    // Split mnemonic from operands
    const spaceIdx = asmPart.search(/\s/);
    let mnemonic: string;
    let operandStr: string;

    if (spaceIdx === -1) {
        mnemonic = asmPart;
        operandStr = '';
    } else {
        mnemonic = asmPart.substring(0, spaceIdx);
        operandStr = asmPart.substring(spaceIdx).trim();
    }

    const operands = parseOperands(operandStr);
    const isBranch = BRANCH_MNEMONICS.has(mnemonic.toLowerCase());

    let branchTarget: string | undefined;
    if (isBranch && operands.length > 0) {
        // Last operand is usually the branch target
        const lastOp = operands[operands.length - 1];
        if (lastOp.type === 'label' || lastOp.type === 'immediate') {
            branchTarget = lastOp.value;
        }
    }

    return {
        raw: line,
        hexBytes,
        mnemonic,
        operands,
        isBranch,
        branchTarget
    };
}

/**
 * Parse operand string into structured operands
 */
function parseOperands(operandStr: string): Operand[] {
    if (!operandStr) return [];

    const operands: Operand[] = [];
    // Split by comma, but be careful with memory operands like "0(r1)"
    const parts = operandStr.split(',').map(s => s.trim());

    for (const part of parts) {
        if (!part) continue;

        // Check for memory operand: offset(register)
        const memMatch = part.match(/^(-?\d+)\((\w+)\)$/);
        if (memMatch) {
            operands.push({
                type: 'memory',
                value: part,
                raw: part
            });
            continue;
        }

        // Check for register: r0-r31, f0-f31, sp, lr, cr0-cr7
        if (/^(r\d{1,2}|f\d{1,2}|sp|lr|cr\d?)$/.test(part)) {
            operands.push({
                type: 'register',
                value: part,
                raw: part
            });
            continue;
        }

        // Check for label: <symbol> or <symbol+offset>
        if (part.startsWith('<') || part.includes('<')) {
            operands.push({
                type: 'label',
                value: part,
                raw: part
            });
            continue;
        }

        // Check for hex immediate: 0x... or plain hex
        if (/^-?0x[0-9a-fA-F]+$/.test(part) || /^-?\d+$/.test(part)) {
            operands.push({
                type: 'immediate',
                value: part,
                raw: part
            });
            continue;
        }

        // Condition register field or other
        operands.push({
            type: 'condition',
            value: part,
            raw: part
        });
    }

    return operands;
}

/**
 * Compare two instructions and identify specific differences
 */
export function compareInstructions(
    target: ParsedInstruction | null,
    current: ParsedInstruction | null
): InstructionDiff {
    if (!target && !current) {
        return { target: null, current: null, status: 'match', mismatchedParts: [] };
    }

    if (!target) {
        return { target: null, current, status: 'current-only', mismatchedParts: [] };
    }

    if (!current) {
        return { target, current: null, status: 'target-only', mismatchedParts: [] };
    }

    // Both exist - compare
    const mismatchedParts: InstructionDiff['mismatchedParts'] = [];

    // Compare mnemonics
    if (target.mnemonic !== current.mnemonic) {
        mismatchedParts.push({
            partType: 'mnemonic',
            targetValue: target.mnemonic,
            currentValue: current.mnemonic
        });
    }

    // Compare operands
    const maxOps = Math.max(target.operands.length, current.operands.length);
    for (let i = 0; i < maxOps; i++) {
        const tOp = target.operands[i];
        const cOp = current.operands[i];

        if (!tOp || !cOp) {
            mismatchedParts.push({
                partType: 'operand',
                targetValue: tOp?.raw || '',
                currentValue: cOp?.raw || '',
                operandIndex: i
            });
        } else if (tOp.value !== cOp.value) {
            mismatchedParts.push({
                partType: 'operand',
                targetValue: tOp.raw,
                currentValue: cOp.raw,
                operandIndex: i
            });
        }
    }

    if (mismatchedParts.length === 0) {
        return { target, current, status: 'match', mismatchedParts: [] };
    }

    // Determine diff type
    let diffType: InstructionDiff['diffType'] = 'o';  // default: opcode diff

    const hasRegisterDiff = mismatchedParts.some(p => {
        if (p.partType === 'operand') {
            const tOp = target.operands[p.operandIndex!];
            const cOp = current.operands[p.operandIndex!];
            return tOp?.type === 'register' || cOp?.type === 'register';
        }
        return false;
    });

    const hasImmediateDiff = mismatchedParts.some(p => {
        if (p.partType === 'operand') {
            const tOp = target.operands[p.operandIndex!];
            const cOp = current.operands[p.operandIndex!];
            return tOp?.type === 'immediate' || cOp?.type === 'immediate' ||
                   tOp?.type === 'memory' || cOp?.type === 'memory';
        }
        return false;
    });

    // Check for stack-related diff (stwu, lwz with r1/sp)
    const isStackOp = target.mnemonic.match(/^(stwu|stw|lwz|lbz|stb)$/) &&
        (target.operands.some(o => o.value === 'r1' || o.value === 'sp') ||
         current.operands.some(o => o.value === 'r1' || o.value === 'sp'));

    if (mismatchedParts.some(p => p.partType === 'mnemonic')) {
        diffType = 'o';  // opcode differs
    } else if (isStackOp) {
        diffType = 's';  // stack diff
    } else if (hasRegisterDiff) {
        diffType = 'r';  // register diff
    } else if (hasImmediateDiff) {
        diffType = 'i';  // immediate diff
    }

    return {
        target,
        current,
        status: 'mismatch',
        diffType,
        mismatchedParts
    };
}

/**
 * Branch arrow information
 */
export interface BranchArrow {
    fromOffset: number;      // Source byte offset
    toOffset: number;        // Destination byte offset
    fromRow: number;         // Source row index
    toRow: number;           // Destination row index
    direction: 'forward' | 'backward';
    type: 'conditional' | 'unconditional' | 'call';
}

/**
 * Parse branch target to extract byte offset
 * Format: <funcName+0xOFFSET> or just <funcName>
 */
function parseBranchTarget(target: string): number | null {
    // Match <name+0xOFFSET> or <name-0xOFFSET>
    const offsetMatch = target.match(/[+-](0x[0-9a-fA-F]+)/);
    if (offsetMatch) {
        const offset = parseInt(offsetMatch[1], 16);
        return target.includes('-') ? -offset : offset;
    }
    // If just <name> with no offset, it's offset 0
    if (target.match(/^<[^+>-]+>$/)) {
        return 0;
    }
    return null;
}

/**
 * Extract branch arrows from parsed instructions
 *
 * NOTE: The instructions array may include non-instruction lines (like relocations)
 * which parse to null. We need to track actual instruction byte offsets.
 */
export function extractBranchArrows(
    instructions: (ParsedInstruction | null)[],
    side: 'target' | 'current'
): BranchArrow[] {
    const arrows: BranchArrow[] = [];

    // Build a map of byte offset -> row index
    // Only count actual instructions, not relocation lines
    const offsetToRow: Map<number, number> = new Map();
    let currentOffset = 0;

    for (let i = 0; i < instructions.length; i++) {
        const instr = instructions[i];
        if (i === 0) {
            // Header row (function label)
            offsetToRow.set(-1, 0);  // Special marker for header
            continue;
        }
        if (instr) {
            // This is a real instruction
            offsetToRow.set(currentOffset, i);
            currentOffset += 4;
        }
        // If instr is null (relocation line), don't increment offset
    }

    // Track instruction index for calculating source offset
    let instrOffset = 0;

    for (let i = 0; i < instructions.length; i++) {
        const instr = instructions[i];
        if (i === 0) continue;  // Skip header

        if (!instr) continue;  // Skip non-instruction lines

        const fromOffset = instrOffset;
        instrOffset += 4;  // Move to next instruction

        if (!instr.isBranch || !instr.branchTarget) continue;

        // Skip function calls (bl/bla) - they typically call external functions
        if (instr.mnemonic === 'bl' || instr.mnemonic === 'bla' || instr.mnemonic === 'blrl') continue;

        // Skip link register returns
        if (instr.mnemonic.endsWith('lr') || instr.mnemonic === 'blr') continue;

        const toOffset = parseBranchTarget(instr.branchTarget);

        if (toOffset === null) continue;

        // Skip if target is outside reasonable range (likely external)
        if (toOffset < 0) continue;

        // Find the row that corresponds to the target offset
        const toRow = offsetToRow.get(toOffset);
        if (toRow === undefined) continue;  // Target not in visible range

        // Determine branch type
        let type: BranchArrow['type'] = 'conditional';
        if (instr.mnemonic === 'b' || instr.mnemonic === 'ba') {
            type = 'unconditional';
        }

        arrows.push({
            fromOffset,
            toOffset,
            fromRow: i,
            toRow,
            direction: toOffset > fromOffset ? 'forward' : 'backward',
            type
        });
    }

    return arrows;
}

/**
 * Build enhanced diff data from raw ASM lines
 */
export function buildEnhancedDiff(
    targetLines: string[],
    currentLines: string[]
): { diffs: InstructionDiff[], targetArrows: BranchArrow[], currentArrows: BranchArrow[] } {
    const diffs: InstructionDiff[] = [];
    const targetInstructions: (ParsedInstruction | null)[] = [];
    const currentInstructions: (ParsedInstruction | null)[] = [];

    const maxLen = Math.max(targetLines.length, currentLines.length);

    for (let i = 0; i < maxLen; i++) {
        const targetLine = targetLines[i] || '';
        const currentLine = currentLines[i] || '';

        const targetInstr = parseInstruction(targetLine);
        const currentInstr = parseInstruction(currentLine);

        targetInstructions.push(targetInstr);
        currentInstructions.push(currentInstr);

        // Skip function headers
        if (targetLine.startsWith('<') || currentLine.startsWith('<')) {
            diffs.push({
                target: targetInstr,
                current: currentInstr,
                status: 'match',
                mismatchedParts: []
            });
            continue;
        }

        diffs.push(compareInstructions(targetInstr, currentInstr));
    }

    // Extract branch arrows
    const targetArrows = extractBranchArrows(targetInstructions, 'target');
    const currentArrows = extractBranchArrows(currentInstructions, 'current');

    return { diffs, targetArrows, currentArrows };
}
