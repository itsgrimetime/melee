from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.mwcc_debug.causal_diff.canonical import canonical_bytes
from src.mwcc_debug.causal_diff.models import CORE_BACKEND_CAPABILITIES

FUNCTION = "fn_test"
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden" / "debug_cli_help" / "debug__inspect__causal-diff.txt"
runner = CliRunner()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_help(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


def _compile_id(source_digest: str) -> str:
    return _sha256(
        canonical_bytes(
            {
                "function": FUNCTION,
                "compiler": "mwcc_233_163n",
                "target_build": "GALE01",
                "flags_digest": _sha256(b"-O4,p -proc gekko"),
                "environment_digest": _sha256(b"causal-cli-test-env"),
                "source_digest": source_digest,
            }
        )
    )


def _pcdump() -> str:
    text = (FIXTURES / "mwcc_debug" / "gm_80173EEC_pcdump.txt").read_text()
    text = text.replace("gm_80173EEC", FUNCTION)
    text, replacements = re.subn(
        r"(?m)^28\s+62\s+r29\s+13\s+16\s+0x02$",
        "28    66      r21        13      16      0x02",
        text,
    )
    assert replacements == 1
    return text


def _write_bundle(directory: Path, *, label: str, source: str) -> Path:
    directory.mkdir(parents=True)
    target_asm = [
        f"<{FUNCTION}>",
        "+230: 80 61 00 08 \tlwz     r3,8(r1)",
        "+234: 3a d5 00 01 \taddi    r22,r21,1",
        "+238: 4e 80 00 20 \tblr",
    ]
    checkdiff = {
        "function": FUNCTION,
        "classification": {},
        "target_asm": target_asm,
        "current_asm": [
            f"<{FUNCTION}>",
            "+230: 80 61 00 08 \tlwz     r3,8(r1)",
            "+234: 3a 93 00 01 \taddi    r20,r19,1",
            "+238: 4e 80 00 20 \tblr",
        ],
    }
    frame = {
        "function": FUNCTION,
        "current": {"frame_allocation_trace": {"status": "computed", "objects": []}},
        "expected": None,
    }
    artifacts = {
        "source": ("candidate.c", source.encode()),
        "checkdiff": ("checkdiff.json", (json.dumps(checkdiff) + "\n").encode()),
        "backend": ("backend.txt", _pcdump().encode()),
        "inspector": (
            "inspector.txt",
            f"FUNCTION: {FUNCTION}\nSTATEMENTS (IR):\n---\n".encode(),
        ),
        "frame_report": ("frame.json", (json.dumps(frame) + "\n").encode()),
    }
    digests: dict[str, str] = {}
    for name, (filename, data) in artifacts.items():
        (directory / filename).write_bytes(data)
        digests[name] = _sha256(data)

    source_digest = digests["source"]
    payload = {
        "schema_version": "causal-frontier-bundle.v1",
        "label": label,
        "function": FUNCTION,
        "compile": {
            "id": _compile_id(source_digest),
            "compiler": "mwcc_233_163n",
            "target_build": "GALE01",
            "flags_digest": _sha256(b"-O4,p -proc gekko"),
            "environment_digest": _sha256(b"causal-cli-test-env"),
            "source_digest": source_digest,
            "expected_assembly_digest": _sha256(("\n".join(target_asm) + "\n").encode()),
        },
        "artifacts": {
            "source": {"path": artifacts["source"][0], "sha256": source_digest},
            "checkdiff": {"path": artifacts["checkdiff"][0], "sha256": digests["checkdiff"]},
            "backend": [
                {
                    "path": artifacts["backend"][0],
                    "sha256": digests["backend"],
                    "format": "mwcc-debug-pcdump",
                    "capabilities": sorted(CORE_BACKEND_CAPABILITIES),
                }
            ],
            "inspector": {"path": artifacts["inspector"][0], "sha256": digests["inspector"]},
            "frame_report": {
                "path": artifacts["frame_report"][0],
                "sha256": digests["frame_report"],
            },
        },
        "producer_versions": {
            "checkdiff": "checkdiff-json.v1",
            "mwcc_debug": "mwcc-debug-pcdump.v1",
            "mwcc_inspect": "mwcc-inspect-text.v1",
            "frame_report": "frame-reservations.v1",
        },
    }
    manifest = directory / "bundle.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def write_cli_bundles(tmp_path: Path) -> tuple[Path, Path]:
    paired = _write_bundle(
        tmp_path / "paired",
        label="paired",
        source=f"void {FUNCTION}(void) {{ int paired = 0; }}\n",
    )
    direct = _write_bundle(
        tmp_path / "direct",
        label="direct",
        source=f"void {FUNCTION}(void) {{ int direct = 0; }}\n",
    )
    return paired, direct


def _args(paired: Path, direct: Path, *extra: str) -> list[str]:
    return [
        "debug",
        "inspect",
        "causal-diff",
        "-f",
        FUNCTION,
        "--frontier",
        f"paired={paired}",
        "--frontier",
        f"direct={direct}",
        "--retail-offset",
        "0x234",
        *extra,
    ]


def _report(status: str):
    from src.mwcc_debug.causal_diff.effects import DerivedEffects
    from src.mwcc_debug.causal_diff.inference import AnalysisStatus, CausalDiffReport

    return CausalDiffReport(
        schema_version="causal-diff-report.v1",
        analysis_id="analysis-test",
        analysis_status=AnalysisStatus(status),
        function=FUNCTION,
        effects=DerivedEffects(allocator_effects=(), stack_effects=(), pairs=(), abstentions=()),
        verdicts=(),
        comparisons=(),
        applied_rules=(),
        missing_evidence=(),
        warnings=(),
    )


def test_causal_diff_json_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.mwcc_debug.causal_diff import commands

    paired, direct = write_cli_bundles(tmp_path)
    monkeypatch.setattr(commands, "run_causal_diff", lambda _options: _report("complete"))

    result = runner.invoke(app, _args(paired, direct, "--json"))

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "causal-diff-report.v1"
    assert payload["analysis_status"] == "complete"


def test_causal_diff_help_marks_all_required_inputs() -> None:
    result = runner.invoke(app, ["debug", "inspect", "causal-diff", "--help"])

    assert result.exit_code == 0
    assert result.stdout.count("[required]") == 3


def test_causal_diff_help_matches_its_golden() -> None:
    result = runner.invoke(app, ["debug", "inspect", "causal-diff", "--help"])

    assert result.exit_code == 0
    assert _canonical_help(result.stdout) == _canonical_help(GOLDEN.read_text())


def test_causal_diff_never_spawns_or_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.mwcc_debug.causal_diff.commands import CausalDiffOptions, run_causal_diff
    from src.mwcc_debug.causal_diff.store import InMemoryEvidenceStore

    paired, direct = write_cli_bundles(tmp_path)
    stores: list[InMemoryEvidenceStore] = []

    def store_factory() -> InMemoryEvidenceStore:
        store = InMemoryEvidenceStore()
        stores.append(store)
        return store

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("subprocess forbidden"))
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: pytest.fail("write forbidden"))
    monkeypatch.setattr(Path, "write_bytes", lambda *args, **kwargs: pytest.fail("write forbidden"))

    report = run_causal_diff(
        CausalDiffOptions(
            function=FUNCTION,
            frontiers=(("paired", paired), ("direct", direct)),
            retail_offset=0x234,
        ),
        store_factory=store_factory,
    )

    assert report.function == FUNCTION
    assert len(stores) == 1


