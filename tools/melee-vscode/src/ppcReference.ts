/**
 * PowerPC Instruction Reference for GameCube/Wii
 *
 * This provides quick documentation for PPC instructions shown in the ASM diff viewer.
 * Data sourced from IBM PowerPC 750CL User's Manual.
 */

export interface InstructionInfo {
    mnemonic: string;
    name: string;
    syntax: string;
    description: string;
    operation?: string;
    flags?: string;
    category: 'integer' | 'float' | 'load-store' | 'branch' | 'compare' | 'logical' | 'system' | 'paired-single';
}

export const ppcInstructions: Record<string, InstructionInfo> = {
    // ============ Integer Arithmetic ============
    'add': {
        mnemonic: 'add',
        name: 'Add',
        syntax: 'add rD, rA, rB',
        description: 'Adds rA and rB, stores result in rD.',
        operation: 'rD ← (rA) + (rB)',
        category: 'integer'
    },
    'addi': {
        mnemonic: 'addi',
        name: 'Add Immediate',
        syntax: 'addi rD, rA, SIMM',
        description: 'Adds signed 16-bit immediate to rA (or 0 if rA=r0), stores in rD. Often used for stack adjustments and address calculations.',
        operation: 'rD ← (rA|0) + EXTS(SIMM)',
        category: 'integer'
    },
    'addic': {
        mnemonic: 'addic',
        name: 'Add Immediate Carrying',
        syntax: 'addic rD, rA, SIMM',
        description: 'Adds signed immediate to rA, stores in rD, sets Carry flag.',
        operation: 'rD ← (rA) + EXTS(SIMM)',
        flags: 'CA',
        category: 'integer'
    },
    'addic.': {
        mnemonic: 'addic.',
        name: 'Add Immediate Carrying and Record',
        syntax: 'addic. rD, rA, SIMM',
        description: 'Adds signed immediate to rA, stores in rD, sets Carry and CR0.',
        operation: 'rD ← (rA) + EXTS(SIMM)',
        flags: 'CA, CR0',
        category: 'integer'
    },
    'addis': {
        mnemonic: 'addis',
        name: 'Add Immediate Shifted',
        syntax: 'addis rD, rA, SIMM',
        description: 'Adds SIMM << 16 to rA (or 0 if rA=r0). Used with addi/ori for loading 32-bit addresses.',
        operation: 'rD ← (rA|0) + (SIMM << 16)',
        category: 'integer'
    },
    'addze': {
        mnemonic: 'addze',
        name: 'Add to Zero Extended',
        syntax: 'addze rD, rA',
        description: 'Adds rA and CA (carry), stores in rD.',
        operation: 'rD ← (rA) + CA',
        flags: 'CA',
        category: 'integer'
    },
    'subf': {
        mnemonic: 'subf',
        name: 'Subtract From',
        syntax: 'subf rD, rA, rB',
        description: 'Subtracts rA from rB (note order!), stores in rD.',
        operation: 'rD ← (rB) - (rA)',
        category: 'integer'
    },
    'subfic': {
        mnemonic: 'subfic',
        name: 'Subtract From Immediate Carrying',
        syntax: 'subfic rD, rA, SIMM',
        description: 'Subtracts rA from sign-extended immediate.',
        operation: 'rD ← EXTS(SIMM) - (rA)',
        flags: 'CA',
        category: 'integer'
    },
    'neg': {
        mnemonic: 'neg',
        name: 'Negate',
        syntax: 'neg rD, rA',
        description: 'Negates rA (two\'s complement), stores in rD.',
        operation: 'rD ← ¬(rA) + 1',
        category: 'integer'
    },
    'mulli': {
        mnemonic: 'mulli',
        name: 'Multiply Low Immediate',
        syntax: 'mulli rD, rA, SIMM',
        description: 'Multiplies rA by signed immediate, stores low 32 bits in rD.',
        operation: 'rD ← (rA) × EXTS(SIMM)',
        category: 'integer'
    },
    'mullw': {
        mnemonic: 'mullw',
        name: 'Multiply Low Word',
        syntax: 'mullw rD, rA, rB',
        description: 'Multiplies rA by rB, stores low 32 bits in rD.',
        operation: 'rD ← (rA) × (rB)',
        category: 'integer'
    },
    'mulhw': {
        mnemonic: 'mulhw',
        name: 'Multiply High Word',
        syntax: 'mulhw rD, rA, rB',
        description: 'Multiplies rA by rB (signed), stores high 32 bits in rD.',
        operation: 'rD ← ((rA) × (rB)) >> 32',
        category: 'integer'
    },
    'mulhwu': {
        mnemonic: 'mulhwu',
        name: 'Multiply High Word Unsigned',
        syntax: 'mulhwu rD, rA, rB',
        description: 'Multiplies rA by rB (unsigned), stores high 32 bits in rD.',
        operation: 'rD ← ((rA) × (rB)) >> 32 (unsigned)',
        category: 'integer'
    },
    'divw': {
        mnemonic: 'divw',
        name: 'Divide Word',
        syntax: 'divw rD, rA, rB',
        description: 'Divides rA by rB (signed), stores quotient in rD.',
        operation: 'rD ← (rA) ÷ (rB)',
        category: 'integer'
    },
    'divwu': {
        mnemonic: 'divwu',
        name: 'Divide Word Unsigned',
        syntax: 'divwu rD, rA, rB',
        description: 'Divides rA by rB (unsigned), stores quotient in rD.',
        operation: 'rD ← (rA) ÷ (rB) (unsigned)',
        category: 'integer'
    },

    // ============ Logical Operations ============
    'and': {
        mnemonic: 'and',
        name: 'AND',
        syntax: 'and rA, rS, rB',
        description: 'Bitwise AND of rS and rB, stores in rA.',
        operation: 'rA ← (rS) & (rB)',
        category: 'logical'
    },
    'andi.': {
        mnemonic: 'andi.',
        name: 'AND Immediate',
        syntax: 'andi. rA, rS, UIMM',
        description: 'Bitwise AND of rS and zero-extended immediate, sets CR0.',
        operation: 'rA ← (rS) & UIMM',
        flags: 'CR0',
        category: 'logical'
    },
    'andis.': {
        mnemonic: 'andis.',
        name: 'AND Immediate Shifted',
        syntax: 'andis. rA, rS, UIMM',
        description: 'Bitwise AND of rS and (UIMM << 16), sets CR0.',
        operation: 'rA ← (rS) & (UIMM << 16)',
        flags: 'CR0',
        category: 'logical'
    },
    'andc': {
        mnemonic: 'andc',
        name: 'AND with Complement',
        syntax: 'andc rA, rS, rB',
        description: 'Bitwise AND of rS and complement of rB.',
        operation: 'rA ← (rS) & ¬(rB)',
        category: 'logical'
    },
    'or': {
        mnemonic: 'or',
        name: 'OR',
        syntax: 'or rA, rS, rB',
        description: 'Bitwise OR of rS and rB. When rS=rB, this is "mr" (move register).',
        operation: 'rA ← (rS) | (rB)',
        category: 'logical'
    },
    'ori': {
        mnemonic: 'ori',
        name: 'OR Immediate',
        syntax: 'ori rA, rS, UIMM',
        description: 'Bitwise OR of rS and zero-extended immediate. Used with lis for loading 32-bit values.',
        operation: 'rA ← (rS) | UIMM',
        category: 'logical'
    },
    'oris': {
        mnemonic: 'oris',
        name: 'OR Immediate Shifted',
        syntax: 'oris rA, rS, UIMM',
        description: 'Bitwise OR of rS and (UIMM << 16).',
        operation: 'rA ← (rS) | (UIMM << 16)',
        category: 'logical'
    },
    'xor': {
        mnemonic: 'xor',
        name: 'XOR',
        syntax: 'xor rA, rS, rB',
        description: 'Bitwise exclusive OR of rS and rB.',
        operation: 'rA ← (rS) ^ (rB)',
        category: 'logical'
    },
    'xori': {
        mnemonic: 'xori',
        name: 'XOR Immediate',
        syntax: 'xori rA, rS, UIMM',
        description: 'Bitwise XOR of rS and zero-extended immediate.',
        operation: 'rA ← (rS) ^ UIMM',
        category: 'logical'
    },
    'nand': {
        mnemonic: 'nand',
        name: 'NAND',
        syntax: 'nand rA, rS, rB',
        description: 'Bitwise NAND of rS and rB.',
        operation: 'rA ← ¬((rS) & (rB))',
        category: 'logical'
    },
    'nor': {
        mnemonic: 'nor',
        name: 'NOR',
        syntax: 'nor rA, rS, rB',
        description: 'Bitwise NOR of rS and rB. When rS=rB, this is "not" (complement).',
        operation: 'rA ← ¬((rS) | (rB))',
        category: 'logical'
    },
    'eqv': {
        mnemonic: 'eqv',
        name: 'Equivalent',
        syntax: 'eqv rA, rS, rB',
        description: 'Bitwise equivalence (XNOR) of rS and rB.',
        operation: 'rA ← ¬((rS) ^ (rB))',
        category: 'logical'
    },
    'extsb': {
        mnemonic: 'extsb',
        name: 'Extend Sign Byte',
        syntax: 'extsb rA, rS',
        description: 'Sign-extends the low byte of rS to 32 bits.',
        operation: 'rA ← EXTS(rS[24:31])',
        category: 'logical'
    },
    'extsh': {
        mnemonic: 'extsh',
        name: 'Extend Sign Half Word',
        syntax: 'extsh rA, rS',
        description: 'Sign-extends the low halfword of rS to 32 bits.',
        operation: 'rA ← EXTS(rS[16:31])',
        category: 'logical'
    },
    'cntlzw': {
        mnemonic: 'cntlzw',
        name: 'Count Leading Zeros Word',
        syntax: 'cntlzw rA, rS',
        description: 'Counts the number of leading zero bits in rS.',
        operation: 'rA ← count_leading_zeros(rS)',
        category: 'logical'
    },

    // ============ Shift and Rotate ============
    'slw': {
        mnemonic: 'slw',
        name: 'Shift Left Word',
        syntax: 'slw rA, rS, rB',
        description: 'Shifts rS left by rB[27:31] bits, zeros fill from right.',
        operation: 'rA ← (rS) << rB[27:31]',
        category: 'logical'
    },
    'slwi': {
        mnemonic: 'slwi',
        name: 'Shift Left Word Immediate',
        syntax: 'slwi rA, rS, n',
        description: 'Shifts rS left by n bits. Simplified mnemonic for rlwinm.',
        operation: 'rA ← (rS) << n',
        category: 'logical'
    },
    'srw': {
        mnemonic: 'srw',
        name: 'Shift Right Word',
        syntax: 'srw rA, rS, rB',
        description: 'Shifts rS right by rB[27:31] bits, zeros fill from left.',
        operation: 'rA ← (rS) >> rB[27:31]',
        category: 'logical'
    },
    'srwi': {
        mnemonic: 'srwi',
        name: 'Shift Right Word Immediate',
        syntax: 'srwi rA, rS, n',
        description: 'Shifts rS right by n bits. Simplified mnemonic for rlwinm.',
        operation: 'rA ← (rS) >> n',
        category: 'logical'
    },
    'sraw': {
        mnemonic: 'sraw',
        name: 'Shift Right Algebraic Word',
        syntax: 'sraw rA, rS, rB',
        description: 'Arithmetic shift right, sign bit fills from left.',
        operation: 'rA ← (rS) >>a rB[27:31]',
        flags: 'CA',
        category: 'logical'
    },
    'srawi': {
        mnemonic: 'srawi',
        name: 'Shift Right Algebraic Word Immediate',
        syntax: 'srawi rA, rS, n',
        description: 'Arithmetic shift right by n bits. Used for signed division by powers of 2.',
        operation: 'rA ← (rS) >>a n',
        flags: 'CA',
        category: 'logical'
    },
    'rlwinm': {
        mnemonic: 'rlwinm',
        name: 'Rotate Left Word Immediate then AND with Mask',
        syntax: 'rlwinm rA, rS, SH, MB, ME',
        description: 'Rotates rS left by SH bits, then ANDs with mask from bit MB to ME. Very versatile for bit manipulation.',
        operation: 'rA ← ROTL(rS, SH) & MASK(MB, ME)',
        category: 'logical'
    },
    'rlwimi': {
        mnemonic: 'rlwimi',
        name: 'Rotate Left Word Immediate then Mask Insert',
        syntax: 'rlwimi rA, rS, SH, MB, ME',
        description: 'Rotates rS left, inserts into rA using mask. Used for bit field insertion.',
        operation: 'rA ← (ROTL(rS, SH) & MASK) | (rA & ¬MASK)',
        category: 'logical'
    },
    'rlwnm': {
        mnemonic: 'rlwnm',
        name: 'Rotate Left Word then AND with Mask',
        syntax: 'rlwnm rA, rS, rB, MB, ME',
        description: 'Rotates rS left by rB[27:31] bits, ANDs with mask.',
        operation: 'rA ← ROTL(rS, rB) & MASK(MB, ME)',
        category: 'logical'
    },
    'clrlwi': {
        mnemonic: 'clrlwi',
        name: 'Clear Left Word Immediate',
        syntax: 'clrlwi rA, rS, n',
        description: 'Clears the high n bits of rS. Simplified mnemonic for rlwinm.',
        operation: 'rA ← rS & ((1 << (32-n)) - 1)',
        category: 'logical'
    },
    'clrrwi': {
        mnemonic: 'clrrwi',
        name: 'Clear Right Word Immediate',
        syntax: 'clrrwi rA, rS, n',
        description: 'Clears the low n bits of rS. Simplified mnemonic for rlwinm.',
        operation: 'rA ← rS & ~((1 << n) - 1)',
        category: 'logical'
    },

    // ============ Load Instructions ============
    'lbz': {
        mnemonic: 'lbz',
        name: 'Load Byte and Zero',
        syntax: 'lbz rD, d(rA)',
        description: 'Loads a byte from memory, zero-extends to 32 bits.',
        operation: 'rD ← MEM(rA + d, 1)',
        category: 'load-store'
    },
    'lbzu': {
        mnemonic: 'lbzu',
        name: 'Load Byte and Zero with Update',
        syntax: 'lbzu rD, d(rA)',
        description: 'Loads byte, updates rA with effective address.',
        operation: 'EA ← rA + d; rD ← MEM(EA, 1); rA ← EA',
        category: 'load-store'
    },
    'lbzx': {
        mnemonic: 'lbzx',
        name: 'Load Byte and Zero Indexed',
        syntax: 'lbzx rD, rA, rB',
        description: 'Loads byte from rA + rB address.',
        operation: 'rD ← MEM(rA + rB, 1)',
        category: 'load-store'
    },
    'lhz': {
        mnemonic: 'lhz',
        name: 'Load Half Word and Zero',
        syntax: 'lhz rD, d(rA)',
        description: 'Loads 16-bit halfword, zero-extends to 32 bits.',
        operation: 'rD ← MEM(rA + d, 2)',
        category: 'load-store'
    },
    'lhzu': {
        mnemonic: 'lhzu',
        name: 'Load Half Word and Zero with Update',
        syntax: 'lhzu rD, d(rA)',
        description: 'Loads halfword, updates rA with effective address.',
        operation: 'EA ← rA + d; rD ← MEM(EA, 2); rA ← EA',
        category: 'load-store'
    },
    'lha': {
        mnemonic: 'lha',
        name: 'Load Half Word Algebraic',
        syntax: 'lha rD, d(rA)',
        description: 'Loads 16-bit halfword, sign-extends to 32 bits.',
        operation: 'rD ← EXTS(MEM(rA + d, 2))',
        category: 'load-store'
    },
    'lhax': {
        mnemonic: 'lhax',
        name: 'Load Half Word Algebraic Indexed',
        syntax: 'lhax rD, rA, rB',
        description: 'Loads halfword from rA + rB, sign-extends.',
        operation: 'rD ← EXTS(MEM(rA + rB, 2))',
        category: 'load-store'
    },
    'lwz': {
        mnemonic: 'lwz',
        name: 'Load Word and Zero',
        syntax: 'lwz rD, d(rA)',
        description: 'Loads 32-bit word from memory. Most common load instruction.',
        operation: 'rD ← MEM(rA + d, 4)',
        category: 'load-store'
    },
    'lwzu': {
        mnemonic: 'lwzu',
        name: 'Load Word and Zero with Update',
        syntax: 'lwzu rD, d(rA)',
        description: 'Loads word, updates rA with effective address.',
        operation: 'EA ← rA + d; rD ← MEM(EA, 4); rA ← EA',
        category: 'load-store'
    },
    'lwzx': {
        mnemonic: 'lwzx',
        name: 'Load Word and Zero Indexed',
        syntax: 'lwzx rD, rA, rB',
        description: 'Loads word from rA + rB address.',
        operation: 'rD ← MEM(rA + rB, 4)',
        category: 'load-store'
    },
    'lmw': {
        mnemonic: 'lmw',
        name: 'Load Multiple Word',
        syntax: 'lmw rD, d(rA)',
        description: 'Loads multiple words into rD through r31. Used in function prologues.',
        operation: 'for i = D to 31: r[i] ← MEM(EA + (i-D)*4, 4)',
        category: 'load-store'
    },

    // ============ Store Instructions ============
    'stb': {
        mnemonic: 'stb',
        name: 'Store Byte',
        syntax: 'stb rS, d(rA)',
        description: 'Stores low byte of rS to memory.',
        operation: 'MEM(rA + d, 1) ← rS[24:31]',
        category: 'load-store'
    },
    'stbu': {
        mnemonic: 'stbu',
        name: 'Store Byte with Update',
        syntax: 'stbu rS, d(rA)',
        description: 'Stores byte, updates rA with effective address.',
        operation: 'EA ← rA + d; MEM(EA, 1) ← rS[24:31]; rA ← EA',
        category: 'load-store'
    },
    'stbx': {
        mnemonic: 'stbx',
        name: 'Store Byte Indexed',
        syntax: 'stbx rS, rA, rB',
        description: 'Stores byte to rA + rB address.',
        operation: 'MEM(rA + rB, 1) ← rS[24:31]',
        category: 'load-store'
    },
    'sth': {
        mnemonic: 'sth',
        name: 'Store Half Word',
        syntax: 'sth rS, d(rA)',
        description: 'Stores low halfword of rS to memory.',
        operation: 'MEM(rA + d, 2) ← rS[16:31]',
        category: 'load-store'
    },
    'sthu': {
        mnemonic: 'sthu',
        name: 'Store Half Word with Update',
        syntax: 'sthu rS, d(rA)',
        description: 'Stores halfword, updates rA with effective address.',
        operation: 'EA ← rA + d; MEM(EA, 2) ← rS[16:31]; rA ← EA',
        category: 'load-store'
    },
    'stw': {
        mnemonic: 'stw',
        name: 'Store Word',
        syntax: 'stw rS, d(rA)',
        description: 'Stores 32-bit word to memory. Most common store instruction.',
        operation: 'MEM(rA + d, 4) ← rS',
        category: 'load-store'
    },
    'stwu': {
        mnemonic: 'stwu',
        name: 'Store Word with Update',
        syntax: 'stwu rS, d(rA)',
        description: 'Stores word, updates rA. Often used for stack frame setup: stwu r1, -N(r1).',
        operation: 'EA ← rA + d; MEM(EA, 4) ← rS; rA ← EA',
        category: 'load-store'
    },
    'stwx': {
        mnemonic: 'stwx',
        name: 'Store Word Indexed',
        syntax: 'stwx rS, rA, rB',
        description: 'Stores word to rA + rB address.',
        operation: 'MEM(rA + rB, 4) ← rS',
        category: 'load-store'
    },
    'stmw': {
        mnemonic: 'stmw',
        name: 'Store Multiple Word',
        syntax: 'stmw rS, d(rA)',
        description: 'Stores rS through r31 to consecutive memory. Used in function prologues.',
        operation: 'for i = S to 31: MEM(EA + (i-S)*4, 4) ← r[i]',
        category: 'load-store'
    },

    // ============ Compare Instructions ============
    'cmpw': {
        mnemonic: 'cmpw',
        name: 'Compare Word',
        syntax: 'cmpw [crD,] rA, rB',
        description: 'Compares rA and rB as signed integers, sets CR field.',
        operation: 'CR[crD] ← compare_signed(rA, rB)',
        flags: 'CR',
        category: 'compare'
    },
    'cmpwi': {
        mnemonic: 'cmpwi',
        name: 'Compare Word Immediate',
        syntax: 'cmpwi [crD,] rA, SIMM',
        description: 'Compares rA with signed immediate.',
        operation: 'CR[crD] ← compare_signed(rA, EXTS(SIMM))',
        flags: 'CR',
        category: 'compare'
    },
    'cmplw': {
        mnemonic: 'cmplw',
        name: 'Compare Logical Word',
        syntax: 'cmplw [crD,] rA, rB',
        description: 'Compares rA and rB as unsigned integers.',
        operation: 'CR[crD] ← compare_unsigned(rA, rB)',
        flags: 'CR',
        category: 'compare'
    },
    'cmplwi': {
        mnemonic: 'cmplwi',
        name: 'Compare Logical Word Immediate',
        syntax: 'cmplwi [crD,] rA, UIMM',
        description: 'Compares rA with unsigned immediate.',
        operation: 'CR[crD] ← compare_unsigned(rA, UIMM)',
        flags: 'CR',
        category: 'compare'
    },

    // ============ Branch Instructions ============
    'b': {
        mnemonic: 'b',
        name: 'Branch',
        syntax: 'b target',
        description: 'Unconditional branch to target address.',
        operation: 'PC ← target',
        category: 'branch'
    },
    'bl': {
        mnemonic: 'bl',
        name: 'Branch and Link',
        syntax: 'bl target',
        description: 'Branch to target, save return address in LR. Used for function calls.',
        operation: 'LR ← PC + 4; PC ← target',
        category: 'branch'
    },
    'blr': {
        mnemonic: 'blr',
        name: 'Branch to Link Register',
        syntax: 'blr',
        description: 'Returns from function by branching to address in LR.',
        operation: 'PC ← LR',
        category: 'branch'
    },
    'blrl': {
        mnemonic: 'blrl',
        name: 'Branch to Link Register and Link',
        syntax: 'blrl',
        description: 'Branch to LR, save return address. Used for indirect function calls.',
        operation: 'temp ← LR; LR ← PC + 4; PC ← temp',
        category: 'branch'
    },
    'bctr': {
        mnemonic: 'bctr',
        name: 'Branch to Count Register',
        syntax: 'bctr',
        description: 'Branch to address in CTR. Used for switch statements and indirect jumps.',
        operation: 'PC ← CTR',
        category: 'branch'
    },
    'bctrl': {
        mnemonic: 'bctrl',
        name: 'Branch to Count Register and Link',
        syntax: 'bctrl',
        description: 'Branch to CTR, save return address. Indirect function call.',
        operation: 'LR ← PC + 4; PC ← CTR',
        category: 'branch'
    },
    'beq': {
        mnemonic: 'beq',
        name: 'Branch if Equal',
        syntax: 'beq [crS,] target',
        description: 'Branch if CR[crS].EQ is set (comparison was equal).',
        operation: 'if CR[crS].EQ then PC ← target',
        category: 'branch'
    },
    'bne': {
        mnemonic: 'bne',
        name: 'Branch if Not Equal',
        syntax: 'bne [crS,] target',
        description: 'Branch if CR[crS].EQ is clear (comparison was not equal).',
        operation: 'if ¬CR[crS].EQ then PC ← target',
        category: 'branch'
    },
    'blt': {
        mnemonic: 'blt',
        name: 'Branch if Less Than',
        syntax: 'blt [crS,] target',
        description: 'Branch if CR[crS].LT is set (comparison was less than).',
        operation: 'if CR[crS].LT then PC ← target',
        category: 'branch'
    },
    'bgt': {
        mnemonic: 'bgt',
        name: 'Branch if Greater Than',
        syntax: 'bgt [crS,] target',
        description: 'Branch if CR[crS].GT is set (comparison was greater than).',
        operation: 'if CR[crS].GT then PC ← target',
        category: 'branch'
    },
    'ble': {
        mnemonic: 'ble',
        name: 'Branch if Less Than or Equal',
        syntax: 'ble [crS,] target',
        description: 'Branch if not greater than.',
        operation: 'if ¬CR[crS].GT then PC ← target',
        category: 'branch'
    },
    'bge': {
        mnemonic: 'bge',
        name: 'Branch if Greater Than or Equal',
        syntax: 'bge [crS,] target',
        description: 'Branch if not less than.',
        operation: 'if ¬CR[crS].LT then PC ← target',
        category: 'branch'
    },
    'bdnz': {
        mnemonic: 'bdnz',
        name: 'Branch Decrement Not Zero',
        syntax: 'bdnz target',
        description: 'Decrements CTR, branches if CTR ≠ 0. Used for loops.',
        operation: 'CTR ← CTR - 1; if CTR ≠ 0 then PC ← target',
        category: 'branch'
    },
    'bdz': {
        mnemonic: 'bdz',
        name: 'Branch Decrement Zero',
        syntax: 'bdz target',
        description: 'Decrements CTR, branches if CTR = 0.',
        operation: 'CTR ← CTR - 1; if CTR = 0 then PC ← target',
        category: 'branch'
    },
    'beqlr': {
        mnemonic: 'beqlr',
        name: 'Branch to LR if Equal',
        syntax: 'beqlr [crS]',
        description: 'Return if equal.',
        operation: 'if CR[crS].EQ then PC ← LR',
        category: 'branch'
    },
    'bnelr': {
        mnemonic: 'bnelr',
        name: 'Branch to LR if Not Equal',
        syntax: 'bnelr [crS]',
        description: 'Return if not equal.',
        operation: 'if ¬CR[crS].EQ then PC ← LR',
        category: 'branch'
    },
    'bltlr': {
        mnemonic: 'bltlr',
        name: 'Branch to LR if Less Than',
        syntax: 'bltlr [crS]',
        description: 'Return if less than.',
        operation: 'if CR[crS].LT then PC ← LR',
        category: 'branch'
    },
    'bgtlr': {
        mnemonic: 'bgtlr',
        name: 'Branch to LR if Greater Than',
        syntax: 'bgtlr [crS]',
        description: 'Return if greater than.',
        operation: 'if CR[crS].GT then PC ← LR',
        category: 'branch'
    },
    'blelr': {
        mnemonic: 'blelr',
        name: 'Branch to LR if Less or Equal',
        syntax: 'blelr [crS]',
        description: 'Return if less or equal.',
        operation: 'if ¬CR[crS].GT then PC ← LR',
        category: 'branch'
    },
    'bgelr': {
        mnemonic: 'bgelr',
        name: 'Branch to LR if Greater or Equal',
        syntax: 'bgelr [crS]',
        description: 'Return if greater or equal.',
        operation: 'if ¬CR[crS].LT then PC ← LR',
        category: 'branch'
    },

    // ============ Floating Point Load/Store ============
    'lfs': {
        mnemonic: 'lfs',
        name: 'Load Floating-Point Single',
        syntax: 'lfs frD, d(rA)',
        description: 'Loads 32-bit float from memory, converts to double precision in frD.',
        operation: 'frD ← double(MEM(rA + d, 4))',
        category: 'float'
    },
    'lfsu': {
        mnemonic: 'lfsu',
        name: 'Load Floating-Point Single with Update',
        syntax: 'lfsu frD, d(rA)',
        description: 'Loads float, updates rA.',
        operation: 'EA ← rA + d; frD ← double(MEM(EA, 4)); rA ← EA',
        category: 'float'
    },
    'lfsx': {
        mnemonic: 'lfsx',
        name: 'Load Floating-Point Single Indexed',
        syntax: 'lfsx frD, rA, rB',
        description: 'Loads float from rA + rB address.',
        operation: 'frD ← double(MEM(rA + rB, 4))',
        category: 'float'
    },
    'lfd': {
        mnemonic: 'lfd',
        name: 'Load Floating-Point Double',
        syntax: 'lfd frD, d(rA)',
        description: 'Loads 64-bit double from memory.',
        operation: 'frD ← MEM(rA + d, 8)',
        category: 'float'
    },
    'lfdu': {
        mnemonic: 'lfdu',
        name: 'Load Floating-Point Double with Update',
        syntax: 'lfdu frD, d(rA)',
        description: 'Loads double, updates rA.',
        operation: 'EA ← rA + d; frD ← MEM(EA, 8); rA ← EA',
        category: 'float'
    },
    'stfs': {
        mnemonic: 'stfs',
        name: 'Store Floating-Point Single',
        syntax: 'stfs frS, d(rA)',
        description: 'Converts frS to single precision, stores to memory.',
        operation: 'MEM(rA + d, 4) ← single(frS)',
        category: 'float'
    },
    'stfsu': {
        mnemonic: 'stfsu',
        name: 'Store Floating-Point Single with Update',
        syntax: 'stfsu frS, d(rA)',
        description: 'Stores float, updates rA.',
        operation: 'EA ← rA + d; MEM(EA, 4) ← single(frS); rA ← EA',
        category: 'float'
    },
    'stfd': {
        mnemonic: 'stfd',
        name: 'Store Floating-Point Double',
        syntax: 'stfd frS, d(rA)',
        description: 'Stores 64-bit double to memory.',
        operation: 'MEM(rA + d, 8) ← frS',
        category: 'float'
    },
    'stfdu': {
        mnemonic: 'stfdu',
        name: 'Store Floating-Point Double with Update',
        syntax: 'stfdu frS, d(rA)',
        description: 'Stores double, updates rA.',
        operation: 'EA ← rA + d; MEM(EA, 8) ← frS; rA ← EA',
        category: 'float'
    },

    // ============ Floating Point Arithmetic ============
    'fadd': {
        mnemonic: 'fadd',
        name: 'Floating Add',
        syntax: 'fadd frD, frA, frB',
        description: 'Adds frA and frB (double precision).',
        operation: 'frD ← frA + frB',
        category: 'float'
    },
    'fadds': {
        mnemonic: 'fadds',
        name: 'Floating Add Single',
        syntax: 'fadds frD, frA, frB',
        description: 'Adds frA and frB (single precision).',
        operation: 'frD ← single(frA + frB)',
        category: 'float'
    },
    'fsub': {
        mnemonic: 'fsub',
        name: 'Floating Subtract',
        syntax: 'fsub frD, frA, frB',
        description: 'Subtracts frB from frA (double precision).',
        operation: 'frD ← frA - frB',
        category: 'float'
    },
    'fsubs': {
        mnemonic: 'fsubs',
        name: 'Floating Subtract Single',
        syntax: 'fsubs frD, frA, frB',
        description: 'Subtracts frB from frA (single precision).',
        operation: 'frD ← single(frA - frB)',
        category: 'float'
    },
    'fmul': {
        mnemonic: 'fmul',
        name: 'Floating Multiply',
        syntax: 'fmul frD, frA, frC',
        description: 'Multiplies frA and frC (double precision). Note: uses frC, not frB!',
        operation: 'frD ← frA × frC',
        category: 'float'
    },
    'fmuls': {
        mnemonic: 'fmuls',
        name: 'Floating Multiply Single',
        syntax: 'fmuls frD, frA, frC',
        description: 'Multiplies frA and frC (single precision).',
        operation: 'frD ← single(frA × frC)',
        category: 'float'
    },
    'fdiv': {
        mnemonic: 'fdiv',
        name: 'Floating Divide',
        syntax: 'fdiv frD, frA, frB',
        description: 'Divides frA by frB (double precision).',
        operation: 'frD ← frA ÷ frB',
        category: 'float'
    },
    'fdivs': {
        mnemonic: 'fdivs',
        name: 'Floating Divide Single',
        syntax: 'fdivs frD, frA, frB',
        description: 'Divides frA by frB (single precision).',
        operation: 'frD ← single(frA ÷ frB)',
        category: 'float'
    },
    'fmadd': {
        mnemonic: 'fmadd',
        name: 'Floating Multiply-Add',
        syntax: 'fmadd frD, frA, frC, frB',
        description: 'Fused multiply-add: (frA × frC) + frB with one rounding.',
        operation: 'frD ← (frA × frC) + frB',
        category: 'float'
    },
    'fmadds': {
        mnemonic: 'fmadds',
        name: 'Floating Multiply-Add Single',
        syntax: 'fmadds frD, frA, frC, frB',
        description: 'Fused multiply-add (single precision).',
        operation: 'frD ← single((frA × frC) + frB)',
        category: 'float'
    },
    'fmsub': {
        mnemonic: 'fmsub',
        name: 'Floating Multiply-Subtract',
        syntax: 'fmsub frD, frA, frC, frB',
        description: 'Fused multiply-subtract: (frA × frC) - frB.',
        operation: 'frD ← (frA × frC) - frB',
        category: 'float'
    },
    'fmsubs': {
        mnemonic: 'fmsubs',
        name: 'Floating Multiply-Subtract Single',
        syntax: 'fmsubs frD, frA, frC, frB',
        description: 'Fused multiply-subtract (single precision).',
        operation: 'frD ← single((frA × frC) - frB)',
        category: 'float'
    },
    'fnmadd': {
        mnemonic: 'fnmadd',
        name: 'Floating Negative Multiply-Add',
        syntax: 'fnmadd frD, frA, frC, frB',
        description: 'Negated fused multiply-add: -((frA × frC) + frB).',
        operation: 'frD ← -((frA × frC) + frB)',
        category: 'float'
    },
    'fnmadds': {
        mnemonic: 'fnmadds',
        name: 'Floating Negative Multiply-Add Single',
        syntax: 'fnmadds frD, frA, frC, frB',
        description: 'Negated fused multiply-add (single precision).',
        operation: 'frD ← single(-((frA × frC) + frB))',
        category: 'float'
    },
    'fnmsub': {
        mnemonic: 'fnmsub',
        name: 'Floating Negative Multiply-Subtract',
        syntax: 'fnmsub frD, frA, frC, frB',
        description: 'Negated fused multiply-subtract: -((frA × frC) - frB).',
        operation: 'frD ← -((frA × frC) - frB)',
        category: 'float'
    },
    'fnmsubs': {
        mnemonic: 'fnmsubs',
        name: 'Floating Negative Multiply-Subtract Single',
        syntax: 'fnmsubs frD, frA, frC, frB',
        description: 'Negated fused multiply-subtract (single precision).',
        operation: 'frD ← single(-((frA × frC) - frB))',
        category: 'float'
    },
    'fneg': {
        mnemonic: 'fneg',
        name: 'Floating Negate',
        syntax: 'fneg frD, frB',
        description: 'Negates frB.',
        operation: 'frD ← -frB',
        category: 'float'
    },
    'fabs': {
        mnemonic: 'fabs',
        name: 'Floating Absolute Value',
        syntax: 'fabs frD, frB',
        description: 'Absolute value of frB.',
        operation: 'frD ← |frB|',
        category: 'float'
    },
    'fnabs': {
        mnemonic: 'fnabs',
        name: 'Floating Negative Absolute Value',
        syntax: 'fnabs frD, frB',
        description: 'Negative absolute value of frB.',
        operation: 'frD ← -|frB|',
        category: 'float'
    },
    'fmr': {
        mnemonic: 'fmr',
        name: 'Floating Move Register',
        syntax: 'fmr frD, frB',
        description: 'Copies frB to frD.',
        operation: 'frD ← frB',
        category: 'float'
    },
    'fres': {
        mnemonic: 'fres',
        name: 'Floating Reciprocal Estimate Single',
        syntax: 'fres frD, frB',
        description: 'Estimates 1/frB (single precision). Fast but approximate.',
        operation: 'frD ≈ 1/frB',
        category: 'float'
    },
    'frsqrte': {
        mnemonic: 'frsqrte',
        name: 'Floating Reciprocal Square Root Estimate',
        syntax: 'frsqrte frD, frB',
        description: 'Estimates 1/√frB. Used for fast inverse square root.',
        operation: 'frD ≈ 1/√frB',
        category: 'float'
    },
    'fsel': {
        mnemonic: 'fsel',
        name: 'Floating Select',
        syntax: 'fsel frD, frA, frC, frB',
        description: 'If frA >= 0, select frC, else select frB. Branchless conditional.',
        operation: 'frD ← (frA >= 0) ? frC : frB',
        category: 'float'
    },
    'frsp': {
        mnemonic: 'frsp',
        name: 'Floating Round to Single Precision',
        syntax: 'frsp frD, frB',
        description: 'Rounds frB to single precision.',
        operation: 'frD ← single(frB)',
        category: 'float'
    },
    'fctiw': {
        mnemonic: 'fctiw',
        name: 'Floating Convert to Integer Word',
        syntax: 'fctiw frD, frB',
        description: 'Converts float to 32-bit signed integer (using current rounding mode).',
        operation: 'frD ← (s32)frB',
        category: 'float'
    },
    'fctiwz': {
        mnemonic: 'fctiwz',
        name: 'Floating Convert to Integer Word with Round toward Zero',
        syntax: 'fctiwz frD, frB',
        description: 'Converts float to 32-bit signed integer (truncates toward zero).',
        operation: 'frD ← trunc(frB)',
        category: 'float'
    },

    // ============ Floating Point Compare ============
    'fcmpu': {
        mnemonic: 'fcmpu',
        name: 'Floating Compare Unordered',
        syntax: 'fcmpu crD, frA, frB',
        description: 'Compares frA and frB, sets CR field. Does not trap on NaN.',
        operation: 'CR[crD] ← compare(frA, frB)',
        flags: 'CR',
        category: 'compare'
    },
    'fcmpo': {
        mnemonic: 'fcmpo',
        name: 'Floating Compare Ordered',
        syntax: 'fcmpo crD, frA, frB',
        description: 'Compares frA and frB, sets CR field. May trap on NaN.',
        operation: 'CR[crD] ← compare(frA, frB)',
        flags: 'CR, FPSCR',
        category: 'compare'
    },

    // ============ System/Special Registers ============
    'mflr': {
        mnemonic: 'mflr',
        name: 'Move From Link Register',
        syntax: 'mflr rD',
        description: 'Copies LR (return address) to rD. Used to save return address.',
        operation: 'rD ← LR',
        category: 'system'
    },
    'mtlr': {
        mnemonic: 'mtlr',
        name: 'Move To Link Register',
        syntax: 'mtlr rS',
        description: 'Copies rS to LR. Used to restore return address before blr.',
        operation: 'LR ← rS',
        category: 'system'
    },
    'mfctr': {
        mnemonic: 'mfctr',
        name: 'Move From Count Register',
        syntax: 'mfctr rD',
        description: 'Copies CTR to rD.',
        operation: 'rD ← CTR',
        category: 'system'
    },
    'mtctr': {
        mnemonic: 'mtctr',
        name: 'Move To Count Register',
        syntax: 'mtctr rS',
        description: 'Copies rS to CTR. Used for loop counts or indirect branches.',
        operation: 'CTR ← rS',
        category: 'system'
    },
    'mfcr': {
        mnemonic: 'mfcr',
        name: 'Move From Condition Register',
        syntax: 'mfcr rD',
        description: 'Copies entire CR to rD.',
        operation: 'rD ← CR',
        category: 'system'
    },
    'mtcrf': {
        mnemonic: 'mtcrf',
        name: 'Move To Condition Register Fields',
        syntax: 'mtcrf CRM, rS',
        description: 'Copies selected fields from rS to CR based on mask.',
        operation: 'CR[selected] ← rS[selected]',
        category: 'system'
    },
    'mffs': {
        mnemonic: 'mffs',
        name: 'Move From FPSCR',
        syntax: 'mffs frD',
        description: 'Copies FPSCR to frD.',
        operation: 'frD ← FPSCR',
        category: 'system'
    },
    'mtfsf': {
        mnemonic: 'mtfsf',
        name: 'Move To FPSCR Fields',
        syntax: 'mtfsf FM, frB',
        description: 'Copies fields from frB to FPSCR.',
        operation: 'FPSCR[selected] ← frB[selected]',
        category: 'system'
    },
    'mtfsb0': {
        mnemonic: 'mtfsb0',
        name: 'Move To FPSCR Bit 0',
        syntax: 'mtfsb0 crbD',
        description: 'Clears specified FPSCR bit.',
        operation: 'FPSCR[crbD] ← 0',
        category: 'system'
    },
    'mtfsb1': {
        mnemonic: 'mtfsb1',
        name: 'Move To FPSCR Bit 1',
        syntax: 'mtfsb1 crbD',
        description: 'Sets specified FPSCR bit.',
        operation: 'FPSCR[crbD] ← 1',
        category: 'system'
    },
    'mfspr': {
        mnemonic: 'mfspr',
        name: 'Move From Special Purpose Register',
        syntax: 'mfspr rD, SPR',
        description: 'Copies SPR to rD. SPR can be LR, CTR, XER, etc.',
        operation: 'rD ← SPR',
        category: 'system'
    },
    'mtspr': {
        mnemonic: 'mtspr',
        name: 'Move To Special Purpose Register',
        syntax: 'mtspr SPR, rS',
        description: 'Copies rS to SPR.',
        operation: 'SPR ← rS',
        category: 'system'
    },
    'mfxer': {
        mnemonic: 'mfxer',
        name: 'Move From XER',
        syntax: 'mfxer rD',
        description: 'Copies XER (overflow/carry flags) to rD.',
        operation: 'rD ← XER',
        category: 'system'
    },
    'mtxer': {
        mnemonic: 'mtxer',
        name: 'Move To XER',
        syntax: 'mtxer rS',
        description: 'Copies rS to XER.',
        operation: 'XER ← rS',
        category: 'system'
    },

    // ============ Condition Register Operations ============
    'crand': {
        mnemonic: 'crand',
        name: 'Condition Register AND',
        syntax: 'crand crbD, crbA, crbB',
        description: 'ANDs two CR bits.',
        operation: 'CR[crbD] ← CR[crbA] & CR[crbB]',
        category: 'logical'
    },
    'crandc': {
        mnemonic: 'crandc',
        name: 'Condition Register AND with Complement',
        syntax: 'crandc crbD, crbA, crbB',
        description: 'ANDs CR bit with complement of another.',
        operation: 'CR[crbD] ← CR[crbA] & ¬CR[crbB]',
        category: 'logical'
    },
    'creqv': {
        mnemonic: 'creqv',
        name: 'Condition Register Equivalent',
        syntax: 'creqv crbD, crbA, crbB',
        description: 'XNORs two CR bits.',
        operation: 'CR[crbD] ← CR[crbA] XNOR CR[crbB]',
        category: 'logical'
    },
    'crnand': {
        mnemonic: 'crnand',
        name: 'Condition Register NAND',
        syntax: 'crnand crbD, crbA, crbB',
        description: 'NANDs two CR bits.',
        operation: 'CR[crbD] ← ¬(CR[crbA] & CR[crbB])',
        category: 'logical'
    },
    'crnor': {
        mnemonic: 'crnor',
        name: 'Condition Register NOR',
        syntax: 'crnor crbD, crbA, crbB',
        description: 'NORs two CR bits.',
        operation: 'CR[crbD] ← ¬(CR[crbA] | CR[crbB])',
        category: 'logical'
    },
    'cror': {
        mnemonic: 'cror',
        name: 'Condition Register OR',
        syntax: 'cror crbD, crbA, crbB',
        description: 'ORs two CR bits.',
        operation: 'CR[crbD] ← CR[crbA] | CR[crbB]',
        category: 'logical'
    },
    'crorc': {
        mnemonic: 'crorc',
        name: 'Condition Register OR with Complement',
        syntax: 'crorc crbD, crbA, crbB',
        description: 'ORs CR bit with complement of another.',
        operation: 'CR[crbD] ← CR[crbA] | ¬CR[crbB]',
        category: 'logical'
    },
    'crxor': {
        mnemonic: 'crxor',
        name: 'Condition Register XOR',
        syntax: 'crxor crbD, crbA, crbB',
        description: 'XORs two CR bits. crxor N,N,N clears bit N.',
        operation: 'CR[crbD] ← CR[crbA] ^ CR[crbB]',
        category: 'logical'
    },
    'mcrf': {
        mnemonic: 'mcrf',
        name: 'Move Condition Register Field',
        syntax: 'mcrf crfD, crfS',
        description: 'Copies one CR field to another.',
        operation: 'CR[crfD] ← CR[crfS]',
        category: 'logical'
    },

    // ============ Paired Singles (GameCube/Wii specific) ============
    'psq_l': {
        mnemonic: 'psq_l',
        name: 'Paired Single Quantized Load',
        syntax: 'psq_l frD, d(rA), W, I',
        description: 'Loads one or two quantized floats. W=0 loads pair, W=1 loads single. I selects GQR for dequantization.',
        operation: 'frD ← dequantize(MEM, GQR[I])',
        category: 'paired-single'
    },
    'psq_lu': {
        mnemonic: 'psq_lu',
        name: 'Paired Single Quantized Load with Update',
        syntax: 'psq_lu frD, d(rA), W, I',
        description: 'Loads quantized float(s), updates rA.',
        operation: 'EA ← rA + d; frD ← dequantize(MEM(EA), GQR[I]); rA ← EA',
        category: 'paired-single'
    },
    'psq_lx': {
        mnemonic: 'psq_lx',
        name: 'Paired Single Quantized Load Indexed',
        syntax: 'psq_lx frD, rA, rB, W, I',
        description: 'Loads quantized float(s) from rA + rB.',
        operation: 'frD ← dequantize(MEM(rA + rB), GQR[I])',
        category: 'paired-single'
    },
    'psq_st': {
        mnemonic: 'psq_st',
        name: 'Paired Single Quantized Store',
        syntax: 'psq_st frS, d(rA), W, I',
        description: 'Stores one or two quantized floats. W=0 stores pair, W=1 stores single.',
        operation: 'MEM ← quantize(frS, GQR[I])',
        category: 'paired-single'
    },
    'psq_stu': {
        mnemonic: 'psq_stu',
        name: 'Paired Single Quantized Store with Update',
        syntax: 'psq_stu frS, d(rA), W, I',
        description: 'Stores quantized float(s), updates rA.',
        operation: 'EA ← rA + d; MEM(EA) ← quantize(frS, GQR[I]); rA ← EA',
        category: 'paired-single'
    },
    'psq_stx': {
        mnemonic: 'psq_stx',
        name: 'Paired Single Quantized Store Indexed',
        syntax: 'psq_stx frS, rA, rB, W, I',
        description: 'Stores quantized float(s) to rA + rB.',
        operation: 'MEM(rA + rB) ← quantize(frS, GQR[I])',
        category: 'paired-single'
    },
    'ps_add': {
        mnemonic: 'ps_add',
        name: 'Paired Single Add',
        syntax: 'ps_add frD, frA, frB',
        description: 'Adds both slots of paired single registers.',
        operation: 'frD[0] ← frA[0] + frB[0]; frD[1] ← frA[1] + frB[1]',
        category: 'paired-single'
    },
    'ps_sub': {
        mnemonic: 'ps_sub',
        name: 'Paired Single Subtract',
        syntax: 'ps_sub frD, frA, frB',
        description: 'Subtracts both slots of paired single registers.',
        operation: 'frD[0] ← frA[0] - frB[0]; frD[1] ← frA[1] - frB[1]',
        category: 'paired-single'
    },
    'ps_mul': {
        mnemonic: 'ps_mul',
        name: 'Paired Single Multiply',
        syntax: 'ps_mul frD, frA, frC',
        description: 'Multiplies both slots of paired single registers.',
        operation: 'frD[0] ← frA[0] × frC[0]; frD[1] ← frA[1] × frC[1]',
        category: 'paired-single'
    },
    'ps_div': {
        mnemonic: 'ps_div',
        name: 'Paired Single Divide',
        syntax: 'ps_div frD, frA, frB',
        description: 'Divides both slots of paired single registers.',
        operation: 'frD[0] ← frA[0] ÷ frB[0]; frD[1] ← frA[1] ÷ frB[1]',
        category: 'paired-single'
    },
    'ps_madd': {
        mnemonic: 'ps_madd',
        name: 'Paired Single Multiply-Add',
        syntax: 'ps_madd frD, frA, frC, frB',
        description: 'Fused multiply-add on both slots.',
        operation: 'frD[i] ← (frA[i] × frC[i]) + frB[i]',
        category: 'paired-single'
    },
    'ps_msub': {
        mnemonic: 'ps_msub',
        name: 'Paired Single Multiply-Subtract',
        syntax: 'ps_msub frD, frA, frC, frB',
        description: 'Fused multiply-subtract on both slots.',
        operation: 'frD[i] ← (frA[i] × frC[i]) - frB[i]',
        category: 'paired-single'
    },
    'ps_nmadd': {
        mnemonic: 'ps_nmadd',
        name: 'Paired Single Negative Multiply-Add',
        syntax: 'ps_nmadd frD, frA, frC, frB',
        description: 'Negated fused multiply-add on both slots.',
        operation: 'frD[i] ← -((frA[i] × frC[i]) + frB[i])',
        category: 'paired-single'
    },
    'ps_nmsub': {
        mnemonic: 'ps_nmsub',
        name: 'Paired Single Negative Multiply-Subtract',
        syntax: 'ps_nmsub frD, frA, frC, frB',
        description: 'Negated fused multiply-subtract on both slots.',
        operation: 'frD[i] ← -((frA[i] × frC[i]) - frB[i])',
        category: 'paired-single'
    },
    'ps_neg': {
        mnemonic: 'ps_neg',
        name: 'Paired Single Negate',
        syntax: 'ps_neg frD, frB',
        description: 'Negates both slots.',
        operation: 'frD[0] ← -frB[0]; frD[1] ← -frB[1]',
        category: 'paired-single'
    },
    'ps_abs': {
        mnemonic: 'ps_abs',
        name: 'Paired Single Absolute Value',
        syntax: 'ps_abs frD, frB',
        description: 'Absolute value of both slots.',
        operation: 'frD[0] ← |frB[0]|; frD[1] ← |frB[1]|',
        category: 'paired-single'
    },
    'ps_mr': {
        mnemonic: 'ps_mr',
        name: 'Paired Single Move Register',
        syntax: 'ps_mr frD, frB',
        description: 'Copies frB to frD (both slots).',
        operation: 'frD ← frB',
        category: 'paired-single'
    },
    'ps_sel': {
        mnemonic: 'ps_sel',
        name: 'Paired Single Select',
        syntax: 'ps_sel frD, frA, frC, frB',
        description: 'Selects frC or frB based on sign of frA for each slot.',
        operation: 'frD[i] ← (frA[i] >= 0) ? frC[i] : frB[i]',
        category: 'paired-single'
    },
    'ps_res': {
        mnemonic: 'ps_res',
        name: 'Paired Single Reciprocal Estimate',
        syntax: 'ps_res frD, frB',
        description: 'Estimates reciprocal of both slots.',
        operation: 'frD[i] ≈ 1/frB[i]',
        category: 'paired-single'
    },
    'ps_rsqrte': {
        mnemonic: 'ps_rsqrte',
        name: 'Paired Single Reciprocal Square Root Estimate',
        syntax: 'ps_rsqrte frD, frB',
        description: 'Estimates inverse square root of both slots.',
        operation: 'frD[i] ≈ 1/√frB[i]',
        category: 'paired-single'
    },
    'ps_sum0': {
        mnemonic: 'ps_sum0',
        name: 'Paired Single Sum High',
        syntax: 'ps_sum0 frD, frA, frC, frB',
        description: 'Adds frA[0] + frB[1], copies frC[1] to low slot.',
        operation: 'frD[0] ← frA[0] + frB[1]; frD[1] ← frC[1]',
        category: 'paired-single'
    },
    'ps_sum1': {
        mnemonic: 'ps_sum1',
        name: 'Paired Single Sum Low',
        syntax: 'ps_sum1 frD, frA, frC, frB',
        description: 'Copies frC[0] to high slot, adds frA[0] + frB[1] to low.',
        operation: 'frD[0] ← frC[0]; frD[1] ← frA[0] + frB[1]',
        category: 'paired-single'
    },
    'ps_muls0': {
        mnemonic: 'ps_muls0',
        name: 'Paired Single Multiply Scalar High',
        syntax: 'ps_muls0 frD, frA, frC',
        description: 'Multiplies both slots of frA by frC[0] (scalar).',
        operation: 'frD[i] ← frA[i] × frC[0]',
        category: 'paired-single'
    },
    'ps_muls1': {
        mnemonic: 'ps_muls1',
        name: 'Paired Single Multiply Scalar Low',
        syntax: 'ps_muls1 frD, frA, frC',
        description: 'Multiplies both slots of frA by frC[1] (scalar).',
        operation: 'frD[i] ← frA[i] × frC[1]',
        category: 'paired-single'
    },
    'ps_madds0': {
        mnemonic: 'ps_madds0',
        name: 'Paired Single Multiply-Add Scalar High',
        syntax: 'ps_madds0 frD, frA, frC, frB',
        description: 'Fused multiply-add using frC[0] as scalar.',
        operation: 'frD[i] ← (frA[i] × frC[0]) + frB[i]',
        category: 'paired-single'
    },
    'ps_madds1': {
        mnemonic: 'ps_madds1',
        name: 'Paired Single Multiply-Add Scalar Low',
        syntax: 'ps_madds1 frD, frA, frC, frB',
        description: 'Fused multiply-add using frC[1] as scalar.',
        operation: 'frD[i] ← (frA[i] × frC[1]) + frB[i]',
        category: 'paired-single'
    },
    'ps_merge00': {
        mnemonic: 'ps_merge00',
        name: 'Paired Single Merge High',
        syntax: 'ps_merge00 frD, frA, frB',
        description: 'Merges high slots of frA and frB.',
        operation: 'frD[0] ← frA[0]; frD[1] ← frB[0]',
        category: 'paired-single'
    },
    'ps_merge01': {
        mnemonic: 'ps_merge01',
        name: 'Paired Single Merge High-Low',
        syntax: 'ps_merge01 frD, frA, frB',
        description: 'Merges frA high with frB low.',
        operation: 'frD[0] ← frA[0]; frD[1] ← frB[1]',
        category: 'paired-single'
    },
    'ps_merge10': {
        mnemonic: 'ps_merge10',
        name: 'Paired Single Merge Low-High',
        syntax: 'ps_merge10 frD, frA, frB',
        description: 'Merges frA low with frB high.',
        operation: 'frD[0] ← frA[1]; frD[1] ← frB[0]',
        category: 'paired-single'
    },
    'ps_merge11': {
        mnemonic: 'ps_merge11',
        name: 'Paired Single Merge Low',
        syntax: 'ps_merge11 frD, frA, frB',
        description: 'Merges low slots of frA and frB.',
        operation: 'frD[0] ← frA[1]; frD[1] ← frB[1]',
        category: 'paired-single'
    },
    'ps_cmpu0': {
        mnemonic: 'ps_cmpu0',
        name: 'Paired Single Compare Unordered High',
        syntax: 'ps_cmpu0 crfD, frA, frB',
        description: 'Compares high slots of frA and frB.',
        operation: 'CR[crfD] ← compare(frA[0], frB[0])',
        flags: 'CR',
        category: 'paired-single'
    },
    'ps_cmpu1': {
        mnemonic: 'ps_cmpu1',
        name: 'Paired Single Compare Unordered Low',
        syntax: 'ps_cmpu1 crfD, frA, frB',
        description: 'Compares low slots of frA and frB.',
        operation: 'CR[crfD] ← compare(frA[1], frB[1])',
        flags: 'CR',
        category: 'paired-single'
    },
    'ps_cmpo0': {
        mnemonic: 'ps_cmpo0',
        name: 'Paired Single Compare Ordered High',
        syntax: 'ps_cmpo0 crfD, frA, frB',
        description: 'Compares high slots (ordered, may trap on NaN).',
        operation: 'CR[crfD] ← compare(frA[0], frB[0])',
        flags: 'CR, FPSCR',
        category: 'paired-single'
    },
    'ps_cmpo1': {
        mnemonic: 'ps_cmpo1',
        name: 'Paired Single Compare Ordered Low',
        syntax: 'ps_cmpo1 crfD, frA, frB',
        description: 'Compares low slots (ordered, may trap on NaN).',
        operation: 'CR[crfD] ← compare(frA[1], frB[1])',
        flags: 'CR, FPSCR',
        category: 'paired-single'
    },

    // ============ Simplified Mnemonics ============
    'li': {
        mnemonic: 'li',
        name: 'Load Immediate',
        syntax: 'li rD, value',
        description: 'Loads a signed 16-bit value into rD. Simplified mnemonic for addi rD, 0, value.',
        operation: 'rD ← EXTS(value)',
        category: 'integer'
    },
    'lis': {
        mnemonic: 'lis',
        name: 'Load Immediate Shifted',
        syntax: 'lis rD, value',
        description: 'Loads value << 16 into rD. Simplified mnemonic for addis rD, 0, value. Used with ori for 32-bit constants.',
        operation: 'rD ← value << 16',
        category: 'integer'
    },
    'la': {
        mnemonic: 'la',
        name: 'Load Address',
        syntax: 'la rD, d(rA)',
        description: 'Calculates effective address rA + d. Simplified mnemonic for addi.',
        operation: 'rD ← rA + d',
        category: 'integer'
    },
    'mr': {
        mnemonic: 'mr',
        name: 'Move Register',
        syntax: 'mr rA, rS',
        description: 'Copies rS to rA. Simplified mnemonic for or rA, rS, rS.',
        operation: 'rA ← rS',
        category: 'integer'
    },
    'not': {
        mnemonic: 'not',
        name: 'Complement',
        syntax: 'not rA, rS',
        description: 'Bitwise complement of rS. Simplified mnemonic for nor rA, rS, rS.',
        operation: 'rA ← ¬rS',
        category: 'logical'
    },
    'nop': {
        mnemonic: 'nop',
        name: 'No Operation',
        syntax: 'nop',
        description: 'Does nothing. Simplified mnemonic for ori 0, 0, 0.',
        operation: '(no operation)',
        category: 'system'
    },
    'subi': {
        mnemonic: 'subi',
        name: 'Subtract Immediate',
        syntax: 'subi rD, rA, value',
        description: 'Subtracts immediate from rA. Simplified mnemonic for addi rD, rA, -value.',
        operation: 'rD ← rA - value',
        category: 'integer'
    },
    'subis': {
        mnemonic: 'subis',
        name: 'Subtract Immediate Shifted',
        syntax: 'subis rD, rA, value',
        description: 'Subtracts value << 16 from rA. Simplified mnemonic for addis rD, rA, -value.',
        operation: 'rD ← rA - (value << 16)',
        category: 'integer'
    },
    'sub': {
        mnemonic: 'sub',
        name: 'Subtract',
        syntax: 'sub rD, rA, rB',
        description: 'Subtracts rB from rA. Simplified mnemonic for subf rD, rB, rA (note operand swap).',
        operation: 'rD ← rA - rB',
        category: 'integer'
    },
    'rotlwi': {
        mnemonic: 'rotlwi',
        name: 'Rotate Left Word Immediate',
        syntax: 'rotlwi rA, rS, n',
        description: 'Rotates rS left by n bits. Simplified mnemonic for rlwinm rA, rS, n, 0, 31.',
        operation: 'rA ← ROTL(rS, n)',
        category: 'logical'
    },
    'rotrwi': {
        mnemonic: 'rotrwi',
        name: 'Rotate Right Word Immediate',
        syntax: 'rotrwi rA, rS, n',
        description: 'Rotates rS right by n bits. Simplified mnemonic for rlwinm rA, rS, 32-n, 0, 31.',
        operation: 'rA ← ROTR(rS, n)',
        category: 'logical'
    },

    // ============ Memory Synchronization ============
    'sync': {
        mnemonic: 'sync',
        name: 'Synchronize',
        syntax: 'sync',
        description: 'Memory barrier. Ensures all previous memory accesses complete before continuing.',
        operation: 'memory_barrier()',
        category: 'system'
    },
    'isync': {
        mnemonic: 'isync',
        name: 'Instruction Synchronize',
        syntax: 'isync',
        description: 'Instruction barrier. Ensures instruction fetches see previous stores.',
        operation: 'instruction_barrier()',
        category: 'system'
    },
    'eieio': {
        mnemonic: 'eieio',
        name: 'Enforce In-Order Execution of I/O',
        syntax: 'eieio',
        description: 'Orders I/O operations. Required for hardware register access.',
        operation: 'io_barrier()',
        category: 'system'
    },
    'dcbf': {
        mnemonic: 'dcbf',
        name: 'Data Cache Block Flush',
        syntax: 'dcbf rA, rB',
        description: 'Flushes cache block containing address rA + rB to memory.',
        operation: 'flush_cache_block(rA + rB)',
        category: 'system'
    },
    'dcbi': {
        mnemonic: 'dcbi',
        name: 'Data Cache Block Invalidate',
        syntax: 'dcbi rA, rB',
        description: 'Invalidates cache block (discards without writeback). Privileged.',
        operation: 'invalidate_cache_block(rA + rB)',
        category: 'system'
    },
    'dcbst': {
        mnemonic: 'dcbst',
        name: 'Data Cache Block Store',
        syntax: 'dcbst rA, rB',
        description: 'Writes cache block to memory (keeps in cache).',
        operation: 'store_cache_block(rA + rB)',
        category: 'system'
    },
    'dcbt': {
        mnemonic: 'dcbt',
        name: 'Data Cache Block Touch',
        syntax: 'dcbt rA, rB',
        description: 'Prefetch hint - brings cache block into L1 data cache.',
        operation: 'prefetch(rA + rB)',
        category: 'system'
    },
    'dcbz': {
        mnemonic: 'dcbz',
        name: 'Data Cache Block Zero',
        syntax: 'dcbz rA, rB',
        description: 'Allocates cache block and zeros it. Fast memset for 32-byte aligned blocks.',
        operation: 'zero_cache_block(rA + rB)',
        category: 'system'
    },
    'icbi': {
        mnemonic: 'icbi',
        name: 'Instruction Cache Block Invalidate',
        syntax: 'icbi rA, rB',
        description: 'Invalidates instruction cache block. Required after modifying code.',
        operation: 'invalidate_icache_block(rA + rB)',
        category: 'system'
    },
};

/**
 * Look up instruction info by mnemonic
 */
export function getInstructionInfo(mnemonic: string): InstructionInfo | undefined {
    // Normalize mnemonic (lowercase, remove trailing +/-)
    const normalized = mnemonic.toLowerCase().replace(/[+-]$/, '');
    return ppcInstructions[normalized];
}

/**
 * Get category color for syntax highlighting
 */
export function getCategoryColor(category: InstructionInfo['category']): string {
    switch (category) {
        case 'integer': return '#9cdcfe';      // blue
        case 'float': return '#c586c0';        // purple
        case 'load-store': return '#4ec9b0';   // cyan
        case 'branch': return '#dcdcaa';       // yellow
        case 'compare': return '#ce9178';      // orange
        case 'logical': return '#b5cea8';      // green
        case 'system': return '#d4d4d4';       // gray
        case 'paired-single': return '#f14c4c'; // red
        default: return '#d4d4d4';
    }
}
