"""Tests for the production scratch-create building blocks (pure / no network)."""

import pytest

from src.cli.scratch_production import (
    PRODUCTION_COMPILER_FLAGS,
    _seed_source_from_repo,
    build_production_create_data,
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
    # No preset key unless explicitly requested.
    assert "preset" not in data


def test_build_payload_flags_override():
    data = build_production_create_data(
        name="f", target_asm="x", context="", source_code="", compiler="c", flags="-O0"
    )
    assert data["compiler_flags"] == "-O0"


def test_build_payload_includes_preset_when_given():
    data = build_production_create_data(
        name="f", target_asm="x", context="", source_code="", compiler="c", preset=63
    )
    assert data["preset"] == 63


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
    # -proc gekko is required for correct PPC codegen; -DM2CTX must NOT be present
    # (it breaks the decompctx context — flips headers to m2c stub types).
    assert "-proc gekko" in PRODUCTION_COMPILER_FLAGS
    assert "-DM2CTX" not in PRODUCTION_COMPILER_FLAGS


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


def test_production_create_cli_dispatches_to_top_level_module(monkeypatch):
    from typer.testing import CliRunner

    import src.cli.scratch_production as sp
    from src.cli.scratch import scratch_app

    calls = []
    monkeypatch.setattr(
        sp,
        "run_production_create",
        lambda function_name, melee_root, *, force=False, dry_run=False: calls.append(
            (function_name, melee_root, force, dry_run)
        ),
    )

    runner = CliRunner()
    result = runner.invoke(scratch_app, ["create", "fn_1", "--production", "--dry-run"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "fn_1"
    assert calls[0][2:] == (False, True)


def test_production_update_cli_dispatches_to_top_level_module(monkeypatch):
    from typer.testing import CliRunner

    import src.cli.scratch_production as sp
    from src.cli.scratch import scratch_app

    calls = []
    monkeypatch.setattr(
        sp,
        "run_production_update",
        lambda function_name, melee_root, *, refresh_context=True, compile_after=True, dry_run=False: calls.append(
            (function_name, melee_root, refresh_context, compile_after, dry_run)
        ),
    )

    runner = CliRunner()
    result = runner.invoke(
        scratch_app,
        ["create", "fn_1", "--production", "--update", "--no-context", "--no-compile", "--dry-run"],
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "fn_1"
    assert calls[0][2:] == (False, False, True)


def test_owner_is_account_none():
    from src.cli.scratch_production import _owner_is_account
    assert _owner_is_account(None) is False


def test_owner_is_account_anonymous():
    from src.cli.scratch_production import _owner_is_account
    assert _owner_is_account({"id": 1, "is_anonymous": True, "username": "X (anon)"}) is False


def test_owner_is_account_real():
    from src.cli.scratch_production import _owner_is_account
    assert _owner_is_account({"id": 2, "is_anonymous": False, "username": "realuser"}) is True


def _fake_console_collector(monkeypatch):
    """Patch scratch_production.console with a collector; return the list of printed strings."""
    import src.cli.scratch_production as sp

    printed: list[str] = []

    class _FakeConsole:
        def print(self, *a, **k):
            printed.append(" ".join(str(x) for x in a))

    monkeypatch.setattr(sp, "console", _FakeConsole())
    monkeypatch.setattr(sp, "db_upsert_scratch", lambda *a, **k: True)
    monkeypatch.setattr(sp, "db_upsert_function", lambda *a, **k: True)
    monkeypatch.setattr("src.cli.scratch._save_scratch_token", lambda *a, **k: None)
    monkeypatch.setattr("src.cli.sync._helpers.RATE_LIMIT_DELAY", 0.0)
    return printed


import httpx  # noqa: E402
import respx  # noqa: E402


@respx.mock
async def test_create_claim_record_warns_on_anonymous_owner(monkeypatch):
    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)

    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "AAAAA", "claim_token": "tok"})
    )
    respx.post("https://decomp.me/api/scratch/AAAAA/claim").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    respx.get("https://decomp.me/api/scratch/AAAAA").mock(
        return_value=httpx.Response(200, json={"slug": "AAAAA", "owner": {"id": 1, "is_anonymous": True}})
    )

    await sp._create_claim_record({"name": "fn_1"}, "fn_1", {"cf_clearance": "x", "sessionid": "y"})

    blob = "\n".join(printed)
    assert "Created scratch" in blob
    assert "NOT owned by your account" in blob


@respx.mock
async def test_create_claim_record_silent_on_account_owner(monkeypatch):
    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)

    respx.post("https://decomp.me/api/scratch").mock(
        return_value=httpx.Response(201, json={"slug": "BBBBB", "claim_token": "tok"})
    )
    respx.post("https://decomp.me/api/scratch/BBBBB/claim").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    respx.get("https://decomp.me/api/scratch/BBBBB").mock(
        return_value=httpx.Response(
            200, json={"slug": "BBBBB", "owner": {"id": 2, "is_anonymous": False, "username": "real"}}
        )
    )

    await sp._create_claim_record({"name": "fn_1"}, "fn_1", {"cf_clearance": "x", "sessionid": "y"})

    blob = "\n".join(printed)
    assert "Created scratch" in blob
    assert "NOT owned" not in blob


