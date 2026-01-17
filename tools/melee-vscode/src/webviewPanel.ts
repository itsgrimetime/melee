import * as vscode from 'vscode';
import { DiffResult, DiffLine } from './diffProvider';

export class DiffPanel {
    public static currentPanel: DiffPanel | undefined;
    private static readonly viewType = 'meleeDecompDiff';

    private readonly _panel: vscode.WebviewPanel;
    private readonly _extensionUri: vscode.Uri;
    private _currentFunction: string | undefined;
    private _disposables: vscode.Disposable[] = [];

    public get currentFunction(): string | undefined {
        return this._currentFunction;
    }

    public static createOrShow(extensionUri: vscode.Uri) {
        const column = vscode.ViewColumn.Beside;

        if (DiffPanel.currentPanel) {
            DiffPanel.currentPanel._panel.reveal(column);
            return;
        }

        const panel = vscode.window.createWebviewPanel(
            DiffPanel.viewType,
            'ASM Diff',
            column,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [extensionUri]
            }
        );

        DiffPanel.currentPanel = new DiffPanel(panel, extensionUri);
    }

    private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
        this._panel = panel;
        this._extensionUri = extensionUri;

        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

        // Handle messages from webview
        this._panel.webview.onDidReceiveMessage(
            message => {
                switch (message.command) {
                    case 'copy':
                        vscode.env.clipboard.writeText(message.text);
                        vscode.window.showInformationMessage('Copied to clipboard');
                        return;
                }
            },
            null,
            this._disposables
        );

        this._panel.webview.html = this._getLoadingHtml();
    }

    public setLoading(functionName: string) {
        this._currentFunction = functionName;
        this._panel.title = `ASM Diff: ${functionName}`;
        this._panel.webview.html = this._getLoadingHtml(functionName);
    }

    public setError(message: string) {
        this._panel.webview.html = this._getErrorHtml(message);
    }

    public updateDiff(result: DiffResult) {
        this._currentFunction = result.functionName;
        this._panel.title = `ASM Diff: ${result.functionName} (${result.matchPercent}%)`;
        this._panel.webview.html = this._getDiffHtml(result);
    }

    private _getLoadingHtml(functionName?: string): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Loading...</title>
    ${this._getStyles()}
</head>
<body>
    <div class="loading">
        <div class="spinner"></div>
        <p>Building and diffing${functionName ? ` ${functionName}` : ''}...</p>
    </div>
