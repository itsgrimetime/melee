# FPR Node-Set Split Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let class-1/FPR `node_set_delta` evidence produce bounded node-set split candidates and worksheets without adding a new CLI command.

**Architecture:** Keep the solver and CLI surface unchanged. Add class-aware FPR guards inside `src.mwcc_debug.node_set_split` so GPR reassociation remains unchanged while FPR reassociation only emits typed local/parameter float probes. Verify class propagation through `solve coloring`, `node-set-split`, and `plan-transforms` using focused regression tests and one live `mnDiagram_80241E78` smoke.

**Tech Stack:** Python 3.11, Typer CLI, pytest, existing `mwcc_debug.node_set_split`, `cli.debug`, and `search.directed.transform_corpus` helpers.

---

## File Structure

- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
  - Owns request parsing, candidate generation, objective evaluation, and summaries for node-set splits.
  - Add typed FPR reassociation helpers here so source-shape rules stay beside the existing GPR reassociation logic.
- Modify: `tools/melee-agent/tests/test_node_set_split.py`
  - Unit tests for request parsing, candidate generation, objective summaries, and CLI smoke helpers.
- Modify: `tools/melee-agent/tests/search/solver/test_cli_solve.py`
  - CLI-level tests for `debug solve coloring` and `debug solve node-set-split`.
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
  - CLI-level `debug search plan-transforms` smoke/regression tests.

## Task 1: Typed FPR Reassociation in Node-Set Split Generator

**Files:**
- Modify: `tools/melee-agent/src/mwcc_debug/node_set_split.py`
- Test: `tools/melee-agent/tests/test_node_set_split.py`

- [ ] **Step 1: Write failing FPR reassociation tests**

Replace `test_generate_node_set_split_patches_reassoc_rejects_fpr_request` with positive class-1 coverage and add explicit rejections:

```python
@pytest.mark.parametrize("type_name", ["float", "f32", "double", "f64"])
def test_generate_node_set_split_patches_emits_typed_fpr_reassoc_candidate(
    type_name: str,
) -> None:
    source = (
        "void fn_test(void) {\n"
        f"    {type_name} a;\n"
        f"    {type_name} b;\n"
        f"    {type_name} holder;\n"
        "    holder = a + b;\n"
        "    use(holder);\n"
        "}\n"
    )
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=1,
        target_ig=40,
        current_reg="f31",
        target_reg="f30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    patch = next(
        patch
        for patch in patches
        if patch.candidate_id.startswith("node-split-reassoc-holder-ig40-")
    )
    assert "    holder = b + a;\n" in patch.patched_source
```

Add the rejection table:

```python
@pytest.mark.parametrize(
    "source",
    [
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 holder;\n"
            "    holder = a + 1;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 holder;\n"
            "    holder = a + 1.0f;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    int b;\n"
            "    f32 holder;\n"
            "    holder = a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = (f32) a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = get(a) + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    struct Pair { f32 x; } p;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    holder = p.x + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 c;\n"
            "    f32 holder;\n"
            "    holder = a + b + c;\n"
            "    use(holder);\n"
            "}\n"
        ),
        (
            "void fn_test(void) {\n"
            "    f32 a;\n"
            "    f32 b;\n"
            "    f32 holder;\n"
            "    {\n"
            "        f32 holder;\n"
            "        holder = a + b;\n"
            "    }\n"
            "    holder = a + b;\n"
            "    use(holder);\n"
            "}\n"
        ),
    ],
)
def test_generate_node_set_split_patches_fpr_reassoc_rejects_unsafe_sources(
    source: str,
) -> None:
    req = NodeSetSplitRequest(
        function="fn_test",
        class_id=1,
        target_ig=40,
        current_reg="f31",
        target_reg="f30",
        var_name="holder",
    )

    patches = generate_node_set_split_patches(
        source, "fn_test", req, max_read_sites=1
    )

    assert not any(
        patch.candidate_id.startswith("node-split-reassoc-holder-ig40-")
        for patch in patches
    )
```

Add class-1 request preservation:

```python
def test_requests_from_node_set_delta_preserves_fpr_class_and_registers() -> None:
    delta = {
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 33,
            "current_register": "f31",
            "desired_registers": ["f28"],
            "source": {"name": "row_offset", "expression": "row_offset"},
        }],
    }

    reqs = requests_from_node_set_delta(delta)

    assert len(reqs) == 1
    assert reqs[0].class_id == 1
    assert reqs[0].current_reg == "f31"
    assert reqs[0].target_reg == "f28"
    assert reqs[0].var_name == "row_offset"
```