# ---------------------------------------------------------------------------
# Production scratch UPDATE (`scratch create <func> --production --update`)
# ---------------------------------------------------------------------------

import json  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _fake_db_with_slug(slug):
    """A get_db() stand-in whose functions row yields ``production_scratch_slug``."""
    row = None if slug is _MISSING else {"production_scratch_slug": slug}

    class _Cur:
        def fetchone(self):
            return row

    class _Conn:
        def execute(self, *a, **k):
            return _Cur()

    class _DB:
        @contextmanager
        def connection(self):
            yield _Conn()

    return _DB()


_MISSING = object()  # sentinel: the functions row does not exist at all


def test_existing_production_slug_returns_slug(monkeypatch):
    import src.cli.scratch_production as sp

    monkeypatch.setattr("src.db.get_db", lambda: _fake_db_with_slug("LlxRu"))
    assert sp._existing_production_slug("mnDiagram_InputProc") == "LlxRu"


def test_existing_production_slug_none_when_no_row(monkeypatch):
    import src.cli.scratch_production as sp

    monkeypatch.setattr("src.db.get_db", lambda: _fake_db_with_slug(_MISSING))
    assert sp._existing_production_slug("mnDiagram_InputProc") is None


def test_existing_production_slug_none_when_slug_null(monkeypatch):
    import src.cli.scratch_production as sp

    monkeypatch.setattr("src.db.get_db", lambda: _fake_db_with_slug(None))
    assert sp._existing_production_slug("mnDiagram_InputProc") is None


# --- sync orchestrator guards --------------------------------------------------


def test_run_production_update_exits_without_cf_clearance(tmp_path, monkeypatch):
    import typer

    import src.cli.scratch_production as sp

    monkeypatch.setattr(sp, "load_production_cookies", lambda: {})
    with pytest.raises(typer.Exit):
        sp.run_production_update("fn_1", tmp_path)


def test_run_production_update_exits_when_no_existing_scratch(tmp_path, monkeypatch):
    import typer

    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)
    monkeypatch.setattr(sp, "load_production_cookies", lambda: {"cf_clearance": "x"})

    async def _noop_preflight(_cookies):
        return None

    monkeypatch.setattr(sp, "_preflight_auth", _noop_preflight)
    monkeypatch.setattr(sp, "_existing_production_slug", lambda fn: None)

    # If the update flow were reached it would need the network; assert it is not.
    async def _must_not_run(**kwargs):
        raise AssertionError("update flow must not run when no scratch exists")

    monkeypatch.setattr(sp, "_update_production_scratch", _must_not_run)

    with pytest.raises(typer.Exit):
        sp.run_production_update("fn_1", tmp_path)

    blob = "\n".join(printed)
    assert "No production scratch" in blob
    assert "--update" in blob


# --- async update flow (network mocked) ---------------------------------------


def _stub_update_build(monkeypatch, *, source="void fn_1(void) {}", context="struct X {};"):
    """Stub the repo-extraction helpers so the async update flow can run offline."""
    import src.cli.scratch_production as sp

    async def _fake_extract(_root, name):
        return SimpleNamespace(name=name, file_path="melee/mn/mnfoo.c", asm="blr")

    monkeypatch.setattr("src.extractor.extract_function", _fake_extract)
    monkeypatch.setattr(sp, "_seed_source_from_repo", lambda *a, **k: source)

    ctx_calls = {"n": 0}

    def _fake_ctx(*a, **k):
        ctx_calls["n"] += 1
        return context

    monkeypatch.setattr("src.cli.scratch._build_stripped_context", _fake_ctx)
    return ctx_calls


@respx.mock
async def test_update_blocks_on_anonymous_owner(monkeypatch):
    import typer

    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)
    # If the build is reached, fail loudly: ownership must be checked first.
    monkeypatch.setattr(
        "src.extractor.extract_function",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not build before ownership check")),
    )

    respx.get("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu", "owner": {"id": 1, "is_anonymous": True}})
    )
    patch_route = respx.patch("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu"})
    )

    with pytest.raises(typer.Exit):
        await sp._update_production_scratch(
            slug="LlxRu", function_name="fn_1", melee_root=Path("."), cookies={"cf_clearance": "x", "sessionid": "y"}
        )

    assert not patch_route.called
    blob = "\n".join(printed)
    assert "fix-ownership" in blob


@respx.mock
async def test_update_errors_on_stale_404_slug(monkeypatch):
    import typer

    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)
    respx.get("https://decomp.me/api/scratch/GONE9").mock(
        return_value=httpx.Response(404, json={"detail": "Not found"})
    )

    with pytest.raises(typer.Exit):
        await sp._update_production_scratch(
            slug="GONE9", function_name="fn_1", melee_root=Path("."), cookies={"cf_clearance": "x"}
        )

    blob = "\n".join(printed)
    assert "no longer exists" in blob.lower()


