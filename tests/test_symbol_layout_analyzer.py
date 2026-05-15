"""Tests for the data/symbol layout analyzer."""

import importlib.util
import sys
from pathlib import Path


def load_symbol_layout_analyzer():
    path = Path(__file__).parents[1] / "tools" / "symbol-layout-analyzer.py"
    spec = importlib.util.spec_from_file_location("symbol_layout_analyzer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_symbols(root: Path, text: str) -> None:
    path = root / "config" / "GALE01" / "symbols.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_analyzer_flags_tail_string_after_adjacent_data(tmp_path):
    analyzer = load_symbol_layout_analyzer()
    write_symbols(
        tmp_path,
        "\n".join(
            [
                "data_blob = .data:0x80400000; // type:object size:0x10 scope:local data:4byte",
                "tail_string = .data:0x80400010; // type:object size:0x8 scope:local hidden data:string",
            ]
        ),
    )

    result = analyzer.analyze_symbol(tmp_path, "tail_string")

    kinds = {finding["kind"] for finding in result["findings"]}
    assert "tail-string-or-padding" in kinds
    assert "missing-source-declaration" in kinds


def test_analyzer_flags_static_global_scope_mismatch(tmp_path):
    analyzer = load_symbol_layout_analyzer()
    write_symbols(
        tmp_path,
        "shared_table = .data:0x80400100; // type:object size:0x20 scope:global data:4byte",
    )
    source = tmp_path / "src" / "melee" / "ft" / "file.c"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("static int shared_table[8];\n")

    result = analyzer.analyze_symbol(tmp_path, "shared_table")

    assert any(finding["kind"] == "scope-mismatch" for finding in result["findings"])


def test_analyzer_includes_map_layout_evidence(tmp_path):
    analyzer = load_symbol_layout_analyzer()
    write_symbols(
        tmp_path,
        "shared_table = .data:0x80400100; // type:object size:0x20 scope:global data:4byte",
    )
    map_path = tmp_path / "build" / "GALE01" / "GALE01.map"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text("80400100 00000020 shared_table build/GALE01/src/melee/mn/file.o\n")

    result = analyzer.analyze_symbol(tmp_path, "shared_table")

    assert result["layout_artifacts"][0]["path"] == "build/GALE01/GALE01.map"
    assert any(finding["kind"] == "build-layout-evidence" for finding in result["findings"])
