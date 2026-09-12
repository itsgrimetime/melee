import * as vscode from 'vscode';
import { DiffProvider } from './diffProvider';

export class DecorationProvider implements vscode.Disposable {
    private diffProvider: DiffProvider;

    // Four decoration types for different match levels
    private matchedDecoration: vscode.TextEditorDecorationType;
    private closeDecoration: vscode.TextEditorDecorationType;
    private unmatchedDecoration: vscode.TextEditorDecorationType;
    private unknownDecoration: vscode.TextEditorDecorationType;

    // Debounce timer
    private updateTimer: NodeJS.Timeout | undefined;
    private static readonly DEBOUNCE_MS = 300;

    // Live match overrides from checkdiff results (more up-to-date than report.json)
    private liveMatchOverrides: Map<string, number> = new Map();

    constructor(diffProvider: DiffProvider) {
        this.diffProvider = diffProvider;

        // Green badge for 100% match
        this.matchedDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 4px',
                backgroundColor: 'rgba(40, 167, 69, 0.3)',
                color: new vscode.ThemeColor('terminal.ansiGreen'),
                border: '1px solid rgba(40, 167, 69, 0.5)'
            }
        });

        // Yellow badge for 95-99% match
        this.closeDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 4px',
                backgroundColor: 'rgba(255, 193, 7, 0.3)',
                color: new vscode.ThemeColor('terminal.ansiYellow'),
                border: '1px solid rgba(255, 193, 7, 0.5)'
            }
        });

        // Red badge for <95% match
        this.unmatchedDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 4px',
                backgroundColor: 'rgba(220, 53, 69, 0.3)',
                color: new vscode.ThemeColor('terminal.ansiRed'),
                border: '1px solid rgba(220, 53, 69, 0.5)'
            }
        });

        // Gray badge for unknown (no data)
        this.unknownDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 4px',
                backgroundColor: 'rgba(128, 128, 128, 0.2)',
                color: new vscode.ThemeColor('descriptionForeground'),
                border: '1px solid rgba(128, 128, 128, 0.3)'
            }
        });
    }

    /**
     * Trigger a debounced decoration update for the given editor.
     */
    triggerUpdate(editor: vscode.TextEditor): void {
        if (this.updateTimer) {
            clearTimeout(this.updateTimer);
        }
        this.updateTimer = setTimeout(() => {
            this.updateDecorations(editor);
        }, DecorationProvider.DEBOUNCE_MS);
    }

    /**
     * Update decorations for all visible C editors.
     */
    updateAllVisibleEditors(): void {
        for (const editor of vscode.window.visibleTextEditors) {
            if (editor.document.languageId === 'c') {
                this.triggerUpdate(editor);
            }
        }
    }

    /**
     * Set a live match percentage override for a function (from checkdiff results).
     * This takes precedence over report.json data until cleared.
     */
    setLiveMatch(functionName: string, matchPercent: number): void {
        this.liveMatchOverrides.set(functionName, matchPercent);
        this.updateAllVisibleEditors();
    }

    /**
     * Clear live overrides (e.g., when report.json is updated).
     */
    clearLiveOverrides(): void {
        this.liveMatchOverrides.clear();
    }

    /**
     * Update decorations for the given editor.
     */
    async updateDecorations(editor: vscode.TextEditor): Promise<void> {
        console.log(`DecorationProvider.updateDecorations: Called for ${editor.document.fileName}, language=${editor.document.languageId}`);

        if (editor.document.languageId !== 'c') {
            console.log('DecorationProvider.updateDecorations: Skipping non-C file');
            return;
        }

        const text = editor.document.getText();

        // Same regex as codeLensProvider.ts
        const funcPattern = /^(?:asm\s+)?(?:static\s+)?(?:inline\s+)?(?:\w+\s+\*?\s*)+(\w+)\s*\([^)]*\)\s*\{?$/gm;

        // Arrays for each decoration level
        const matchedDecos: vscode.DecorationOptions[] = [];
        const closeDecos: vscode.DecorationOptions[] = [];
        const unmatchedDecos: vscode.DecorationOptions[] = [];
        const unknownDecos: vscode.DecorationOptions[] = [];

        interface FunctionInfo {
            name: string;
            range: vscode.Range;
        }

        const functions: FunctionInfo[] = [];
        let match;

        while ((match = funcPattern.exec(text)) !== null) {
            const funcName = match[1];

            // Skip control flow keywords that might match the pattern
            if (['if', 'while', 'for', 'switch', 'return'].includes(funcName)) {
                continue;
            }

            const matchStart = editor.document.positionAt(match.index);
            const line = editor.document.lineAt(matchStart.line);

            // Position the badge at the end of the line
            const lineEnd = new vscode.Position(matchStart.line, line.text.length);
            const range = new vscode.Range(lineEnd, lineEnd);

            functions.push({ name: funcName, range });
        }

        // Fetch all match percentages in parallel
        const percentages = await Promise.all(
            functions.map(f =>
                this.diffProvider.getFunctionMatchPercent(f.name)
                    .catch((err) => {
                        console.error(`DecorationProvider: Error getting match for ${f.name}:`, err);
                        return undefined;
                    })
            )
        );

        // Debug: log first few results
        if (functions.length > 0) {
            console.log(`DecorationProvider: Found ${functions.length} functions, first few: ${functions.slice(0, 3).map((f, i) => `${f.name}=${percentages[i]}`).join(', ')}`)
        }

        // Categorize by match level
        for (let i = 0; i < functions.length; i++) {
            const func = functions[i];
            // Use live override if available, otherwise use report.json data
            const percent = this.liveMatchOverrides.get(func.name) ?? percentages[i];

            const decoOption: vscode.DecorationOptions = {
                range: func.range,
                renderOptions: {
                    after: {
                        contentText: percent !== undefined
                            ? `[${percent.toFixed(0)}%]`
                            : '[?]',
                    }
                }
            };

            if (percent === undefined) {
                unknownDecos.push(decoOption);
            } else if (percent >= 100) {
                matchedDecos.push(decoOption);
            } else if (percent >= 95) {
                closeDecos.push(decoOption);
            } else {
                unmatchedDecos.push(decoOption);
            }
        }

        // Apply all decorations
        editor.setDecorations(this.matchedDecoration, matchedDecos);
        editor.setDecorations(this.closeDecoration, closeDecos);
        editor.setDecorations(this.unmatchedDecoration, unmatchedDecos);
        editor.setDecorations(this.unknownDecoration, unknownDecos);

        console.log(`DecorationProvider.updateDecorations: Applied ${matchedDecos.length} matched, ${closeDecos.length} close, ${unmatchedDecos.length} unmatched, ${unknownDecos.length} unknown`);
    }

    dispose(): void {
        if (this.updateTimer) {
            clearTimeout(this.updateTimer);
        }
        this.matchedDecoration.dispose();
        this.closeDecoration.dispose();
        this.unmatchedDecoration.dispose();
        this.unknownDecoration.dispose();
    }
}