@respx.mock
async def test_update_happy_path_patches_then_compiles(monkeypatch):
    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)
    _stub_update_build(monkeypatch)

    respx.get("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(
            200, json={"slug": "LlxRu", "owner": {"id": 2, "is_anonymous": False, "username": "real"}}
        )
    )
    patch_route = respx.patch("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu", "owner": {"id": 2, "is_anonymous": False}})
    )
    compile_route = respx.get("https://decomp.me/api/scratch/LlxRu/compile").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "compiler_output": "",
                "diff_output": {"arch_str": "ppc", "current_score": 0, "max_score": 1234},
            },
        )
    )

    await sp._update_production_scratch(
        slug="LlxRu", function_name="fn_1", melee_root=Path("."), cookies={"cf_clearance": "x", "sessionid": "y"}
    )

    assert patch_route.called
    assert compile_route.called
    body = json.loads(patch_route.calls[0].request.content)
    assert body["source_code"] == "void fn_1(void) {}"
    assert body["context"] == "struct X {};"
    assert "target_asm" not in body  # immutable on an existing scratch
    blob = "\n".join(printed)
    assert "100.0%" in blob


@respx.mock
async def test_update_no_context_sends_source_only(monkeypatch):
    import src.cli.scratch_production as sp

    _fake_console_collector(monkeypatch)
    ctx_calls = _stub_update_build(monkeypatch)

    respx.get("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu", "owner": {"id": 2, "is_anonymous": False}})
    )
    patch_route = respx.patch("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu"})
    )
    compile_route = respx.get("https://decomp.me/api/scratch/LlxRu/compile").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "compiler_output": "", "diff_output": {"arch_str": "ppc", "current_score": 0, "max_score": 10}},
        )
    )

    await sp._update_production_scratch(
        slug="LlxRu",
        function_name="fn_1",
        melee_root=Path("."),
        cookies={"cf_clearance": "x"},
        refresh_context=False,
    )

    assert patch_route.called
    assert compile_route.called
    body = json.loads(patch_route.calls[0].request.content)
    assert body["source_code"] == "void fn_1(void) {}"
    assert "context" not in body
    assert ctx_calls["n"] == 0  # context was never built


@respx.mock
async def test_update_no_compile_skips_compile(monkeypatch):
    import src.cli.scratch_production as sp

    _fake_console_collector(monkeypatch)
    _stub_update_build(monkeypatch)

    respx.get("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu", "owner": {"id": 2, "is_anonymous": False}})
    )
    patch_route = respx.patch("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu"})
    )
    compile_route = respx.get("https://decomp.me/api/scratch/LlxRu/compile").mock(
        return_value=httpx.Response(200, json={"success": True, "compiler_output": ""})
    )

    await sp._update_production_scratch(
        slug="LlxRu",
        function_name="fn_1",
        melee_root=Path("."),
        cookies={"cf_clearance": "x"},
        compile_after=False,
    )

    assert patch_route.called
    assert not compile_route.called


@respx.mock
async def test_update_dry_run_does_not_patch(monkeypatch):
    import src.cli.scratch_production as sp

    printed = _fake_console_collector(monkeypatch)
    _stub_update_build(monkeypatch)

    respx.get("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu", "owner": {"id": 2, "is_anonymous": False}})
    )
    patch_route = respx.patch("https://decomp.me/api/scratch/LlxRu").mock(
        return_value=httpx.Response(200, json={"slug": "LlxRu"})
    )

    await sp._update_production_scratch(
        slug="LlxRu",
        function_name="fn_1",
        melee_root=Path("."),
        cookies={"cf_clearance": "x"},
        dry_run=True,
    )

    assert not patch_route.called
    blob = "\n".join(printed)
    assert "DRY RUN" in blob
    assert "LlxRu" in blob


# --- CLI flag wiring + guard rails --------------------------------------------


def test_update_flags_present_in_help():
    from typer.testing import CliRunner

    from src.cli.scratch import scratch_app

    runner = CliRunner()
    result = runner.invoke(scratch_app, ["create", "--help"])
    assert result.exit_code == 0
    assert "--update" in result.output
    assert "--no-context" in result.output
    assert "--no-compile" in result.output


def test_update_requires_production(monkeypatch):
    from typer.testing import CliRunner

    from src.cli.scratch import scratch_app

    # --update without --production must error before touching production or the repo.
    runner = CliRunner()
    result = runner.invoke(scratch_app, ["create", "fn_1", "--update"])
    assert result.exit_code == 1
    assert "production" in result.output.lower()


def test_update_conflicts_with_force():
    from typer.testing import CliRunner

    from src.cli.scratch import scratch_app

    runner = CliRunner()
    result = runner.invoke(scratch_app, ["create", "fn_1", "--production", "--update", "--force"])
    assert result.exit_code == 1
    assert "force" in result.output.lower()
