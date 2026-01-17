import * as vscode from 'vscode';
import { DiffProvider } from './diffProvider';
import { DiffPanel } from './webviewPanel';
import { CodeLensProvider } from './codeLensProvider';

let diffProvider: DiffProvider;

export function activate(context: vscode.ExtensionContext) {
    console.log('Melee Decomp Diff extension activated');

    // Find workspace root (should contain objdiff.json)
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
        vscode.window.showErrorMessage('No workspace folder found');
        return;
    }

    diffProvider = new DiffProvider(workspaceRoot);

    // Command: Show diff for function at cursor or prompt
    const showDiffCommand = vscode.commands.registerCommand('meleeDecomp.showDiff', async () => {
        const editor = vscode.window.activeTextEditor;

        // Try to detect function name from cursor position
        let functionName: string | undefined;
        if (editor && editor.document.languageId === 'c') {
            functionName = detectFunctionAtCursor(editor);
        }

        // If not found, prompt user
        if (!functionName) {
            functionName = await vscode.window.showInputBox({
                prompt: 'Enter function name',
                placeHolder: 'e.g., ftCo_800BF7DC'
            });
        }

        if (!functionName) {
            return;
        }

        await showDiffForFunction(functionName, context);
    });

    // Command: Show diff for specific function (used by CodeLens)
    const showDiffForFunctionCommand = vscode.commands.registerCommand(
        'meleeDecomp.showDiffForFunction',
        async (functionName: string) => {
            await showDiffForFunction(functionName, context);
        }
    );

    // Register CodeLens provider for C files
    const codeLensProvider = new CodeLensProvider(diffProvider);
    const codeLensDisposable = vscode.languages.registerCodeLensProvider(
        { language: 'c', scheme: 'file' },
        codeLensProvider
    );

    // Watch for file saves to refresh diff
    const saveWatcher = vscode.workspace.onDidSaveTextDocument(async (doc) => {
        if (doc.languageId === 'c' && DiffPanel.currentPanel) {
            // Re-run diff for current function
            const currentFunc = DiffPanel.currentPanel.currentFunction;
            if (currentFunc) {
                await showDiffForFunction(currentFunc, context);
            }
        }
    });

    context.subscriptions.push(
        showDiffCommand,
        showDiffForFunctionCommand,
        codeLensDisposable,
        saveWatcher
    );
}

async function showDiffForFunction(functionName: string, context: vscode.ExtensionContext) {
    try {
        // Show loading state
        DiffPanel.createOrShow(context.extensionUri);
        DiffPanel.currentPanel?.setLoading(functionName);

        // Get diff data
        const diffResult = await diffProvider.getDiff(functionName);

        // Update panel
        DiffPanel.currentPanel?.updateDiff(diffResult);
    } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`Failed to get diff: ${message}`);
        DiffPanel.currentPanel?.setError(message);
    }
}

function detectFunctionAtCursor(editor: vscode.TextEditor): string | undefined {
    const document = editor.document;
    const position = editor.selection.active;

    // Look for function definition pattern around cursor
    // Patterns like: void funcName(args) { or static s32 funcName(void)
    const funcPattern = /^(?:static\s+)?(?:\w+\s+\*?\s*)+(\w+)\s*\([^)]*\)\s*\{?$/;

    // Check current line and a few lines above
    for (let lineNum = position.line; lineNum >= Math.max(0, position.line - 5); lineNum--) {
        const line = document.lineAt(lineNum).text;
        const match = funcPattern.exec(line);
        if (match) {
            return match[1];
        }
    }

    // Also check if cursor is on a function name
    const wordRange = document.getWordRangeAtPosition(position);
    if (wordRange) {
        const word = document.getText(wordRange);
        // Check if it looks like a function name (starts with letter, contains underscore or hex-like suffix)
        if (/^[a-zA-Z_]\w*$/.test(word)) {
            return word;
        }
    }

    return undefined;
}

export function deactivate() {
    // Cleanup
}
