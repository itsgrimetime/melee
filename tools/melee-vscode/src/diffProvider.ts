import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { buildEnhancedDiff, InstructionDiff, ParsedInstruction, BranchArrow } from './asmParser';

export interface DiffLine {
    target: string;
    current: string;
    status: 'match' | 'mismatch' | 'target-only' | 'current-only';
    diffType?: 'r' | 'i' | 'o' | 's';  // register, immediate, opcode, stack
    mismatchedParts?: Array<{
        partType: 'mnemonic' | 'operand';
        targetValue: string;
        currentValue: string;
        operandIndex?: number;
    }>;
    targetParsed?: ParsedInstruction | null;
    currentParsed?: ParsedInstruction | null;
}

export interface DiffResult {
    functionName: string;
    match: boolean;
    matchPercent: number;
    targetLines: string[];
    currentLines: string[];
    diffLines: DiffLine[];
    targetArrows: BranchArrow[];
    currentArrows: BranchArrow[];
    buildError?: string;
}

export interface ReportFunction {
    name: string;
    fuzzy_match_percent?: number;
}

export interface ReportUnit {
    name: string;
    functions: ReportFunction[];
    metadata?: {
        source_path?: string;
    };
}

export interface Report {
    units: ReportUnit[];
}

export class DiffProvider {
    private workspaceRoot: string;
    private reportCache: Report | null = null;
    private reportMtime: number = 0;

    constructor(workspaceRoot: string) {
        this.workspaceRoot = workspaceRoot;
    }

    async getDiff(functionName: string): Promise<DiffResult> {
        // First try the enhanced JSON output from checkdiff.py
        const checkdiffPath = path.join(this.workspaceRoot, 'tools', 'checkdiff.py');

        console.log(`[melee-decomp] getDiff called for: ${functionName}`);
        console.log(`[melee-decomp] workspaceRoot: ${this.workspaceRoot}`);
        console.log(`[melee-decomp] checkdiffPath: ${checkdiffPath}`);

        return new Promise((resolve, reject) => {
            const proc = cp.spawn('python3', [checkdiffPath, functionName, '--format', 'json'], {
                cwd: this.workspaceRoot,
                env: { ...process.env }
            });

            console.log(`[melee-decomp] Spawned process for ${functionName}`);

            let stdout = '';
            let stderr = '';

            proc.stdout.on('data', (data) => {
                stdout += data.toString();
            });

            proc.stderr.on('data', (data) => {
                stderr += data.toString();
            });

            proc.on('close', (code) => {
                console.log(`[melee-decomp] Process exited with code: ${code}`);
                console.log(`[melee-decomp] stdout length: ${stdout.length}`);
                console.log(`[melee-decomp] stderr length: ${stderr.length}`);
                if (stderr) {
                    console.log(`[melee-decomp] stderr: ${stderr.slice(0, 500)}`);
                }

                if (code !== 0) {
                    // Build or diff failed
                    const errorMsg = stderr || stdout || `checkdiff.py exited with code ${code}`;
                    console.log(`[melee-decomp] Error: ${errorMsg.slice(0, 500)}`);
                    reject(new Error(errorMsg.trim()));
                    return;
                }

                // Try to find JSON in stdout (skip any non-JSON prefix)
                const jsonMatch = stdout.match(/^\s*(\{[\s\S]*\})\s*$/);
                if (!jsonMatch) {
                    console.log(`[melee-decomp] No JSON match. stdout: ${stdout.slice(0, 200)}`);
                    reject(new Error(`No JSON found in output. stdout: ${stdout.slice(0, 200)}`));
                    return;
                }

                try {
                    const jsonData = JSON.parse(jsonMatch[1]);
                    const result = this.parseCheckdiffJson(jsonData, functionName);
                    console.log(`[melee-decomp] Success! Match: ${result.match}, ${result.matchPercent}%`);
                    resolve(result);
                } catch (e) {
                    console.log(`[melee-decomp] JSON parse error: ${e}`);
                    reject(new Error(`Failed to parse checkdiff output: ${e}\nOutput: ${stdout.slice(0, 500)}`));
                }
            });

            proc.on('error', (err) => {
                reject(new Error(`Failed to run checkdiff.py: ${err.message}`));
            });
        });
    }

