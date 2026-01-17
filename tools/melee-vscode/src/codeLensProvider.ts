import * as vscode from 'vscode';
import { DiffProvider } from './diffProvider';

export class CodeLensProvider implements vscode.CodeLensProvider {
    private _onDidChangeCodeLenses: vscode.EventEmitter<void> = new vscode.EventEmitter<void>();
    public readonly onDidChangeCodeLenses: vscode.Event<void> = this._onDidChangeCodeLenses.event;

    private diffProvider: DiffProvider;
    private functionCache: Map<string, number | undefined> = new Map();

    constructor(diffProvider: DiffProvider) {
        this.diffProvider = diffProvider;

        // Refresh CodeLenses when files change
        vscode.workspace.onDidSaveTextDocument(() => {
            this.functionCache.clear();
            this._onDidChangeCodeLenses.fire();
        });
    }

    async provideCodeLenses(
        document: vscode.TextDocument,
        token: vscode.CancellationToken
    ): Promise<vscode.CodeLens[]> {
        if (document.languageId !== 'c') {
            return [];
        }

        const codeLenses: vscode.CodeLens[] = [];
        const text = document.getText();

        // Pattern to match function definitions
        // Handles: void func(args) { or static s32 func(void) or asm func(...) {
        const funcPattern = /^(?:asm\s+)?(?:static\s+)?(?:inline\s+)?(?:\w+\s+\*?\s*)+(\w+)\s*\([^)]*\)\s*\{?$/gm;

        let match;
        while ((match = funcPattern.exec(text)) !== null) {
            if (token.isCancellationRequested) {
                break;
            }

            const funcName = match[1];

            // Skip common non-function patterns
            if (funcName === 'if' || funcName === 'while' || funcName === 'for' || funcName === 'switch') {
                continue;
            }

            const position = document.positionAt(match.index);
            const range = new vscode.Range(position, position);

            // Try to get match percentage (async, but we'll show without it if not cached)
            let matchPercent: number | undefined;
            if (this.functionCache.has(funcName)) {
                matchPercent = this.functionCache.get(funcName);
            } else {
                // Don't await here to keep CodeLens fast - fetch in background
                this.diffProvider.getFunctionMatchPercent(funcName).then(pct => {
                    if (pct !== undefined) {
                        this.functionCache.set(funcName, pct);
                        this._onDidChangeCodeLenses.fire();
                    }
                }).catch(() => {
                    // Function not in report, ignore
                });
            }

            const title = matchPercent !== undefined
                ? `Show ASM Diff (${matchPercent.toFixed(0)}%)`
                : 'Show ASM Diff';

            const lens = new vscode.CodeLens(range, {
                title,
                command: 'meleeDecomp.showDiffForFunction',
                arguments: [funcName]
            });

            codeLenses.push(lens);
        }

        return codeLenses;
    }
}