Add a real-source-shaped fixture:

```python
def test_fpr_node_set_delta_materializes_mndiagram_80241e78_candidate() -> None:
    source = (
        "typedef float f32;\n"
        "void mnDiagram_80241E78(void* arg0, unsigned char col, unsigned char row, int arg3) {\n"
        "    f32 x_spacing;\n"
        "    f32 col_offset;\n"
        "    f32 digit_offset;\n"
        "    int i;\n"
        "    digit_offset = x_spacing + col_offset;\n"
        "    for (i = 0; i < arg3; i++) {\n"
        "        use(digit_offset, i);\n"
        "    }\n"
        "}\n"
    )
    delta = {
        "function": "mnDiagram_80241E78",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 33,
            "current_register": "f31",
            "desired_registers": ["f28"],
            "source": {"name": "digit_offset", "expression": "digit_offset"},
        }],
    }
    req = request_from_node_set_delta(delta, source_text=source)

    patches = generate_node_set_split_patches(
        source,
        "mnDiagram_80241E78",
        req,
        max_read_sites=1,
    )

    assert req.class_id == 1
    assert any(
        patch.candidate_id.startswith(
            "node-split-reassoc-digit_offset-ig33-"
        )
        for patch in patches
    )
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_split_patches_emits_typed_fpr_reassoc_candidate \
  tools/melee-agent/tests/test_node_set_split.py::test_generate_node_set_split_patches_fpr_reassoc_rejects_unsafe_sources \
  tools/melee-agent/tests/test_node_set_split.py::test_requests_from_node_set_delta_preserves_fpr_class_and_registers \
  tools/melee-agent/tests/test_node_set_split.py::test_fpr_node_set_delta_materializes_mndiagram_80241e78_candidate
```

Expected: the positive FPR candidate tests fail because `_append_reassociation_patches` returns early for `class_id != 0`. The request-preservation test may already pass.

- [ ] **Step 3: Implement typed FPR reassociation guard**

In `tools/melee-agent/src/mwcc_debug/node_set_split.py`, keep the class-0 path unchanged and add helpers near `_append_reassociation_patches`:

```python
_FLOATING_SCALAR_TYPES = {"float", "f32", "double", "f64"}


def _floating_decl_names_for_function(
    source: str,
    function: str,
) -> set[str] | None:
    extracted = _extract_function_text(source, function)
    if extracted is None:
        return None
    params_text, body_text, _line = extracted
    counts: dict[str, int] = {}
    floating: set[str] = set()
    for decl in [*_parse_params(params_text), *walk_local_decls(body_text)]:
        counts[decl.name] = counts.get(decl.name, 0) + 1
        if _is_floating_scalar_type(decl.type_str):
            floating.add(decl.name)
    ambiguous = {name for name, count in counts.items() if count != 1}
    return {name for name in floating if name not in ambiguous}


def _is_floating_scalar_type(type_str: str) -> bool:
    normalized = " ".join(type_str.replace("*", " * ").split())
    if "*" in normalized:
        return False
    tokens = [
        token for token in normalized.split()
        if token not in {"const", "volatile", "register", "static"}
    ]
    return len(tokens) == 1 and tokens[0] in _FLOATING_SCALAR_TYPES


def _fpr_reassociation_allowed(
    floating_names: set[str] | None,
    var_name: str,
    left_operand: str,
    right_operand: str,
) -> bool:
    if floating_names is None:
        return False
    if not _SIMPLE_IDENTIFIER_RE.fullmatch(left_operand):
        return False
    if not _SIMPLE_IDENTIFIER_RE.fullmatch(right_operand):
        return False
    return {var_name, left_operand, right_operand}.issubset(floating_names)
```

Update `_append_reassociation_patches`:

```python
def _append_reassociation_patches(..., class_id: int) -> None:
    if class_id not in {0, 1}:
        return
    floating_names = (
        _floating_decl_names_for_function(source, function)
        if class_id == 1 else None
    )
    ...
            if class_id == 1 and not _fpr_reassociation_allowed(
                floating_names,
                var_name,
                left_operand,
                right_operand,
            ):
                continue
```