    private parseCheckdiffJson(data: {
        function: string;
        reference_lines: number;
        current_lines: number;
        match: boolean;
        diff: string[];
        target_asm?: string[];
        current_asm?: string[];
    }, functionName: string): DiffResult {
        // Parse unified diff to extract side-by-side lines
        const diffLines: DiffLine[] = [];
        const targetLines: string[] = [];
        const currentLines: string[] = [];

        // If we have raw ASM lines (enhanced output), use them
        if (data.target_asm && data.current_asm) {
            return this.buildSideBySideDiff(
                data.target_asm,
                data.current_asm,
                functionName,
                data.match
            );
        }

        // Otherwise, parse unified diff format
        const unifiedDiff = data.diff;
        let targetIdx = 0;
        let currentIdx = 0;

        for (const line of unifiedDiff) {
            if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) {
                continue;
            }

            if (line.startsWith('-')) {
                // Line only in target (expected)
                const text = line.substring(1);
                targetLines.push(text);
                diffLines.push({
                    target: text,
                    current: '',
                    status: 'target-only'
                });
            } else if (line.startsWith('+')) {
                // Line only in current
                const text = line.substring(1);
                currentLines.push(text);
                diffLines.push({
                    target: '',
                    current: text,
                    status: 'current-only'
                });
            } else if (line.startsWith(' ')) {
                // Context line (matches)
                const text = line.substring(1);
                targetLines.push(text);
                currentLines.push(text);
                diffLines.push({
                    target: text,
                    current: text,
                    status: 'match'
                });
            }
        }

        // Calculate match percentage from line counts
        const totalLines = Math.max(data.reference_lines, data.current_lines);
        const matchingLines = diffLines.filter(l => l.status === 'match').length;
        const matchPercent = totalLines > 0 ? Math.round((matchingLines / totalLines) * 100) : 100;

        return {
            functionName,
            match: data.match,
            matchPercent,
            targetLines,
            currentLines,
            diffLines,
            targetArrows: [],
            currentArrows: []
        };
    }

    private buildSideBySideDiff(
        targetAsm: string[],
        currentAsm: string[],
        functionName: string,
        isMatch: boolean
    ): DiffResult {
        // Use enhanced diff parser for detailed comparison
        const { diffs: enhancedDiffs, targetArrows, currentArrows } = buildEnhancedDiff(targetAsm, currentAsm);

        const diffLines: DiffLine[] = [];
        let matchCount = 0;

        for (let i = 0; i < enhancedDiffs.length; i++) {
            const ed = enhancedDiffs[i];
            const target = targetAsm[i] || '';
            const current = currentAsm[i] || '';

            if (ed.status === 'match') {
                matchCount++;
            }

            diffLines.push({
                target,
                current,
                status: ed.status,
                diffType: ed.diffType,
                mismatchedParts: ed.mismatchedParts,
                targetParsed: ed.target,
                currentParsed: ed.current
            });
        }

        const maxLen = Math.max(targetAsm.length, currentAsm.length);
        const matchPercent = maxLen > 0 ? Math.round((matchCount / maxLen) * 100) : 100;

        return {
            functionName,
            match: isMatch,
            matchPercent,
            targetLines: targetAsm,
            currentLines: currentAsm,
            diffLines,
            targetArrows,
            currentArrows
        };
    }

    async getReport(): Promise<Report> {
        const reportPath = path.join(this.workspaceRoot, 'build', 'GALE01', 'report.json');

        try {
            const stat = fs.statSync(reportPath);
            if (this.reportCache && stat.mtimeMs === this.reportMtime) {
                return this.reportCache;
            }

            const content = fs.readFileSync(reportPath, 'utf-8');
            this.reportCache = JSON.parse(content);
            this.reportMtime = stat.mtimeMs;
            return this.reportCache!;
        } catch (e) {
            throw new Error(`Failed to read report.json: ${e}`);
        }
    }

    async getFunctionsInFile(filePath: string): Promise<ReportFunction[]> {
        const report = await this.getReport();
        const relativePath = path.relative(this.workspaceRoot, filePath);

        // Find unit matching this file
        for (const unit of report.units) {
            const unitSourcePath = unit.metadata?.source_path;
            if (unitSourcePath && relativePath.endsWith(unitSourcePath.replace('src/', ''))) {
                return unit.functions;
            }

            // Also check by unit name
            const unitPath = unit.name.replace('main/', '');
            if (relativePath.includes(unitPath)) {
                return unit.functions;
            }
        }

        return [];
    }

    async getFunctionMatchPercent(functionName: string): Promise<number | undefined> {
        const report = await this.getReport();

        for (const unit of report.units) {
            for (const func of unit.functions) {
                if (func.name === functionName) {
                    return func.fuzzy_match_percent;
                }
            }
        }

        return undefined;
    }
}
