"""Tests for the production scratch-create building blocks (pure / no network)."""

import pytest

from src.cli.scratch_production import (
    PRODUCTION_COMPILER_FLAGS,
    build_production_create_data,
    _seed_source_from_repo,
)


def test_build_payload_fields():
    data = build_production_create_data(
        name="fn_1",
        target_asm="/* asm */\nblr",
        context="struct X {};",
        source_code="void fn_1(void) {}",
        compiler="mwcc_233_163n",
    )
    assert data["name"] == "fn_1"
    assert data["diff_label"] == "fn_1"
    assert data["target_asm"] == "/* asm */\nblr"
    assert data["context"] == "struct X {};"
    assert data["source_code"] == "void fn_1(void) {}"
    assert data["compiler"] == "mwcc_233_163n"
    assert data["platform"] == "gc_wii"
    assert data["diff_flags"] == []
    assert data["compiler_flags"] == PRODUCTION_COMPILER_FLAGS


def test_build_payload_flags_override():
    data = build_production_create_data(
        name="f", target_asm="x", context="", source_code="", compiler="c", flags="-O0"
    )
    assert data["compiler_flags"] == "-O0"


def test_seed_source_extracts_from_repo(tmp_path):
    src = tmp_path / "src" / "melee" / "mn"
    src.mkdir(parents=True)
    (src / "mnfoo.c").write_text(
        "#include <x.h>\n\nvoid mnFoo(int a) {\n    return;\n}\n\nvoid other(void) {}\n"
    )
    out = _seed_source_from_repo("mnFoo", "melee/mn/mnfoo.c", tmp_path)
    assert "mnFoo" in out
    assert out.strip().startswith("void mnFoo")
    assert "other" not in out


def test_seed_source_stub_when_missing(tmp_path):
    out = _seed_source_from_repo("mnFoo", "melee/mn/missing.c", tmp_path)
    assert out == "// TODO: Decompile this function\n"


def test_seed_source_stub_when_function_absent(tmp_path):
    src = tmp_path / "src" / "melee" / "mn"
    src.mkdir(parents=True)
    (src / "mnfoo.c").write_text("void somethingElse(void) {}\n")
    out = _seed_source_from_repo("mnFoo", "melee/mn/mnfoo.c", tmp_path)
    assert out == "// TODO: Decompile this function\n"


def test_compiler_flags_constant():
    assert PRODUCTION_COMPILER_FLAGS.startswith("-O4,p")


def test_run_production_create_exits_without_cf_clearance(tmp_path, monkeypatch):
    import typer

    import src.cli.scratch_production as sp

    # No cf_clearance configured -> must exit before any network/build.
    monkeypatch.setattr(sp, "load_production_cookies", lambda: {})
    with pytest.raises(typer.Exit):
        sp.run_production_create("fn_1", tmp_path, force=False, dry_run=False)


def test_production_flag_present_in_help():
    from typer.testing import CliRunner

    from src.cli.scratch import scratch_app

    runner = CliRunner()
    result = runner.invoke(scratch_app, ["create", "--help"])
    assert result.exit_code == 0
    assert "--production" in result.output
    assert "--dry-run" in result.output
    assert "--force" in result.output


def test_owner_is_account_none():
    from src.cli.scratch_production import _owner_is_account
    assert _owner_is_account(None) is False


def test_owner_is_account_anonymous():
    from src.cli.scratch_production import _owner_is_account
    assert _owner_is_account({"id": 1, "is_anonymous": True, "username": "X (anon)"}) is False


def test_owner_is_account_real():
    from src.cli.scratch_production import _owner_is_account
    assert _owner_is_account({"id": 2, "is_anonymous": False, "username": "realuser"}) is True
