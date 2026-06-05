const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

test('DiffProvider accepts mismatching checkdiff JSON from exit code 1', async () => {
    const childProcess = require('node:child_process');
    const originalSpawn = childProcess.spawn;

    const payload = {
        function: 'fn_80247510',
        reference_lines: 3,
        current_lines: 3,
        match: false,
        fuzzy_match_percent: 97.14597,
        target_asm: [
            '<fn_80247510>:',
            '+000: 7c 08 02 a6 \tmflr    r0',
            ''
        ],
        current_asm: [
            '<fn_80247510>:',
            '+000: 7c 08 02 a6 \tmflr    r3',
            ''
        ],
        diff: [
            '--- expected',
            '+++ current',
            '@@ -1,3 +1,3 @@',
            ' <fn_80247510>:',
            '-+000: 7c 08 02 a6 \tmflr    r0',
            '++000: 7c 08 02 a6 \tmflr    r3',
            ' '
        ]
    };

    childProcess.spawn = () => {
        const proc = new EventEmitter();
        proc.stdout = new EventEmitter();
        proc.stderr = new EventEmitter();
        proc.kill = () => {};

        process.nextTick(() => {
            proc.stdout.emit('data', JSON.stringify(payload));
            proc.emit('close', 1);
        });

        return proc;
    };

    try {
        const { DiffProvider } = require('../out/diffProvider');
        const provider = new DiffProvider('/tmp/melee');

        const result = await provider.getDiff('fn_80247510');

        assert.equal(result.functionName, 'fn_80247510');
        assert.equal(result.match, false);
        assert.equal(result.matchPercent, 97.14597);
        assert.equal(result.diffLines.some((line) => line.status === 'mismatch'), true);
    } finally {
        childProcess.spawn = originalSpawn;
    }
});