def test_run_causal_diff_threads_evidence_depth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.causal_diff import commands

    paired, direct = write_cli_bundles(tmp_path)
    original = commands.build_report
    observed_depths: list[int] = []

    def capture_depth(graphs, effects, comparisons, *, evidence_depth: int = 4):
        observed_depths.append(evidence_depth)
        return original(
            graphs,
            effects,
            comparisons,
            evidence_depth=evidence_depth,
        )

    monkeypatch.setattr(commands, "build_report", capture_depth)
    commands.run_causal_diff(
        commands.CausalDiffOptions(
            function=FUNCTION,
            frontiers=(("paired", paired), ("direct", direct)),
            retail_offset=0x234,
            evidence_depth=5,
        )
    )

    assert observed_depths == [5]


def test_input_error_is_exit_two(tmp_path: Path) -> None:
    paired, direct = write_cli_bundles(tmp_path)
    (paired.parent / "candidate.c").write_text("digest mismatch\n")

    result = runner.invoke(app, _args(paired, direct, "--json"))

    assert result.exit_code == 2
    assert "digest mismatch" in result.stderr
    assert "causal-diff-report.v1" not in result.stdout


@pytest.mark.parametrize("count", (1, 3))
def test_cli_requires_exactly_two_frontiers(tmp_path: Path, count: int) -> None:
    paired, direct = write_cli_bundles(tmp_path)
    values = [f"paired={paired}", f"direct={direct}", f"third={paired}"][:count]
    args = ["debug", "inspect", "causal-diff", "-f", FUNCTION]
    for value in values:
        args.extend(("--frontier", value))
    args.extend(("--retail-offset", "0x234"))

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "exactly two" in result.stderr