Do not change `_is_simple_reassociation_operand`; GPR behavior depends on its current literal support.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/test_node_set_split.py -k 'fpr_reassoc or preserves_fpr_class or mndiagram_80241e78_candidate'
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add tools/melee-agent/src/mwcc_debug/node_set_split.py tools/melee-agent/tests/test_node_set_split.py
git commit -m "feat: add typed fpr node-set split candidates"
```

## Task 2: CLI Class Propagation Regressions

**Files:**
- Modify: `tools/melee-agent/tests/search/solver/test_cli_solve.py`
- Modify only if a regression fails: `tools/melee-agent/src/cli/debug/__init__.py`

- [ ] **Step 1: Write failing CLI class propagation tests**

Add a class-1 delta derivation assertion near the existing `test_derive_node_set_delta_payload_names_source_intro_point`:

```python
def test_derive_node_set_delta_payload_uses_fpr_prefix_for_class_one():
    ig = IG(
        class_id=1,
        select_order=[33],
        nodes={
            33: IGNode(
                ig_idx=33,
                neighbors={39},
                precolored={},
                array_size=2,
                incomplete=False,
                observed_reg=31,
            )
        },
        decision_igs={33},
    )
    source = SimpleNamespace(
        kind="local",
        name="row_offset",
        type="f32",
        source_file="src/melee/mn/mndiagram.c",
        source_line=2079,
        source_col=5,
        expression="row_offset",
        base_virtual=None,
        base_var=None,
        field_offset=None,
        field_name=None,
        confidence="exact",
    )
    report = SimpleNamespace(
        virtuals=(
            SimpleNamespace(ig_idx=33, live_range=(10, 20), source=source),
        )
    )

    payload = debugcli._derive_node_set_delta_payload(
        function="mnDiagram_80241E78",
        class_id=1,
        ig=ig,
        phys_target={33: 28},
        phys_conflicts=[],
        report=report,
    )

    entry = payload["missing_virtuals"][0]
    assert payload["class_id"] == 1
    assert payload["register_prefix"] == "f"
    assert entry["current_virtual"] == "f33"
    assert entry["current_register"] == "f31"
    assert entry["desired_registers"] == ["f28"]
