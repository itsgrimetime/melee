# Reviewed Namespace Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic discover-review-rerun workflow that supplies hash-bound full namespace maps only for allocator artifacts the automatic v5 solver cannot prove.

**Architecture:** A focused `namespace_review.py` module owns strict request/review schemas, map validation, sealing, and resolution. The delta runner captures raw parent/candidate evidence before objective publication, emits an incomplete request when namespaces remain unresolved, and validates an optional reviewed sidecar on rerun. Automatic v5 proof remains authoritative; reviewed maps are exact-content fallbacks and are bound into objective/publication epochs.

**Tech Stack:** Python 3, dataclasses, PyYAML, SHA-256, existing delta store/evaluator/role solver, Typer CLI, pytest.

## Global Constraints

- Do not weaken or bypass the reviewer-approved automatic v5 pairwise solver.
- Reviewed bindings apply only to artifacts recorded unresolved in the exact bound request.
- Resolution order is exact source+pcdump inheritance, automatic v5 proof, reviewed binding, then incomplete.
- Pcdump-only equality is never sufficient.
- Automatic proof cannot be overridden by a reviewed entry.
- Every sealed map is fully expanded; no identity shorthand is accepted as authority.
- ABI roles map identically and true virtual roles form a complete bijection over the coherent class domain.
- Reviews bind target, delta lattice, parents, compiler/cflags/object/parser/inspector context, namespace epoch, and request digest.
- Preserve compatible content-addressed raw evidence caches while invalidating current publications.
- Any unresolved viable artifact prevents exact Pareto publication.

---

### Task 1: Strict request/review schemas and sealing

**Files:**
- Create: `tools/melee-agent/src/search/delta_minimize/namespace_review.py`
- Create: `tools/melee-agent/tests/search/delta_minimize/test_namespace_review.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/__init__.py`

**Interfaces:**
- `NamespaceArtifact`: immutable artifact id/kind/side/candidate/mask/source+pcdump hashes/domain/automatic status/diagnostic.
- `NamespaceReviewRequest`: strict `delta-minimize-namespace-review-request.v1` model with canonical context and deterministic `to_dict()/to_yaml()/sha256`.
- `ReviewedNamespaceBinding`: exact full canonical-to-artifact map.
- `ReviewedNamespaces`: strict `delta-minimize-reviewed-namespaces.v1` model.
- `load_review_request(path)`, `load_reviewed_namespaces(path)`, `seal_namespace_review(request, identity_ids, map_paths)`, and `resolve_reviewed_map(...)`.

- [ ] **Step 1: Write strict-schema RED tests**

