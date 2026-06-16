from typer.testing import CliRunner

import src.cli.debug as debugcli
from src.mwcc_debug import first_divergence as fd
from src.mwcc_debug import colorgraph_parser


runner = CliRunner()


def _fact() -> fd.AllocatorFact:
    return fd.AllocatorFact(
        class_id=1,
        ig_idx=39,
        case=fd.DivergenceCase.C2_STICKY_POOL,
        iter_idx=26,
        baseline_reg=28,
        target_reg=26,
        coalesced_nodes=(),
        coalesced_root=None,
        coalesced_root_phys=None,
        blocker_ig=None,
        blocker_dependency=False,
        working_mask=frozenset(),
        cap_hit=False,
        earlier_unmapped_warning=False,
        local_target="change upstream virtual order",
    )


def test_first_divergence_source_falls_back_to_prefix_source_file(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "melee"
    source_path = root / "src" / "melee" / "mn" / "mndiagram.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("void mnDiagram_80240D94(void) {}\n")
    dump_path = tmp_path / "dump.txt"
    dump_path.write_text("pcdump")

    class FakeParsedFunction:
        name = "mnDiagram_DrawCellNumber"

        def last_precolor_pass(self):
            return object()

    captured = {}

    def fake_attach_source_ideas(
        fact,
        source_text,
        fn_name,
        pre_pass,
        source_file=None,
    ):
        captured.update(
            source_text=source_text,
            fn_name=fn_name,
            pre_pass=pre_pass,
            source_file=source_file,
        )
        return fd.SourceIdea(
            ig_idx=fact.ig_idx,
            var_name=None,
            confidence=None,
            alternates=(),
            ideas=("source attached",),
            source_kind="fpr-temp",
            source_expression="fmuls f39,f32,f51",
            source_file=source_file,
        )

    monkeypatch.setattr(debugcli, "DEFAULT_MELEE_ROOT", root)
    monkeypatch.setattr(debugcli, "_find_unit_for_function", lambda *a: None)
    monkeypatch.setattr(debugcli, "_resolve_pcdump_path", lambda *a, **k: dump_path)
    monkeypatch.setattr(debugcli, "parse_pcdump", lambda text: [FakeParsedFunction()])
    monkeypatch.setattr(colorgraph_parser, "parse_hook_events", lambda text: object())
    monkeypatch.setattr(colorgraph_parser, "find_function", lambda events, name: object())
    monkeypatch.setattr(
        fd,
        "analyze_first_divergence",
        lambda fev, target: fd.FirstDivergenceReport(_fact(), None),
    )
    monkeypatch.setattr(fd, "attach_source_ideas", fake_attach_source_ideas)

    result = runner.invoke(
        debugcli.debug_app,
        [
            "inspect",
            "first-divergence",
            str(dump_path),
            "-f",
            "mnDiagram_DrawCellNumber",
            "--class",
            "1",
            "--force-phys",
            "39:26",
            "--source",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["source_text"] == "void mnDiagram_80240D94(void) {}\n"
    assert captured["fn_name"] == "mnDiagram_DrawCellNumber"
    assert captured["source_file"] == "src/melee/mn/mndiagram.c"
    assert "source: fmuls f39,f32,f51" in result.output