```

Add a `node-set-split` CLI class inference test that avoids real compiler work by monkeypatching compile/score helpers:

```python
def test_solve_node_set_split_delta_infers_fpr_class_for_compile(
    monkeypatch,
    tmp_path,
):
    melee_root = tmp_path / "melee"
    src_dir = melee_root / "src" / "melee" / "mn"
    src_dir.mkdir(parents=True)
    source = src_dir / "sample.c"
    source.write_text(
        "typedef float f32;\n"
        "void fn_test(void) {\n"
        "    f32 a;\n"
        "    f32 b;\n"
        "    f32 holder;\n"
        "    holder = a + b;\n"
        "    use(holder);\n"
        "}\n",
        encoding="utf-8",
    )
    report = melee_root / "build" / "GALE01" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "units": [
            {"name": "main/melee/mn/sample", "functions": [{"name": "fn_test"}]},
        ],
    }), encoding="utf-8")
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "function": "fn_test",
        "class_id": 1,
        "missing_virtuals": [{
            "target_ig": 33,
            "current_register": "f31",
            "desired_registers": ["f28"],
            "source": {"name": "holder", "expression": "holder"},
        }],
    }), encoding="utf-8")
    compile_class_ids = []

    def fake_compile_signature(*_args, **kwargs):
        compile_class_ids.append(kwargs["class_id"])
        return debugcli.BaselineSignature(
            assigned_regs=frozenset({(33, 31)}),
            spill_set=frozenset(),
        )

    monkeypatch.setattr(debugcli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(debugcli, "_node_set_split_compile_signature", fake_compile_signature)
    monkeypatch.setattr(debugcli, "_fresh_node_set_split_baseline_pct", lambda **_kw: (95.0, None))
    monkeypatch.setattr(debugcli, "_score_node_set_split_candidate", lambda *args, **kwargs: debugcli.CandidateScore(
        "fake",
        compile_ok=True,
        checkdiff_pct=95.0,
        checkdiff_delta=0.0,
        pcdump_score_delta=None,
        diagnostics_path=None,
        status="scored",
    ))

    result = runner.invoke(debugcli.debug_app, [
        "solve", "node-set-split",
        "--node-set-delta", str(delta),
        "--max-candidates", "1",
        "--json",
    ])

    assert result.exit_code in {0, 4}, result.output
    assert compile_class_ids
    assert set(compile_class_ids) == {1}
```

If imports are missing in the test file, add:

```python
from src.mwcc_debug.simplify_search import BaselineSignature
from src.mwcc_debug.source_shape import CandidateScore
```

and use those names instead of `debugcli.BaselineSignature` / `debugcli.CandidateScore`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/solver/test_cli_solve.py::test_derive_node_set_delta_payload_uses_fpr_prefix_for_class_one \
  tools/melee-agent/tests/search/solver/test_cli_solve.py::test_solve_node_set_split_delta_infers_fpr_class_for_compile
```

Expected: the derivation test may pass immediately; the CLI compile inference test should fail until Task 1's FPR candidate generation exists and the test imports are corrected.

- [ ] **Step 3: Fix only class propagation defects if tests expose them**

If the compile-signature helper receives class 0, keep the existing inference but ensure it runs before compile:

```python
if prelim is not None and prelim.class_id in {0, 1}:
    class_id = prelim.class_id
```

If the test cannot import `BaselineSignature` or `CandidateScore`, import them directly from their production modules in the test. Do not add test-only exports to `cli.debug`.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/search/solver/test_cli_solve.py -k 'fpr_prefix or node_set_split_delta_infers_fpr_class'
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add tools/melee-agent/tests/search/solver/test_cli_solve.py tools/melee-agent/src/cli/debug/__init__.py
git commit -m "test: cover fpr node-set split cli routing"
```

If `tools/melee-agent/src/cli/debug/__init__.py` is unchanged, omit it from `git add`.

## Task 3: Transform-Corpus FPR Node-Set Delta Smoke

**Files:**
- Modify: `tools/melee-agent/tests/search/test_cli_smoke.py`
- Modify only if a regression fails: `tools/melee-agent/src/search/directed/transform_corpus.py`

- [ ] **Step 1: Write failing transform-corpus FPR smoke**

Add this test near the existing `test_search_plan_transforms_accepts_node_set_delta_and_writes_probe`:

```python
def test_search_plan_transforms_preserves_fpr_node_set_delta_probe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mndiagram.c"
    source.write_text(
        "typedef float f32;\n"
        "void mnDiagram_80241E78(void) {\n"
        "    f32 x_spacing;\n"
        "    f32 col_offset;\n"
        "    f32 digit_offset;\n"
        "    digit_offset = x_spacing + col_offset;\n"
        "    use(digit_offset);\n"
        "}\n",
        encoding="utf-8",
    )
    delta = tmp_path / "delta.json"
    delta.write_text(json.dumps({
        "node_set_delta": {
            "kind": "node-set-delta",
            "function": "mnDiagram_80241E78",
            "class_id": 1,
            "missing_virtuals": [{
                "target_ig": 33,
                "current_register": "f31",
                "desired_registers": ["f28"],
                "source": {"expression": "digit_offset", "name": "digit_offset"},
            }],
        }
    }), encoding="utf-8")
    probes_dir = tmp_path / "probes"

    result = CliRunner().invoke(
        search_app,
        [
            "plan-transforms",
            "--function", "mnDiagram_80241E78",
            "--unit", "melee/mn/mndiagram",
            "--force-phys", "1:33:28",
            "--node-set-delta", str(delta),
            "--source-file", str(source),
            "--max-per-family", "3",
            "--write-probes", str(probes_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    probes = [
        probe for probe in payload["probes"]
        if probe["mutator_key"] == "steer_node_set_delta_split"
    ]
    assert probes
    request = probes[0]["payload"]["node_set_delta"]["requests"][0]
    assert request["class_id"] == 1
    assert request["current_reg"] == "f31"
    assert request["target_reg"] == "f28"
    assert "digit_offset = col_offset + x_spacing;" in (
        Path(probes[0]["candidate_path"]).read_text(encoding="utf-8")
    )
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/search/test_cli_smoke.py::test_search_plan_transforms_preserves_fpr_node_set_delta_probe
```

Expected: fails before Task 1 because no FPR reassociation probe is materialized.

- [ ] **Step 3: Fix transform payload only if needed**

If the test fails after Task 1 because request metadata loses class/register data, keep using `asdict(request)` in `_node_set_request_payload` and ensure no later payload normalization overwrites `class_id`, `current_reg`, or `target_reg`.

If the test fails because `--force-phys 1:33:28` class parsing rejects class 1, fix `_parse_directed_force_phys` in `tools/melee-agent/src/search/cli/__init__.py` to accept the existing class-qualified format without changing unqualified GPR behavior.

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q tools/melee-agent/tests/search/test_cli_smoke.py -k 'fpr_node_set_delta_probe or accepts_node_set_delta'
```

Expected: selected transform tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add tools/melee-agent/tests/search/test_cli_smoke.py tools/melee-agent/src/search/directed/transform_corpus.py tools/melee-agent/src/search/cli/__init__.py
git commit -m "test: cover fpr node-set transform probes"
```

Omit unchanged production files from `git add`.

## Task 4: Full Verification and #705 Resolution

**Files:**
- Modify only if needed: `/Users/mike/.codex/automations/issue-resolver/memory.md`

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
PYTHONPATH=tools/melee-agent pytest -q \
  tools/melee-agent/tests/test_node_set_split.py \
  tools/melee-agent/tests/search/solver/test_cli_solve.py -k 'solve_coloring or node_set_split' \
  tools/melee-agent/tests/search/test_cli_smoke.py -k 'node_set_delta'
```

Expected: all selected tests pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
python -m compileall -q tools/melee-agent/src
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run command-level help smoke**

Run:

```bash
PYTHONPATH=tools/melee-agent python -m src.cli debug solve node-set-split --help | head -40
```

Expected: output includes `--class`, `--node-set-delta`, and `--coupled`.

- [ ] **Step 4: Run live FPR evidence smoke**

Run a bounded live check:

```bash
tmpdir=$(mktemp -d build/mwcc_debug_cache/issue705-fpr.XXXXXX)
PYTHONPATH=tools/melee-agent python -m src.cli debug solve coloring \
  -f mnDiagram_80241E78 --class fpr --json > "$tmpdir/solve.json"; solve_status=$?
python - <<'PY' "$tmpdir/solve.json"
import json, sys
payload = json.load(open(sys.argv[1]))
delta = payload.get("node_set_delta")
assert delta, payload
assert delta["class_id"] == 1
assert delta["register_prefix"] == "f"
print("solve-coloring fpr delta ok")
PY
PYTHONPATH=tools/melee-agent python -m src.cli debug solve node-set-split \
  --node-set-delta "$tmpdir/solve.json" \
  --max-candidates 10 \
  --budget 240 \
  --timeout 120 \
  --json > "$tmpdir/node-set.json"; split_status=$?
python - <<'PY' "$tmpdir/node-set.json" "$split_status"
import json, sys
payload = json.load(open(sys.argv[1]))
status = int(sys.argv[2])
assert status in {0, 4}, (status, payload)
assert payload["request"]["class_id"] == 1
assert payload["generated_count"] > 0
print("node-set fpr smoke", payload["status"], payload["generated_count"])
PY
```

Expected: the first Python snippet prints `solve-coloring fpr delta ok`; the second prints `node-set fpr smoke ...` with `generated_count > 0`. If status is 0, record the improvement. If status is 4, record bounded negative evidence and generated/scored counts.

- [ ] **Step 5: Refresh editable install**

Run:

```bash
python tools/worktree-doctor.py --fix
/opt/homebrew/bin/python3.11 - <<'PY'
import src.cli
print(src.cli.__file__)
PY
```

Expected: the import path is `/Users/mike/code/melee/tools/melee-agent/src/cli/__init__.py`.

- [ ] **Step 6: Resolve #705**

After the live smoke passes, resolve the issue:

```bash
commit=$(git rev-parse --short HEAD)
DECOMP_AGENT_ID=codex-issue-resolver-3-20260614f melee-agent issue resolve 705 \
  --note "fixed in ${commit}: class-1/FPR node-set delta evidence now materializes typed FPR node-set split candidates; mnDiagram_80241E78 live smoke produced a bounded worksheet/evidence set."
```

If the live smoke produces no candidates, do not resolve #705. Add a note to the issue with the blocker and release the claim.

- [ ] **Step 7: Commit memory update if repo docs changed; otherwise leave repo tracked clean**

If `/Users/mike/.codex/automations/issue-resolver/memory.md` is updated, do not include it in the repo commit because it is outside `/Users/mike/code/melee`. Verify:

```bash
git status --short --branch
```

Expected: no tracked changes. Unrelated untracked `.playwright-mcp/` may remain.