Test deterministic request round-trip and review loading. Parametrize rejection
of duplicate YAML keys, unknown/missing fields, symlink paths, bad SHA text,
wrong request digest, context drift, duplicate artifact ids/content pairs,
bad candidate id/mask, and unsupported schema/epoch.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd tools/melee-agent
python -m pytest --no-cov -q tests/search/delta_minimize/test_namespace_review.py
```

Expected: import/interface failure.

- [ ] **Step 3: Implement immutable strict models and YAML parsing**

Use the existing unique-key YAML and canonical JSON/hash patterns. Require exact
field sets and lowercase 64-character hashes. Write atomically and reject
symlinked inputs/outputs.

- [ ] **Step 4: Add map/sealer RED tests**

For a domain `0..109`, cover full identity expansion and supplied nonidentity
maps. Reject missing/extra keys, bools, duplicate/out-of-range values,
nonidentity ABI 0..31, incomplete virtual 32..109 bijections, anchor 64/78
conflicts, missing/extra/redundant approvals, automatically resolved entries,
and conflicting duplicate exact-content maps.

- [ ] **Step 5: Implement sealing and resolver validation**

`--accept-identity` is only a sealing input; the output stores every pair.
Require reviewed entries to equal the unresolved exact-content identities in
the request. `resolve_reviewed_map` must revalidate current hashes/context and
return artifact-to-canonical only after full validation.

- [ ] **Step 6: Verify and commit**

Run the new module tests and scoped Ruff. Commit:
`feat: add reviewed namespace attestations`.

---

### Task 2: Discovery, resolution, and publication epochs

**Files:**
- Modify: `tools/melee-agent/src/search/delta_minimize/run.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/objectives.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/evaluator.py`
- Modify: `tools/melee-agent/src/search/delta_minimize/store.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_run.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_evaluator.py`
- Test: `tools/melee-agent/tests/search/delta_minimize/test_store.py`

**Interfaces:**
- Extend `DeltaMinimizeConfig` with `namespace_review_path: Path | None`.
- Add store paths/writers for `namespace-review-request.yaml` and immutable reviewed-resolution provenance.
- Add a central resolver returning raw-IG-to-canonical maps plus source (`inheritance`, `automatic-v5`, `reviewed-v1`, `unresolved`).
- Bump objective-input and objective-manifest schemas and add `namespace_resolution` provenance/digest.

- [ ] **Step 1: Add first-run discovery RED**

Construct two parents where target roles are valid but the strict v5 full map
is ambiguous. Assert the runner still extracts/materializes the lattice,
captures every raw candidate once, writes a deterministic review request and
incomplete result, and exits without objective/Pareto publication.

- [ ] **Step 2: Implement capture-before-objective discovery**

Refactor only orchestration: parent capture, delta extraction/materialization,
raw candidate capture, then namespace resolution, then objective/profile
publication. Preserve compile-invalid visibility and existing evidence caches.
Invalidate current result/candidates/request publications at run entry.

- [ ] **Step 3: Add resolver precedence RED tests**

Cover exact two-hash inheritance, pcdump-only rejection, automatic v5 success,
reviewed fallback, automatic/review conflict rejection, duplicate exact-content
inheritance, partial review incomplete, changed source/pcdump/context rejection,
and candidate maps composed correctly with donor/canonical maps.

- [ ] **Step 4: Implement central resolution in objectives/evaluator**

Automatic proof runs before reviewed fallback. Parent objective inference and
candidate color profiling consume the same validated map source. Reviewed maps
authorize namespace identity only; all objective facts continue to come from
captured evidence.

- [ ] **Step 5: Add epoch/cache/publication RED tests**

Changing request/review digest must start a new objective/profile publication
epoch but reuse compatible raw parent/candidate evidence. Pre-sidecar objective
manifests and inputs must reject. Missing review must never leave an old exact
result current.

- [ ] **Step 6: Implement epoch/schema bumps and verify**

Bind namespace schema, sidecar schema, request/review digest, parser, compiler,
target, delta, and run context into objective inputs/manifest/cache keys. Run
the three affected modules plus full delta-minimize suite and scoped Ruff.
Commit: `feat: resolve reviewed delta namespaces`.

---

### Task 3: CLI, documentation, and retained acceptance

**Files:**
- Modify: `tools/melee-agent/src/search/cli/__init__.py`
- Modify: `tools/melee-agent/tests/search/delta_minimize/test_cli.py`
- Modify: `tools/melee-agent/tests/search/delta_minimize/test_integration.py`
- Modify: relevant help goldens under `tools/melee-agent/tests/golden/debug_cli_help/`
- Modify: `docs/superpowers/specs/2026-07-11-two-frontier-delta-minimizer-design.md`
- Modify: `docs/superpowers/plans/2026-07-11-two-frontier-delta-minimizer.md`

**Interfaces:**
- Add `--namespace-review PATH` to `delta-minimize`.
- Add `debug search delta-namespace-review seal --request PATH --accept-identity ID... --map ID=PATH... --out PATH`.
- Text/JSON incomplete output names the request path and unresolved artifact ids.

- [ ] **Step 1: Add CLI/help/seal RED tests**

Assert help, strict option parsing, deterministic seal output, duplicate/unknown
approval errors, atomic output, and actionable incomplete rendering.

- [ ] **Step 2: Wire CLI and update goldens/docs**

Keep CLI thin over Task 1 functions. Document discover, inspect, seal, and rerun
commands; explain that sealing is explicit authority and all pairs are expanded.

- [ ] **Step 3: Add two-stage integration RED/GREEN**

First run captures all candidates and requests review. Seal exact unresolved
ids. Second run reuses every raw evidence entry, performs no recapture, and
publishes only after all viable namespaces resolve. Assert exact legal and
Pareto mask sets.

- [ ] **Step 4: Retained discovery and seal**

Run the frozen real family without a review under v5. Verify the deterministic
request. Seal exactly `parent:right`, `candidate:mask-100`,
`candidate:mask-101`, and `candidate:mask-110` as full identity maps. Verify
`mask-111` is absent because it exact-inherits `parent:right`.

- [ ] **Step 5: Retained reviewed rerun**

Rerun with the sealed sidecar. Require exit 0, 8/8 legal/viable/complete,
`exact_four_axis=true`, no blockers, Pareto `000/001/010/011`,
`best_next=000`, and exact endpoint hashes. Confirm raw capture caches were
reused.

- [ ] **Step 6: Final verification and commit**

Run full focused/adjacent suites, scoped Ruff, help golden comparison,
`python configure.py && ninja`, and `git diff --check`. Commit:
`test: prove reviewed namespace workflow`.
