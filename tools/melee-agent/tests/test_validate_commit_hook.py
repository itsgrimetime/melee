from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.hooks import validate_commit


def _run_header_signature_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    staged_files: list[str],
    c_content: str,
    h_content: str,
    c_diff: str,
    h_diff: str = "",
) -> validate_commit.CommitValidator:
    validator = validate_commit.CommitValidator(worktree_path=str(tmp_path))
    monkeypatch.setattr(validator, "_get_staged_files", lambda: staged_files)
    monkeypatch.setattr(
        validator,
        "_get_staged_diff",
        lambda path: h_diff if path.endswith(".h") else c_diff,
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["git", "show"]:
            path = cmd[2][1:]
            if path.endswith(".c"):
                return SimpleNamespace(stdout=c_content)
            if path.endswith(".h"):
                return SimpleNamespace(stdout=h_content)
        raise AssertionError(f"unexpected subprocess.run call: {cmd!r}")

    monkeypatch.setattr(validate_commit.subprocess, "run", fake_run)

    validator.validate_header_signatures()
    return validator


def _run_symbol_rename_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    staged_files: list[str],
    diff: str,
) -> validate_commit.CommitValidator:
    validator = validate_commit.CommitValidator(worktree_path=str(tmp_path))
    monkeypatch.setattr(validator, "_get_staged_files", lambda: staged_files)
    monkeypatch.setattr(validator, "_get_staged_diff", lambda path: diff)

    validator.validate_symbol_renames()
    return validator


def test_symbol_rename_check_ignores_removed_type_declaration_with_added_address_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    diff = """\
diff --git a/src/melee/hsd/hsd_3AA7.c b/src/melee/hsd/hsd_3AA7.c
@@ -4,9 +4,8 @@ void hsd_803AAA48(CardCmd* cmd)
 {
-    CardState* state = cmd->state;
-    state->status = 1;
+    cmd->state->status = 1;
+    fn_803AC2A4(cmd);
 }
"""

    validator = _run_symbol_rename_check(
        monkeypatch,
        tmp_path,
        staged_files=["melee/src/melee/hsd/hsd_3AA7.c"],
        diff=diff,
    )

    assert validator.errors == []


def test_symbol_rename_check_flags_descriptive_symbol_replaced_with_address_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    diff = """\
diff --git a/src/melee/it/item.c b/src/melee/it/item.c
@@ -20,7 +20,7 @@ void it_8026B390(void)
 {
-    item->table = ItemStateTable_GShell;
+    item->table = it_803F5BA8;
 }
"""

    validator = _run_symbol_rename_check(
        monkeypatch,
        tmp_path,
        staged_files=["melee/src/melee/it/item.c"],
        diff=diff,
    )

    messages = [error.message for error in validator.errors]
    assert len(messages) == 1
    assert "ItemStateTable_GShell" in messages[0]
    assert "it_803F5BA8" in messages[0]


def test_symbol_rename_check_flags_descriptive_symbol_argument_replaced_with_address_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    diff = """\
diff --git a/src/melee/it/item.c b/src/melee/it/item.c
@@ -20,7 +20,7 @@ void it_8026B390(void)
 {
-    load_item_table(ItemStateTable_GShell);
+    load_item_table(it_803F5BA8);
 }
"""

    validator = _run_symbol_rename_check(
        monkeypatch,
        tmp_path,
        staged_files=["melee/src/melee/it/item.c"],
        diff=diff,
    )

    messages = [error.message for error in validator.errors]
    assert len(messages) == 1
    assert "ItemStateTable_GShell" in messages[0]
    assert "it_803F5BA8" in messages[0]


def test_header_signature_check_ignores_unchanged_preexisting_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    c_content = """\
void fn_80179F6C(int idx, int value)
{
}

void fn_8017A004(void)
{
}

void fn_8017A9B4(void)
{
    int touched = 1;
}
"""
    h_content = """\
/* 179F6C */ UNK_RET fn_80179F6C(int idx, int value);
/* 17A004 */ UNK_RET fn_8017A004(UNK_PARAMS);
/* 17A9B4 */ void fn_8017A9B4(void);
"""
    c_diff = """\
diff --git a/src/melee/gm/gmresultplayer.c b/src/melee/gm/gmresultplayer.c
@@ -8,5 +8,5 @@ void fn_8017A9B4(void)
 {
-    int touched = 0;
+    int touched = 1;
 }
"""

    validator = _run_header_signature_check(
        monkeypatch,
        tmp_path,
        staged_files=["melee/src/melee/gm/gmresultplayer.c"],
        c_content=c_content,
        h_content=h_content,
        c_diff=c_diff,
    )

    assert validator.errors == []


def test_header_signature_check_still_flags_touched_function_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    c_content = """\
void fn_8017A9B4(void)
{
    int touched = 1;
}
"""
    h_content = "/* 17A9B4 */ UNK_RET fn_8017A9B4(UNK_PARAMS);\n"
    c_diff = """\
diff --git a/src/melee/gm/gmresultplayer.c b/src/melee/gm/gmresultplayer.c
@@ -2,5 +2,5 @@ void fn_8017A9B4(void)
 {
-    int touched = 0;
+    int touched = 1;
 }
"""

    validator = _run_header_signature_check(
        monkeypatch,
        tmp_path,
        staged_files=["melee/src/melee/gm/gmresultplayer.c"],
        c_content=c_content,
        h_content=h_content,
        c_diff=c_diff,
    )

    messages = [error.message for error in validator.errors]
    assert len(messages) == 1
    assert "fn_8017A9B4" in messages[0]
    assert "UNK_RET fn_8017A9B4(UNK_PARAMS)" in messages[0]
