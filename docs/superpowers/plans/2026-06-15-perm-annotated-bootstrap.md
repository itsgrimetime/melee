# PERM-Annotated Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `melee-agent debug permute bootstrap` a supported path for importing decomp-permuter source files annotated with `PERM_LINESWAP` and `PERM_GENERAL`.

**Architecture:** Extend the existing bootstrap path rather than adding a new command. Add tests first in `test_debug_cli_reorg.py`, then update the bootstrap helper and Typer option metadata in `tools/melee-agent/src/cli/debug/__init__.py`, keeping all import.py and post-import repair behavior in one path.

**Tech Stack:** Python 3.11, Typer, pytest, upstream decomp-permuter import.py/permuter.py.

---

## File Structure

- Modify `tools/melee-agent/tests/test_debug_cli_reorg.py`: add focused regressions for annotated source staging, validation, metadata, and PERM-aware default preserve regex.
- Modify `tools/melee-agent/src/cli/debug/__init__.py`: add `--annotated-source-file` alias, source validation, staging lock, PERM-aware preserve default, and metadata/text output.
- Modify `docs/mwcc-debug-permuter-integration.md`: document the guided annotated-source bootstrap command and the expected smoke check.
- Keep this plan and the matching design spec committed with the feature.

### Task 1: Tests For Annotated Bootstrap

- [ ] **Step 1: Add failing tests**

Add tests near the existing bootstrap tests in `tools/melee-agent/tests/test_debug_cli_reorg.py`:

```python
def test_debug_permute_bootstrap_default_preserve_macros_include_perm_family():
    assert "PERM_.*" in debug_cli._PERMUTER_DEFAULT_PRESERVE_MACROS


def test_debug_permute_bootstrap_annotated_source_stages_perm_file_and_restores(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    melee_root = tmp_path / "melee"
    perm_root = tmp_path / "decomp-permuter"
    src_path = melee_root / "src" / "melee" / "mn" / "sample.c"
    annotated_path = tmp_path / "annotated.c"
    src_path.parent.mkdir(parents=True)
    original = "void fn_80000000(void) { int a; a = 1; }\n"
    annotated = (
        "void fn_80000000(void) {\n"
        "    PERM_LINESWAP(\n"
        "        int a;\n"
        "        a = PERM_GENERAL(1, 2);\n"
        "    )\n"
        "}\n"
    )
    src_path.write_text(original)
    annotated_path.write_text(annotated)
    perm_root.mkdir()
    (perm_root / "import.py").write_text("")

    calls: list[list[str]] = []
    observed_import_source: list[str] = []

    def fake_run(argv, *, cwd=None, capture_output=False, text=False, check=False, **kwargs):
        argv = [str(part) for part in argv]
        calls.append(argv)
        if "import.py" in argv[1]:
            observed_import_source.append(src_path.read_text())
            fn_dir = perm_root / "nonmatchings" / "fn_80000000"
            fn_dir.mkdir(parents=True)
            (fn_dir / "base.c").write_text(src_path.read_text())
            (fn_dir / "compile.sh").write_text("#!/usr/bin/env bash\n")
            (fn_dir / "target.o").write_bytes(b"target")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(debug_cli, "DEFAULT_MELEE_ROOT", melee_root)
    monkeypatch.setattr(
        debug_cli,
        "_find_unit_for_function",
        lambda function, root: "melee/mn/sample",
    )
    monkeypatch.setattr(debug_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "debug", "permute", "bootstrap",
            "-f", "fn_80000000",
            "--perm-root", str(perm_root),
            "--annotated-source-file", str(annotated_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    import_cmd = next(call for call in calls if "import.py" in call[1])
    assert observed_import_source == [annotated]
    assert src_path.read_text() == original
    assert import_cmd[2] == str(src_path)
    assert "PERM_.*" in import_cmd[import_cmd.index("--preserve-macros") + 1]
    assert payload["source"] == str(annotated_path)
    assert payload["source_staged"] is True
    assert payload["source_contains_perm_macros"] is True
    assert payload["base_contains_perm_macros"] is True
    assert payload["base_object_status"] == "absent"
```

Also add a wrong-function rejection test that invokes the same command with an annotated file containing `void other_fn(void) {}` and asserts exit code 2, no import.py call, and the repo source remains unchanged.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_debug_cli_reorg.py \
  -k 'bootstrap and (annotated_source or preserve_macros)' -q
```

Expected: fail because the default regex lacks `PERM_.*`, the alias is unknown, and metadata fields are missing.

### Task 2: Bootstrap Implementation

- [ ] **Step 1: Implement the minimal production changes**

In `tools/melee-agent/src/cli/debug/__init__.py`:

- change `_PERMUTER_DEFAULT_PRESERVE_MACROS` to include `PERM_.*`;
- add `--annotated-source-file` as an alias for the existing source-file option;
- add a small helper that reads a source file and verifies `find_source_function(text, function)` is not `None`;
- wrap the `_staged_permuter_import_source` overwrite/restore section in a repo-local lock file under the build/temp area;
- record `source_contains_perm_macros`, `base_contains_perm_macros`, `preserve_macros`, and `base_object_status` in the payload;
- print those fields in non-JSON output.

- [ ] **Step 2: Run tests and confirm GREEN**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_debug_cli_reorg.py \
  -k 'bootstrap and (annotated_source or preserve_macros)' -q
```

Expected: all selected tests pass.

### Task 3: Docs And Verification

- [ ] **Step 1: Document the guided command**

Update `docs/mwcc-debug-permuter-integration.md` near the bootstrap/setup section with:

```markdown
For guided PERM campaigns, put `PERM_LINESWAP`, `PERM_GENERAL`, or other
decomp-permuter `PERM_*` macros in a temporary copy of the source TU, then import
that annotated file through bootstrap:

```bash
melee-agent debug permute bootstrap \
  -f mnDiagram_SortNamesByKOs \
  --annotated-source-file /tmp/mnDiagram_SortNamesByKOs.perm.c
```

Do not hand-edit PERM macros into `base.c` after import; import.py must see the
annotated source so generated candidates expand the PERM syntax before compile.
```

- [ ] **Step 2: Run focused and smoke verification**

Run:

```bash
PYTEST_ADDOPTS=--no-cov pytest tools/melee-agent/tests/test_debug_cli_reorg.py -k bootstrap -q
python -m compileall -q tools/melee-agent/src/cli tools/melee-agent/src/mwcc_debug
git diff --check
```

Then run a command-level smoke on `mnDiagram_SortNamesByKOs`: create a temporary annotated copy from the reporter worktree source, bootstrap it with `--annotated-source-file`, run a bounded permuter debug/candidate generation command, and verify no generated candidate fails with raw `PERM_LINESWAP` or `PERM_GENERAL` compiler errors.
