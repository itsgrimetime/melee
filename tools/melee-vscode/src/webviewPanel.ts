import * as vscode from 'vscode';
import { DiffResult, DiffLine } from './diffProvider';
import { BranchArrow } from './asmParser';
import { ppcInstructions } from './ppcReference';

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
        // Send message to show loading overlay instead of replacing content
        this._panel.webview.postMessage({ command: 'showLoading', functionName });
    }

    public setError(message: string) {
        this._panel.webview.html = this._getErrorHtml(message);
    }

    public updateDiff(result: DiffResult) {
        this._currentFunction = result.functionName;
        this._panel.title = `ASM Diff: ${result.functionName} (${result.matchPercent}%)`;
        this._panel.webview.html = this._getDiffHtml(result);
    }

    public navigateDiff(direction: 'next' | 'prev') {
        this._panel.webview.postMessage({ command: 'navigate', direction });
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

        const rowsHtml = result.diffLines.map((line, idx) => this._renderDiffRow(line, idx, idx === 0)).join('\n');

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
            <div class="col-header line-num-header"></div>
            <div class="col-header marker-header"></div>
            <div class="col-header arrow-header"></div>
            <div class="col-header target-header">Target (Expected)</div>
            <div class="col-header arrow-header"></div>
            <div class="col-header current-header">Current (Compiled)</div>
        </div>
        <div id="loading-overlay" class="loading-overlay" style="display: none;">
            <div class="spinner"></div>
            <span>Rebuilding...</span>
        </div>
        <div class="diff-rows">
            ${rowsHtml}
        </div>
        <svg id="target-arrows" class="arrow-overlay target-side"></svg>
        <svg id="current-arrows" class="arrow-overlay current-side"></svg>
    </div>
    <script>
        const targetArrows = ${JSON.stringify(result.targetArrows || [])};
        const currentArrows = ${JSON.stringify(result.currentArrows || [])};

        function renderArrows() {
            renderArrowSet('target-arrows', targetArrows, 'target-gutter');
            renderArrowSet('current-arrows', currentArrows, 'current-gutter');
        }

        function renderArrowSet(svgId, arrows, gutterClass) {
            const svg = document.getElementById(svgId);
            if (!svg || arrows.length === 0) return;

            const rows = document.querySelectorAll('.diff-rows .diff-row');
            if (rows.length === 0) return;

            const diffRows = document.querySelector('.diff-rows');
            const diffContainer = document.querySelector('.diff-container');
            const rowHeight = rows[0].offsetHeight || 20;

            // Find the first gutter element to get its position
            const firstGutter = rows[0].querySelector('.' + gutterClass);
            if (!firstGutter) return;

            const gutterRect = firstGutter.getBoundingClientRect();
            const containerRect = diffContainer.getBoundingClientRect();
            const diffRowsRect = diffRows.getBoundingClientRect();

            // Position SVG over the gutter column, accounting for headers above diff-rows
            const gutterLeft = gutterRect.left - containerRect.left;
            const topOffset = diffRowsRect.top - containerRect.top;
            const gutterWidth = 40;  // Arrow gutter width

            svg.style.left = gutterLeft + 'px';
            svg.style.top = topOffset + 'px';
            svg.setAttribute('width', gutterWidth);
            svg.setAttribute('height', diffRows.scrollHeight);
            svg.innerHTML = '';

            // Assign lanes to arrows to avoid overlaps
            const lanes = assignLanes(arrows);
            const laneWidth = 6;
            const maxLane = Math.max(...Object.values(lanes), 0);

            arrows.forEach((arrow, idx) => {
                const lane = lanes[idx];
                const laneX = gutterWidth - 10 - lane * laneWidth;  // Lane position

                // Center vertically in row, with small adjustment for padding/borders
                const yOffset = -1;  // Nudge up slightly to better center
                const fromY = (arrow.fromRow * rowHeight) + rowHeight / 2 + yOffset;
                const toY = (arrow.toRow * rowHeight) + rowHeight / 2 + yOffset;

                // Color based on type
                let color = '#888';
                if (arrow.direction === 'backward') {
                    color = '#f14c4c';  // red for backward (loops)
                } else if (arrow.type === 'unconditional') {
                    color = '#569cd6';  // blue for unconditional
                } else {
                    color = '#dcdcaa';  // yellow for conditional
                }

                // Draw the arrow as a bracket shape
                // Start at source row near code, go to lane, vertical to target, back to code
                const codeEdge = gutterWidth - 2;  // Right edge near code

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');

                // Path: source -> lane -> target -> code edge (with arrowhead)
                // The final segment goes right to ensure arrowhead points toward code
                const d = \`M \${codeEdge} \${fromY} H \${laneX} V \${toY} H \${codeEdge}\`;

                path.setAttribute('d', d);
                path.setAttribute('stroke', color);
                path.setAttribute('stroke-width', '1.5');
                path.setAttribute('fill', 'none');
                path.setAttribute('marker-end', \`url(#arrow-\${color.replace('#', '')})\`);
                svg.appendChild(path);

                // Draw a small tick at the source row to indicate where the branch is
                const tick = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                tick.setAttribute('cx', codeEdge);
                tick.setAttribute('cy', fromY);
                tick.setAttribute('r', '2');
                tick.setAttribute('fill', color);
                svg.appendChild(tick);
            });

            // Add arrow markers
            addArrowMarkers(svg);
        }

        function assignLanes(arrows) {
            // Simple lane assignment - arrows that overlap get different lanes
            const lanes = {};
            const usedRanges = [];  // Array of {lane, min, max}

            // Sort by span length (shorter arrows get inner lanes)
            const sorted = arrows.map((a, i) => ({
                idx: i,
                span: Math.abs(a.toRow - a.fromRow)
            })).sort((a, b) => a.span - b.span);

            sorted.forEach(({ idx }) => {
                const arrow = arrows[idx];
                const min = Math.min(arrow.fromRow, arrow.toRow);
                const max = Math.max(arrow.fromRow, arrow.toRow);

                // Find a lane that doesn't overlap
                let lane = 0;
                while (true) {
                    const conflict = usedRanges.find(r =>
                        r.lane === lane && !(max < r.min || min > r.max)
                    );
                    if (!conflict) break;
                    lane++;
                }

                lanes[idx] = lane;
                usedRanges.push({ lane, min, max });
            });

            return lanes;
        }

        function addArrowMarkers(svg) {
            const colors = ['888', 'f14c4c', '4ec9b0', '569cd6', 'dcdcaa'];
            const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

            colors.forEach(color => {
                const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                marker.setAttribute('id', \`arrow-\${color}\`);
                marker.setAttribute('markerWidth', '5');
                marker.setAttribute('markerHeight', '5');
                marker.setAttribute('refX', '4');
                marker.setAttribute('refY', '2.5');
                marker.setAttribute('orient', 'auto');

                const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                polygon.setAttribute('points', '0,0 5,2.5 0,5');
                polygon.setAttribute('fill', \`#\${color}\`);
                marker.appendChild(polygon);
                defs.appendChild(marker);
            });

            svg.insertBefore(defs, svg.firstChild);
        }

        // Render arrows after DOM is ready
        setTimeout(renderArrows, 100);

        // Re-render on window resize
        window.addEventListener('resize', () => setTimeout(renderArrows, 50));

        // Handle scroll sync for arrows
        document.querySelector('.diff-rows')?.addEventListener('scroll', () => {
            const targetSvg = document.getElementById('target-arrows');
            const currentSvg = document.getElementById('current-arrows');
            const scrollTop = document.querySelector('.diff-rows').scrollTop;
            if (targetSvg) targetSvg.style.transform = \`translateY(-\${scrollTop}px)\`;
            if (currentSvg) currentSvg.style.transform = \`translateY(-\${scrollTop}px)\`;
        });
    </script>
    <script>
        const vscode = acquireVsCodeApi();
        let currentDiffIndex = -1;
        const diffRows = Array.from(document.querySelectorAll('.diff-row.mismatch, .diff-row.target-only, .diff-row.current-only'));

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

        // Handle messages from extension
        window.addEventListener('message', event => {
            const message = event.data;
            if (message.command === 'navigate') {
                navigateToDiff(message.direction);
            } else if (message.command === 'showLoading') {
                const overlay = document.getElementById('loading-overlay');
                if (overlay) {
                    overlay.style.display = 'flex';
                }
            } else if (message.command === 'hideLoading') {
                const overlay = document.getElementById('loading-overlay');
                if (overlay) {
                    overlay.style.display = 'none';
                }
            }
        });

        function navigateToDiff(direction) {
            if (diffRows.length === 0) return;

            // Remove highlight from current
            if (currentDiffIndex >= 0 && currentDiffIndex < diffRows.length) {
                diffRows[currentDiffIndex].classList.remove('highlighted');
            }

            // Move to next/prev
            if (direction === 'next') {
                currentDiffIndex = (currentDiffIndex + 1) % diffRows.length;
            } else {
                currentDiffIndex = currentDiffIndex <= 0 ? diffRows.length - 1 : currentDiffIndex - 1;
            }

            // Highlight and scroll to new position
            const row = diffRows[currentDiffIndex];
            row.classList.add('highlighted');
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'n' || e.key === 'j') {
                navigateToDiff('next');
            } else if (e.key === 'p' || e.key === 'k') {
                navigateToDiff('prev');
            }
        });
    </script>
    <div id="instruction-tooltip" class="instruction-tooltip"></div>
    <script>
        // PPC Instruction Reference
        const ppcRef = ${JSON.stringify(ppcInstructions)};

        let tooltipTimeout = null;

        // Extract mnemonic from ASM text
        function extractMnemonic(text) {
            if (!text) return null;
            const trimmed = text.trim();
            // Skip labels
            if (trimmed.startsWith('<') || trimmed.startsWith('R_')) return null;
            // First word is the mnemonic
            const match = trimmed.match(/^(\\S+)/);
            if (match) {
                // Remove trailing . or other suffixes for lookup
                return match[1].toLowerCase().replace(/\\.$/, '');
            }
            return null;
        }

        // Show tooltip for instruction
        function showTooltip(element, mnemonic) {
            const tooltip = document.getElementById('instruction-tooltip');
            const info = ppcRef[mnemonic] || ppcRef[mnemonic.replace(/[+-]$/, '')];
            if (!info || !tooltip) return;

            // Build tooltip content
            let html = \`
                <div class="tooltip-header">
                    <span class="tooltip-mnemonic">\${info.mnemonic}</span>
                    <span class="tooltip-name">\${info.name}</span>
                </div>
                <div class="tooltip-syntax">\${info.syntax}</div>
                <div class="tooltip-desc">\${info.description}</div>
            \`;

            if (info.operation) {
                html += \`<div class="tooltip-operation"><code>\${info.operation}</code></div>\`;
            }

            if (info.flags) {
                html += \`<div class="tooltip-flags">Flags: \${info.flags}</div>\`;
            }

            html += \`<div class="tooltip-category">\${info.category}</div>\`;

            tooltip.innerHTML = html;
            tooltip.style.display = 'block';

            // Position tooltip near element
            const rect = element.getBoundingClientRect();
            const containerRect = document.body.getBoundingClientRect();

            let left = rect.left + 10;
            let top = rect.bottom + 5;

            // Keep tooltip in view
            if (left + 350 > containerRect.right) {
                left = containerRect.right - 360;
            }
            if (top + 200 > containerRect.bottom) {
                top = rect.top - 200;
            }

            tooltip.style.left = left + 'px';
            tooltip.style.top = top + 'px';
        }

        let hideTimeout = null;
        let isOverTooltip = false;

        function hideTooltip() {
            const tooltip = document.getElementById('instruction-tooltip');
            if (tooltip) tooltip.style.display = 'none';
        }

        function scheduleHide() {
            // Don't hide if mouse is over tooltip
            if (isOverTooltip) return;

            hideTimeout = setTimeout(() => {
                if (!isOverTooltip) {
                    hideTooltip();
                }
            }, 100);
        }

        function cancelHide() {
            if (hideTimeout) {
                clearTimeout(hideTimeout);
                hideTimeout = null;
            }
        }

        // Keep tooltip visible when hovering over it
        const tooltipEl = document.getElementById('instruction-tooltip');
        if (tooltipEl) {
            tooltipEl.addEventListener('mouseenter', () => {
                isOverTooltip = true;
                cancelHide();
            });
            tooltipEl.addEventListener('mouseleave', () => {
                isOverTooltip = false;
                scheduleHide();
            });
        }

        // Add hover listeners to ASM columns
        document.querySelectorAll('.target-col, .current-col').forEach(col => {
            col.addEventListener('mouseenter', (e) => {
                cancelHide();
                if (tooltipTimeout) {
                    clearTimeout(tooltipTimeout);
                }
                const text = col.textContent;
                const mnemonic = extractMnemonic(text);
                if (mnemonic) {
                    tooltipTimeout = setTimeout(() => {
                        showTooltip(col, mnemonic);
                    }, 400);  // Delay before showing
                }
            });

            col.addEventListener('mouseleave', () => {
                if (tooltipTimeout) {
                    clearTimeout(tooltipTimeout);
                    tooltipTimeout = null;
                }
                scheduleHide();
            });
        });
    </script>
</body>
</html>`;
    }

    private _renderDiffRow(line: DiffLine, index: number, isHeader: boolean): string {
        const statusClass = line.status;
        const diffTypeClass = line.diffType ? `diff-${line.diffType}` : '';

        // Function header row (starts with <)
        if (isHeader || line.target.trim().startsWith('<') || line.current.trim().startsWith('<')) {
            const headerText = line.target.trim() || line.current.trim();
            return `<div class="diff-row header-row" data-offset="-1">
    <div class="line-num"></div>
    <div class="marker-col"></div>
    <div class="arrow-gutter target-gutter"></div>
    <div class="target-col">${this._escapeHtml(headerText)}</div>
    <div class="arrow-gutter current-gutter"></div>
    <div class="current-col">${this._escapeHtml(headerText)}</div>
</div>`;
        }

        // Calculate byte offset (each instruction is 4 bytes, skip header row)
        const offset = (index - 1) * 4;  // -1 to account for header
        const offsetHex = offset >= 0 ? `0x${offset.toString(16).toUpperCase().padStart(2, '0')}` : '';

        // Get diff marker
        let marker = '';
        if (line.status === 'target-only') {
            marker = '<span class="diff-marker marker-target">&gt;</span>';
        } else if (line.status === 'current-only') {
            marker = '<span class="diff-marker marker-current">&lt;</span>';
        } else if (line.status === 'mismatch') {
            switch (line.diffType) {
                case 'r': marker = '<span class="diff-marker marker-reg">r</span>'; break;
                case 'i': marker = '<span class="diff-marker marker-imm">i</span>'; break;
                case 'o': marker = '<span class="diff-marker marker-op">o</span>'; break;
                case 's': marker = '<span class="diff-marker marker-stack">s</span>'; break;
                default: marker = '<span class="diff-marker marker-diff">|</span>';
            }
        }

        // Strip hex bytes and show only mnemonic + operands
        const targetAsm = this._stripHexBytes(line.target);
        const currentAsm = this._stripHexBytes(line.current);

        // Highlight with mismatch info
        const targetHtml = this._highlightAsmWithDiff(targetAsm, line.targetParsed, line.mismatchedParts, 'target');
        const currentHtml = this._highlightAsmWithDiff(currentAsm, line.currentParsed, line.mismatchedParts, 'current');

        return `<div class="diff-row ${statusClass} ${diffTypeClass}" data-offset="${offset}">
    <div class="line-num">${offsetHex}</div>
    <div class="marker-col">${marker}</div>
    <div class="arrow-gutter target-gutter"></div>
    <div class="target-col">${targetHtml}</div>
    <div class="arrow-gutter current-gutter"></div>
    <div class="current-col">${currentHtml}</div>
</div>`;
    }

    private _stripHexBytes(asm: string): string {
        if (!asm) return '';
        // Format is "  hex_bytes \t mnemonic operands" - extract just mnemonic + operands
        const tabIdx = asm.indexOf('\t');
        if (tabIdx !== -1) {
            return asm.substring(tabIdx + 1).trim();
        }
        return asm.trim();
    }

    private _highlightAsmWithDiff(
        asm: string,
        parsed: any,
        mismatchedParts: DiffLine['mismatchedParts'],
        side: 'target' | 'current'
    ): string {
        if (!asm) return '&nbsp;';

        // If no parsed info or no mismatches, use basic highlighting
        if (!parsed || !mismatchedParts || mismatchedParts.length === 0) {
            return this._highlightAsm(asm);
        }

        let html = this._escapeHtml(asm);

        // Highlight mismatched mnemonic
        const mnemonicMismatch = mismatchedParts.find(p => p.partType === 'mnemonic');
        if (mnemonicMismatch) {
            const val = side === 'target' ? mnemonicMismatch.targetValue : mnemonicMismatch.currentValue;
            if (val) {
                html = html.replace(
                    new RegExp(`\\b${this._escapeRegex(val)}\\b`),
                    `<span class="mismatch-highlight mnemonic">${val}</span>`
                );
            }
        }

        // Highlight mismatched operands
        for (const p of mismatchedParts) {
            if (p.partType === 'operand') {
                const val = side === 'target' ? p.targetValue : p.currentValue;
                if (val) {
                    html = html.replace(
                        new RegExp(`\\b${this._escapeRegex(val)}\\b`),
                        `<span class="mismatch-highlight operand">${val}</span>`
                    );
                }
            }
        }

        // Apply standard syntax highlighting to non-mismatched parts
        // Registers (not already highlighted)
        html = html.replace(/(?<!<[^>]*)\b(r\d{1,2}|f\d{1,2}|sp|lr|cr\d?)\b(?![^<]*>)/g,
            '<span class="register">$1</span>');

        // Hex numbers
        html = html.replace(/(?<!<[^>]*)\b(0x[0-9a-fA-F]+|-?0x[0-9a-fA-F]+)\b(?![^<]*>)/g,
            '<span class="hex">$1</span>');

        return html;
    }

    private _escapeRegex(str: string): string {
        return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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

.col-header.line-num-header {
    width: 40px;
    flex: none;
}

.col-header.marker-header {
    width: 20px;
    flex: none;
}

.col-header.arrow-header {
    width: 40px;
    flex: none;
}

.col-header.target-header,
.col-header.current-header {
    flex: 1;
}

/* Arrow gutter in rows */
.arrow-gutter {
    width: 40px;
    flex: none;
    position: relative;
}

/* SVG arrow overlay */
.arrow-overlay {
    position: absolute;
    top: 0;
    pointer-events: none;
    overflow: visible;
    z-index: 10;
}

.diff-container {
    position: relative;
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

.diff-row.highlighted {
    outline: 2px solid var(--vscode-focusBorder);
    outline-offset: -2px;
}

.diff-row.header-row {
    background: var(--header-bg);
    font-weight: bold;
    border-bottom: 1px solid var(--border-color);
}

.diff-row.header-row .target-col,
.diff-row.header-row .current-col {
    color: var(--vscode-symbolIcon-functionForeground, #dcdcaa);
}

/* Diff type specific backgrounds */
.diff-row.diff-r { background: rgba(156, 220, 254, 0.15); }  /* register - blue */
.diff-row.diff-i { background: rgba(181, 206, 168, 0.15); }  /* immediate - green */
.diff-row.diff-o { background: rgba(220, 53, 69, 0.15); }    /* opcode - red */
.diff-row.diff-s { background: rgba(255, 193, 7, 0.15); }    /* stack - yellow */

/* Marker column */
.marker-col {
    width: 20px;
    text-align: center;
    font-weight: bold;
    flex-shrink: 0;
    font-size: 11px;
}

.diff-marker {
    display: inline-block;
    width: 14px;
    height: 14px;
    line-height: 14px;
    text-align: center;
    border-radius: 2px;
    font-size: 10px;
}

.marker-reg { background: #9cdcfe; color: #1e1e1e; }
.marker-imm { background: #b5cea8; color: #1e1e1e; }
.marker-op { background: #f14c4c; color: white; }
.marker-stack { background: #cca700; color: #1e1e1e; }
.marker-diff { background: #888; color: white; }
.marker-target { background: #f14c4c; color: white; }
.marker-current { background: #cca700; color: #1e1e1e; }

/* Mismatch highlighting */
.mismatch-highlight {
    background: rgba(255, 255, 0, 0.3);
    border-radius: 2px;
    padding: 0 2px;
}

.mismatch-highlight.mnemonic {
    background: rgba(241, 76, 76, 0.4);
}

.mismatch-highlight.operand {
    background: rgba(255, 200, 0, 0.4);
}

/* Loading overlay */
.loading-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.loading-overlay .spinner {
    width: 24px;
    height: 24px;
    border: 2px solid var(--border-color);
    border-top-color: var(--vscode-progressBar-background);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-right: 12px;
}

.loading-overlay span {
    color: white;
    font-size: 14px;
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

/* Instruction tooltip */
.instruction-tooltip {
    display: none;
    position: fixed;
    z-index: 1000;
    max-width: 400px;
    padding: 12px;
    background: var(--vscode-editorHoverWidget-background, #252526);
    border: 1px solid var(--vscode-editorHoverWidget-border, #454545);
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    font-size: 13px;
    line-height: 1.5;
}

.tooltip-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 6px;
}

.tooltip-mnemonic {
    font-weight: bold;
    font-size: 15px;
    color: var(--vscode-symbolIcon-keywordForeground, #569cd6);
}

.tooltip-name {
    color: var(--vscode-descriptionForeground, #888);
    font-style: italic;
}

.tooltip-syntax {
    font-family: var(--vscode-editor-font-family), monospace;
    background: rgba(255, 255, 255, 0.05);
    padding: 6px 8px;
    border-radius: 3px;
    margin-bottom: 8px;
    color: var(--vscode-symbolIcon-functionForeground, #dcdcaa);
}

.tooltip-desc {
    margin-bottom: 8px;
    color: var(--fg-color);
}

.tooltip-operation {
    font-family: var(--vscode-editor-font-family), monospace;
    background: rgba(0, 100, 200, 0.1);
    padding: 6px 8px;
    border-radius: 3px;
    margin-bottom: 8px;
    border-left: 3px solid var(--vscode-symbolIcon-keywordForeground, #569cd6);
}

.tooltip-operation code {
    color: var(--vscode-symbolIcon-variableForeground, #9cdcfe);
}

.tooltip-flags {
    font-size: 11px;
    color: var(--vscode-symbolIcon-constantForeground, #b5cea8);
    margin-bottom: 6px;
}

.tooltip-category {
    font-size: 10px;
    text-transform: uppercase;
    color: var(--vscode-descriptionForeground, #888);
    margin-top: 8px;
    padding-top: 6px;
    border-top: 1px solid var(--border-color);
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