@pytest.mark.parametrize(
    ("first", "second", "message"),
    (
        ("paired", "paired", "unique"),
        ("bad!", "direct", "[A-Za-z0-9_-]+"),
    ),
)
def test_cli_rejects_invalid_frontier_labels(tmp_path: Path, first: str, second: str, message: str) -> None:
    paired, direct = write_cli_bundles(tmp_path)
    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "causal-diff",
            "-f",
            FUNCTION,
            "--frontier",
            f"{first}={paired}",
            "--frontier",
            f"{second}={direct}",
            "--retail-offset",
            "0x234",
        ],
    )

    assert result.exit_code == 2
    assert message in result.stderr


def test_cli_rejects_label_manifest_mismatch(tmp_path: Path) -> None:
    paired, direct = write_cli_bundles(tmp_path)
    result = runner.invoke(
        app,
        [
            "debug",
            "inspect",
            "causal-diff",
            "-f",
            FUNCTION,
            "--frontier",
            f"alias={paired}",
            "--frontier",
            f"direct={direct}",
            "--retail-offset",
            "0x234",
        ],
    )

    assert result.exit_code == 2
    assert "does not match manifest label" in result.stderr


@pytest.mark.parametrize("offset", ("wat", "-1"))
def test_cli_rejects_invalid_retail_offset(tmp_path: Path, offset: str) -> None:
    paired, direct = write_cli_bundles(tmp_path)
    args = _args(paired, direct)
    args[-1] = offset

    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "retail offset" in result.stderr.lower()


@pytest.mark.parametrize("depth", ("0", "9"))
def test_cli_rejects_invalid_evidence_depth(tmp_path: Path, depth: str) -> None:
    paired, direct = write_cli_bundles(tmp_path)

    result = runner.invoke(app, _args(paired, direct, "--evidence-depth", depth))

    assert result.exit_code == 2
    assert "evidence-depth" in result.stderr


def test_cli_accepts_operand_scoped_assertion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.mwcc_debug.causal_diff import commands

    paired, direct = write_cli_bundles(tmp_path)
    captured = []

    def fake_run(options):
        captured.append(options)
        return _report("complete")

    monkeypatch.setattr(commands, "run_causal_diff", fake_run)
    result = runner.invoke(
        app,
        _args(paired, direct, "--frontier-node", "paired:def:0=gpr:66", "--json"),
    )

    assert result.exit_code == 0
    assert captured[0].assertions == ("paired:def:0=gpr:66",)


@pytest.mark.parametrize(
    "assertion",
    ("paired=gpr:66", "paired:arg:0=gpr:66", "unknown:def:0=gpr:66"),
)
def test_cli_rejects_invalid_operand_assertion(tmp_path: Path, assertion: str) -> None:
    paired, direct = write_cli_bundles(tmp_path)

    result = runner.invoke(app, _args(paired, direct, "--frontier-node", assertion))

    assert result.exit_code == 2
    assert "frontier-node" in result.stderr


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    (("abstained", 3), ("partial", 0)),
)
def test_cli_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    expected_exit: int,
) -> None:
    from src.mwcc_debug.causal_diff import commands

    paired, direct = write_cli_bundles(tmp_path)
    monkeypatch.setattr(commands, "run_causal_diff", lambda _options: _report(status))

    result = runner.invoke(app, _args(paired, direct, "--json"))

    assert result.exit_code == expected_exit
    assert json.loads(result.stdout)["analysis_status"] == status


def test_cli_evidence_depth_changes_rendered_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.mwcc_debug.causal_diff import commands

    paired, direct = write_cli_bundles(tmp_path)
    monkeypatch.setattr(
        commands,
        "run_causal_diff",
        lambda options: _report("complete" if options.evidence_depth == 5 else "abstained"),
    )

    shallow = runner.invoke(app, _args(paired, direct, "--evidence-depth", "4", "--json"))
    deep = runner.invoke(app, _args(paired, direct, "--evidence-depth", "5", "--json"))

    assert shallow.exit_code == 3
    assert json.loads(shallow.stdout)["analysis_status"] == "abstained"
    assert deep.exit_code == 0
    assert json.loads(deep.stdout)["analysis_status"] == "complete"