</body>
</html>`;
    }

    private _getErrorHtml(message: string): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Error</title>
    ${this._getStyles()}
</head>
<body>
    <div class="error">
        <h2>Error</h2>
        <pre>${this._escapeHtml(message)}</pre>
    </div>
</body>
</html>`;
    }

    private _getDiffHtml(result: DiffResult): string {
        const statusClass = result.match ? 'match' : 'mismatch';
        const statusText = result.match ? 'MATCH' : 'MISMATCH';

        const rowsHtml = result.diffLines.map((line, idx) => this._renderDiffRow(line, idx)).join('\n');

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ASM Diff: ${result.functionName}</title>
    ${this._getStyles()}
</head>
<body>
    <div class="header">
        <div class="function-name">${this._escapeHtml(result.functionName)}</div>
        <div class="status ${statusClass}">
            ${statusText} - ${result.matchPercent}%
        </div>
    </div>
    <div class="diff-container">
        <div class="column-headers">
            <div class="col-header target-header">Target (Expected)</div>
            <div class="col-header current-header">Current (Compiled)</div>
        </div>
        <div class="diff-rows">
            ${rowsHtml}
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();

        document.querySelectorAll('.diff-row').forEach(row => {
            row.addEventListener('click', () => {
                const target = row.querySelector('.target-col')?.textContent || '';
                const current = row.querySelector('.current-col')?.textContent || '';
                const text = target || current;
                if (text.trim()) {
                    vscode.postMessage({ command: 'copy', text: text.trim() });
                }
            });
        });

        // Sync scroll between columns
        const container = document.querySelector('.diff-rows');
        if (container) {
            container.addEventListener('scroll', (e) => {
                // Scroll sync is handled by CSS (single scrollable container)
            });
        }
    </script>
</body>
</html>`;
    }

    private _renderDiffRow(line: DiffLine, index: number): string {
        const statusClass = line.status;
        const lineNum = index + 1;

        // Highlight instruction parts
        const targetHtml = this._highlightAsm(line.target);
        const currentHtml = this._highlightAsm(line.current);

        return `<div class="diff-row ${statusClass}" data-line="${lineNum}">
    <div class="line-num">${lineNum}</div>
    <div class="target-col">${targetHtml}</div>
    <div class="current-col">${currentHtml}</div>
</div>`;
    }

    private _highlightAsm(asm: string): string {
        if (!asm) return '&nbsp;';

        let html = this._escapeHtml(asm);

        // Highlight registers (r0-r31, f0-f31, sp, lr, cr0-cr7)
        html = html.replace(/\b(r\d{1,2}|f\d{1,2}|sp|lr|cr\d?)\b/g,
            '<span class="register">$1</span>');

        // Highlight hex numbers
        html = html.replace(/\b(0x[0-9a-fA-F]+|-?0x[0-9a-fA-F]+)\b/g,
            '<span class="hex">$1</span>');

        // Highlight decimal numbers (but not in register names)
        html = html.replace(/(?<![rf])\b(-?\d+)\b(?!\s*[:\(])/g,
            '<span class="number">$1</span>');

        // Highlight instruction mnemonics (first word on the line)
        html = html.replace(/^(\s*)(\w+)/, '$1<span class="mnemonic">$2</span>');

        // Highlight labels/symbols
        html = html.replace(/(<[^>]+>)/g, '<span class="label">$1</span>');

        return html;
    }

    private _escapeHtml(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    private _getStyles(): string {
        return `<style>
:root {
    --bg-color: var(--vscode-editor-background);
    --fg-color: var(--vscode-editor-foreground);
    --border-color: var(--vscode-panel-border);
    --match-bg: rgba(40, 167, 69, 0.15);
    --mismatch-bg: rgba(220, 53, 69, 0.15);
    --target-only-bg: rgba(220, 53, 69, 0.25);
    --current-only-bg: rgba(255, 193, 7, 0.25);
    --header-bg: var(--vscode-sideBarSectionHeader-background);
    --hover-bg: var(--vscode-list-hoverBackground);
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    background: var(--bg-color);
    color: var(--fg-color);
    font-family: var(--vscode-editor-font-family), monospace;
    font-size: var(--vscode-editor-font-size, 13px);
    line-height: 1.4;
    overflow: hidden;
    height: 100vh;
    display: flex;
    flex-direction: column;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    background: var(--header-bg);
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
}

.function-name {
    font-weight: bold;
    font-size: 14px;
}

.status {
    padding: 4px 12px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 12px;
}

.status.match {
    background: rgba(40, 167, 69, 0.3);
    color: #28a745;
}

.status.mismatch {
    background: rgba(220, 53, 69, 0.3);
    color: #dc3545;
}

.diff-container {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.column-headers {
    display: flex;
    border-bottom: 1px solid var(--border-color);
    flex-shrink: 0;
}

.col-header {
    flex: 1;
    padding: 6px 12px;
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    background: var(--header-bg);
}

.col-header:first-child {
    margin-left: 40px; /* Space for line numbers */
}

.col-header.target-header {
    border-right: 1px solid var(--border-color);
}

.diff-rows {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
}

.diff-row {
    display: flex;
    border-bottom: 1px solid rgba(128, 128, 128, 0.1);
    cursor: pointer;
    min-height: 20px;
}

.diff-row:hover {
    background: var(--hover-bg) !important;
}

.diff-row.match {
    background: var(--match-bg);
}

.diff-row.mismatch {
    background: var(--mismatch-bg);
}

.diff-row.target-only {
    background: var(--target-only-bg);
}

.diff-row.current-only {
    background: var(--current-only-bg);
}

.line-num {
    width: 40px;
    text-align: right;
    padding: 2px 8px;
    color: var(--vscode-editorLineNumber-foreground);
    user-select: none;
    flex-shrink: 0;
    font-size: 11px;
}

.target-col, .current-col {
    flex: 1;
    padding: 2px 8px;
    white-space: pre;
    overflow: hidden;
    text-overflow: ellipsis;
}

.target-col {
    border-right: 1px solid var(--border-color);
}

/* Syntax highlighting */
.register {
    color: var(--vscode-symbolIcon-variableForeground, #9cdcfe);
}

.hex, .number {
    color: var(--vscode-symbolIcon-constantForeground, #b5cea8);
}

.mnemonic {
    color: var(--vscode-symbolIcon-keywordForeground, #569cd6);
}

.label {
    color: var(--vscode-symbolIcon-functionForeground, #dcdcaa);
}

/* Loading state */
.loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: 16px;
}

.spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--border-color);
    border-top-color: var(--vscode-progressBar-background);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Error state */
.error {
    padding: 20px;
}

.error h2 {
    color: #dc3545;
    margin-bottom: 12px;
}

.error pre {
    background: rgba(220, 53, 69, 0.1);
    padding: 12px;
    border-radius: 4px;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
}
</style>`;
    }

    public dispose() {
        DiffPanel.currentPanel = undefined;

        this._panel.dispose();

        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
}
