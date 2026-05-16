import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { ParsedInstruction, BranchArrow, parseInstruction, compareInstructions, extractBranchArrows } from './asmParser';

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
        const checkdiffPath = path.join(this.workspaceRoot, 'tools', 'checkdiff.py');
        const TIMEOUT_MS = 60000;  // 60 second timeout

        return new Promise((resolve, reject) => {
            const proc = cp.spawn('python3', [checkdiffPath, functionName, '--format', 'json'], {
                cwd: this.workspaceRoot,
                env: { ...process.env }
            });

            const timeout = setTimeout(() => {
                proc.kill();
                reject(new Error(`checkdiff.py timed out after ${TIMEOUT_MS / 1000}s`));
            }, TIMEOUT_MS);

            let stdout = '';
            let stderr = '';

            proc.stdout.on('data', (data) => {
                stdout += data.toString();
            });

            proc.stderr.on('data', (data) => {
                stderr += data.toString();
            });

            proc.on('close', (code) => {
                clearTimeout(timeout);

                if (code !== 0) {
                    const errorMsg = stderr || stdout || `checkdiff.py exited with code ${code}`;
                    reject(new Error(errorMsg.trim()));
                    return;
                }

                // Try to find JSON in stdout
                const jsonMatch = stdout.match(/^\s*(\{[\s\S]*\})\s*$/);
                if (!jsonMatch) {
                    reject(new Error(`No JSON found in output. stdout: ${stdout.slice(0, 200)}`));
                    return;
                }

                try {
                    const jsonData = JSON.parse(jsonMatch[1]);
                    const result = this.parseCheckdiffJson(jsonData, functionName);
                    resolve(result);
                } catch (e) {
                    reject(new Error(`Failed to parse checkdiff output: ${e}\nOutput: ${stdout.slice(0, 500)}`));
                }
            });

            proc.on('error', (err) => {
                clearTimeout(timeout);
                reject(new Error(`Failed to run checkdiff.py: ${err.message}`));
            });
        });
    }

    private parseCheckdiffJson(data: {
        function: string;
        reference_lines: number;
        current_lines: number;
        match: boolean;
        fuzzy_match_percent?: number;
        diff: string[];
        target_asm?: string[];
        current_asm?: string[];
    }, functionName: string): DiffResult {
        // Always use unified diff for proper alignment
        // Then enhance with parsed instruction data for syntax highlighting
        return this.buildAlignedDiff(
            data.diff,
            functionName,
            data.match,
            data.reference_lines,
            data.current_lines,
            data.target_asm || [],
            data.current_asm || [],
            data.fuzzy_match_percent
        );
    }

    /**
     * Build a properly aligned side-by-side diff from unified diff format.
     * This handles insertions, deletions, and changes correctly.
     */
    private buildAlignedDiff(
        unifiedDiff: string[],
        functionName: string,
        isMatch: boolean,
        referenceLines: number,
        currentLines: number,
        targetAsm: string[],
        currentAsm: string[],
        fuzzyMatchPercent?: number
    ): DiffResult {
        const diffLines: DiffLine[] = [];
        const targetLines: string[] = [];
        const currentLines_: string[] = [];

        // Find the starting line from the @@ header
        // Format: @@ -startLine,count +startLine,count @@
        let diffStartLine = 1;
        for (const line of unifiedDiff) {
            const match = line.match(/^@@ -(\d+),?\d* \+(\d+),?\d* @@/);
            if (match) {
                diffStartLine = parseInt(match[1], 10);
                break;
            }
        }

        // Add lines before the diff starts (these are matching lines not shown in diff)
        // Lines are 1-indexed in diff format, but 0-indexed in arrays
        for (let i = 0; i < diffStartLine - 1 && i < targetAsm.length && i < currentAsm.length; i++) {
            const target = targetAsm[i];
            const current = currentAsm[i];
            targetLines.push(target);
            currentLines_.push(current);

            const instr = parseInstruction(target);
            diffLines.push({
                target,
                current,
                status: 'match',
                targetParsed: instr,
                currentParsed: instr
            });
        }

        // Track line indices as we process the diff
        let targetIdx = diffStartLine - 1;  // 0-indexed
        let currentIdx = diffStartLine - 1;

        // Collect consecutive +/- pairs to display as side-by-side changes
        let pendingDeletes: string[] = [];
        let pendingInserts: string[] = [];

        const flushPending = () => {
            // Pair up deletes and inserts as side-by-side changes
            const maxLen = Math.max(pendingDeletes.length, pendingInserts.length);
            for (let i = 0; i < maxLen; i++) {
                const target = pendingDeletes[i] || '';
                const current = pendingInserts[i] || '';

                targetLines.push(target);
                currentLines_.push(current);
                if (pendingDeletes[i]) targetIdx++;
                if (pendingInserts[i]) currentIdx++;

                if (target && current) {
                    // Both sides have content - compare them
                    const targetInstr = parseInstruction(target);
                    const currentInstr = parseInstruction(current);
                    const comparison = compareInstructions(targetInstr, currentInstr);

                    diffLines.push({
                        target,
                        current,
                        status: comparison.status,
                        diffType: comparison.diffType,
                        mismatchedParts: comparison.mismatchedParts,
                        targetParsed: comparison.target,
                        currentParsed: comparison.current
                    });
                } else if (target) {
                    // Only target (delete)
                    const targetInstr = parseInstruction(target);
                    diffLines.push({
                        target,
                        current: '',
                        status: 'target-only',
                        targetParsed: targetInstr,
                        currentParsed: null
                    });
                } else {
                    // Only current (insert)
                    const currentInstr = parseInstruction(current);
                    diffLines.push({
                        target: '',
                        current,
                        status: 'current-only',
                        targetParsed: null,
                        currentParsed: currentInstr
                    });
                }
            }
            pendingDeletes = [];
            pendingInserts = [];
        };

        for (const line of unifiedDiff) {
            if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) {
                continue;
            }

            if (line.startsWith('-')) {
                // Delete line - queue it
                pendingDeletes.push(line.substring(1));
            } else if (line.startsWith('+')) {
                // Insert line - queue it
                pendingInserts.push(line.substring(1));
            } else if (line.startsWith(' ')) {
                // Context line - flush any pending changes first
                flushPending();

                const text = line.substring(1);
                targetLines.push(text);
                currentLines_.push(text);
                targetIdx++;
                currentIdx++;

                const instr = parseInstruction(text);
                diffLines.push({
                    target: text,
                    current: text,
                    status: 'match',
                    targetParsed: instr,
                    currentParsed: instr
                });
            }
        }

        // Flush any remaining pending changes
        flushPending();

        // Add trailing lines after the diff (matching lines not shown in diff)
        while (targetIdx < targetAsm.length && currentIdx < currentAsm.length) {
            const target = targetAsm[targetIdx];
            const current = currentAsm[currentIdx];

            // These should be matching lines
            targetLines.push(target);
            currentLines_.push(current);
            targetIdx++;
            currentIdx++;

            const instr = parseInstruction(target);
            diffLines.push({
                target,
                current,
                status: 'match',
                targetParsed: instr,
                currentParsed: instr
            });
        }

        // Use fuzzy_match_percent from objdiff (via checkdiff.py which regenerates report.json)
        // This is the authoritative match percentage calculated by objdiff-cli
        let matchPercent: number;
        if (isMatch) {
            matchPercent = 100;
        } else if (fuzzyMatchPercent !== undefined) {
            matchPercent = fuzzyMatchPercent;
        } else {
            // Fallback: calculate from actual instruction lines if no fuzzy match available
            const instrLines = diffLines.filter(l =>
                (l.target && !l.target.trim().startsWith('<')) ||
                (l.current && !l.current.trim().startsWith('<'))
            );
            const matchingLines = instrLines.filter(l => l.status === 'match').length;
            const totalInstrLines = instrLines.length;
            matchPercent = totalInstrLines > 0 ? (matchingLines / totalInstrLines) * 100 : 0;
        }

        // Extract branch arrows from the aligned lines
        const targetInstrs = diffLines.map(d => d.targetParsed || null);
        const currentInstrs = diffLines.map(d => d.currentParsed || null);
        const targetArrows = extractBranchArrows(targetInstrs, 'target');
        const currentArrows = extractBranchArrows(currentInstrs, 'current');

        return {
            functionName,
            match: isMatch,
            matchPercent,
            targetLines,
            currentLines: currentLines_,
            diffLines,
            targetArrows,
            currentArrows
        };
    }


    async getReport(): Promise<Report> {
        const reportPath = path.join(this.workspaceRoot, 'build', 'GALE01', 'report.json');
        console.log(`DiffProvider.getReport: Loading from ${reportPath}`);

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
            console.error(`DiffProvider.getReport: Failed to read ${reportPath}:`, e);
            throw new Error(`Failed to read report.json: ${e}`);
        }
    }

    /**
     * Invalidate the cached report data, forcing a reload on next access.
     */
    invalidateCache(): void {
        this.reportCache = null;
        this.reportMtime = 0;
    }

    async getFunctionsInFile(filePath: string): Promise<ReportFunction[]> {
        const report = await this.getReport();
        const relativePath = path.relative(this.workspaceRoot, filePath);

        // Find unit matching this file
        for (const unit of report.units) {
            const unitSourcePath = unit.metadata?.source_path;
            if (unitSourcePath && relativePath.endsWith(unitSourcePath.replace('src/', ''))) {
                return unit.functions || [];
            }

            // Also check by unit name
            const unitPath = unit.name.replace('main/', '');
            if (relativePath.includes(unitPath)) {
                return unit.functions || [];
            }
        }

        return [];
    }

    async getFunctionMatchPercent(functionName: string): Promise<number | undefined> {
        const report = await this.getReport();

        for (const unit of report.units) {
            if (!unit.functions) continue;
            for (const func of unit.functions) {
                if (func.name === functionName) {
                    return func.fuzzy_match_percent;
                }
            }
        }

        return undefined;
    }
}
