// docs/superpowers/plans/backtest-run.workflow.js
export const meta = {
  name: 'backtest-run',
  description: 'Orchestrate the tooling-backtest: calibration gate + cheap tiers + LLM judge + blind-agent escalation',
  phases: [{ title: 'Cheap tiers' }, { title: 'Blind agents' }, { title: 'Report' }],
}

const WT = '/Users/mike/code/melee/.claude/worktrees/awesome-lamport-fe4b0b'
const AGENT = `${WT}/tools/melee-agent`

phase('Cheap tiers')
// All of build-corpus, calibrate, and the cheap tiers are deterministic CLI.
// (Cases must already be built via `backtest build-corpus` before this workflow runs.)
//
// 1) HARD GATE: the Phase-0 two-sided calibration must pass before we trust any
//    downstream verdict. `calibrate` exits non-zero on failure; the agent echoes
//    its JSON either way so we can throw with the failure detail.
const calJson = await agent(
  `cd ${AGENT} && python -m src.cli backtest calibrate --json ; echo "EXIT:$?". ` +
  `Echo the JSON object and the EXIT line verbatim, nothing else.`,
  { label: 'calibrate-gate', phase: 'Cheap tiers' })
const calibration = JSON.parse(calJson.slice(calJson.indexOf('{'), calJson.lastIndexOf('}') + 1))
if (!calibration.passed) {
  throw new Error('backtest calibration gate FAILED — refusing to run; failures: ' +
                  JSON.stringify(calibration.failures))
}

// 2) Run the deterministic cheap tiers (advisory + generative) over the stored
//    corpus. This populates a result row per case (with the advisory bundle in
//    evidence), which the LLM judge then reads via `judge-input`.
await agent(`cd ${AGENT} && python -m src.cli backtest run --cheap --json. Echo the JSON.`,
  { label: 'cheap-tiers', phase: 'Cheap tiers' })

// 3) Enumerate the cases that now have a result row and need a judge verdict.
const caseIds = JSON.parse(await agent(
  `cd ${AGENT} && python -m src.cli backtest pending-judge --json. Echo only the JSON array.`,
  { label: 'pending-judge', phase: 'Cheap tiers' }))

// 4) One judge agent per case. The agent reads the LABEL-BLINDED judge input from
//    the store (no provenance/author), applies the rubric, and writes the verdict
//    back through the CLI (which recomputes the rollup).
const VERDICT_SCHEMA = { type: 'object', additionalProperties: false,
  properties: { verdict: { type: 'string', enum: ['names-lever','hints-adjacent','silent-or-wrong'] },
                rationale: { type: 'string' } }, required: ['verdict','rationale'] }

await parallel(caseIds.map(cid => () =>
  agent(`Score one backtest advisory bundle. ` +
        `Run: cd ${AGENT} && python -m src.cli backtest judge-input ${cid} --json ` +
        `→ a label-blinded JSON object {function, ground_truth_diff, lever_class, tool_outputs}. ` +
        `Apply this rubric and decide ONE verdict:\n` +
        `names-lever = a tool output identifies the exact change in ground_truth_diff ` +
        `(same variable/type/literal/structural move); ` +
        `hints-adjacent = right region/mechanism, not the specific change; ` +
        `silent-or-wrong = nothing references the actual lever (DEFAULT when uncertain). ` +
        `You are BLIND: judge ONLY from the judge-input JSON; do NOT inspect git history or future commits. ` +
        `Return {"verdict": ..., "rationale": ...} matching the schema, then write it back via: ` +
        `cd ${AGENT} && python -m src.cli backtest set-advisory ${cid} <verdict>.`,
        { label: `judge:${cid}`, phase: 'Cheap tiers', schema: VERDICT_SCHEMA })))

phase('Blind agents')
const escalate = JSON.parse(await agent(
  `cd ${AGENT} && python -m src.cli backtest escalation --json  (returns case_ids for the blind tier). Echo only the JSON array.`,
  { label: 'escalation-list', phase: 'Blind agents' }))

await parallel(escalate.map(cid => () =>
  agent(`Blind matching attempt for backtest case ${cid}. ` +
        `Run: cd ${AGENT} && python -m src.cli backtest open-sandbox ${cid} --json  → gives {sandbox, function}. ` +
        `In that sandbox dir ONLY, use the /decomp workflow (checkdiff) to match the function. ` +
        `You are BLIND: do NOT inspect git history for future commits. ` +
        `Stop after a fixed effort budget. Then record the outcome: ` +
        `cd ${AGENT} && python -m src.cli backtest set-agent ${cid} <matched|improved|stuck>. ` +
        `Finally: cd ${AGENT} && python -m src.cli backtest close-sandbox ${cid}.`,
        { label: `blind:${cid}`, phase: 'Blind agents', isolation: 'worktree' })))

phase('Report')
const report = await agent(`cd ${AGENT} && python -m src.cli backtest report --json. Echo the JSON.`,
  { label: 'report', phase: 'Report' })
return { report }
