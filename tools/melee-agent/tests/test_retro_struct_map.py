import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import struct_map  # noqa: E402


def _load_gc125n_table():
    return json.loads((REPO / "tools/mwcc_retro/tables/gc_125n.json").read_text())


def test_live_gc125n_table_satisfies_required_backend_map_gate():
    table = _load_gc125n_table()

    assert struct_map.validate_required_backend_map(table) == []
    assert struct_map.validate_backend_ig_snapshot_capability(table) == []
    assert struct_map.validate_backend_pcode_snapshot_capability(table) == []


def test_live_gc125n_table_satisfies_backend_reader_gate():
    table = _load_gc125n_table()

    assert struct_map.validate_backend_reader_capability(table) == []


def test_required_gc125n_backend_keys_validate():
    table = {
        "compiler": "1.2.5n",
        "entries": {
            key: {
                "va": 0x400000 + i,
                "confidence": "live-invariant",
                "provenance": "fixture",
            }
            for i, key in enumerate(struct_map.REQUIRED_GC125N_BACKEND_KEYS)
        },
        "structs": {
            name: {
                "confidence": "manual-disassembly-confirmed",
                "fields": fields,
            }
            for name, fields in struct_map.REQUIRED_STRUCT_FIELDS.items()
        },
        "backend_reader": {
            "complete": True,
            "event_families": list(struct_map.REQUIRED_BACKEND_READER_FAMILIES),
        },
    }
    assert struct_map.validate_required_backend_map(table) == []
    assert struct_map.validate_backend_reader_capability(table) == []


def test_missing_required_key_reports_error():
    table = {"compiler": "1.2.5n", "entries": {}, "structs": {}}
    errors = struct_map.validate_required_backend_map(table)
    assert any("missing required backend entry codegen_start" in e for e in errors)
    assert any("missing required struct IGNode" in e for e in errors)


def test_low_confidence_required_key_reports_error():
    table = {
        "compiler": "1.2.5n",
        "entries": {
            "codegen_start": {
                "va": 0x4351C0,
                "confidence": "byte-correlate",
                "provenance": "fixture",
            }
        },
        "structs": {},
    }
    errors = struct_map.validate_required_backend_map(table)
    assert any("codegen_start confidence byte-correlate below required gate" in e for e in errors)


def test_malformed_top_level_collections_report_errors_without_crashing():
    table = {"compiler": "1.2.5n", "entries": ["bad"], "structs": "bad"}
    errors = struct_map.validate_required_backend_map(table)
    assert "entries must be object" in errors
    assert "structs must be object" in errors
    assert any("missing required backend entry codegen_start" in e for e in errors)
    assert any("missing required struct IGNode" in e for e in errors)


def test_malformed_nested_values_report_errors_without_crashing():
    table = {
        "compiler": "1.2.5n",
        "entries": {
            "codegen_start": "bad",
        },
        "structs": {
            "IGNode": "bad",
            "PCode": {
                "confidence": "manual-disassembly-confirmed",
                "fields": "bad",
            },
        },
    }
    errors = struct_map.validate_required_backend_map(table)
    assert "backend entry codegen_start must be object" in errors
    assert "struct IGNode must be object" in errors
    assert "struct PCode fields must be object" in errors


def test_backend_reader_capability_requires_complete_event_families():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "event_families": ["function_start", "regclass"],
        },
    }

    errors = struct_map.validate_backend_reader_capability(table)

    assert "backend_reader.complete is not true" in errors
    assert any("backend_reader missing event family pcode_instruction" in e for e in errors)


def test_missing_backend_reader_capability_reports_error():
    errors = struct_map.validate_backend_reader_capability({"compiler": "1.2.5n"})

    assert "missing backend_reader capability gate" in errors


def test_backend_ig_snapshot_capability_requires_partial_event_families():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "event_families": list(struct_map.REQUIRED_BACKEND_READER_FAMILIES),
        },
    }

    errors = struct_map.validate_backend_ig_snapshot_capability(table)

    assert "backend_reader.partial_event_families must be list" in errors


def test_backend_ig_snapshot_capability_reports_missing_partial_family():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "partial_event_families": [
                "function_start",
                "backend_marker",
                "regclass",
                "node",
            ],
        },
    }

    errors = struct_map.validate_backend_ig_snapshot_capability(table)

    assert "backend_reader.complete is not true" not in errors
    assert "backend_reader missing partial event family edge" in errors
    assert "backend_reader missing partial event family coalesce_mapping" in errors
    assert "backend_reader missing partial event family coalesce_mapping_empty" in errors
    assert "backend_reader missing partial event family simplify_order" in errors
    assert "backend_reader missing partial event family select_order" in errors
    assert "backend_reader missing partial event family color_decision" in errors


def test_backend_ig_snapshot_capability_rejects_extra_partial_family():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "partial_event_families": [
                "function_start",
                "backend_marker",
                "regclass",
                "node",
                "edge",
                "color_decision",
                "frame_state",
            ],
        },
    }

    errors = struct_map.validate_backend_ig_snapshot_capability(table)

    assert "backend_reader unexpected partial event family frame_state" in errors


def test_backend_ig_snapshot_capability_rejects_missing_or_malformed_backend_reader():
    assert struct_map.validate_backend_ig_snapshot_capability({"compiler": "1.2.5n"}) == [
        "missing backend_reader capability gate"
    ]
    assert struct_map.validate_backend_ig_snapshot_capability(
        {"compiler": "1.2.5n", "backend_reader": "bad"}
    ) == ["backend_reader must be object"]


def test_backend_pcode_snapshot_capability_requires_partial_event_families():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "event_families": list(struct_map.REQUIRED_BACKEND_READER_FAMILIES),
        },
    }

    errors = struct_map.validate_backend_pcode_snapshot_capability(table)

    assert "backend_reader.partial_pcode_event_families must be list" in errors


def test_backend_pcode_snapshot_capability_reports_missing_partial_family():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "partial_pcode_event_families": [
                "function_start",
                "backend_marker",
                "block",
            ],
        },
    }

    errors = struct_map.validate_backend_pcode_snapshot_capability(table)

    assert "backend_reader.complete is not true" not in errors
    assert "backend_reader missing partial PCode event family pcode_instruction" in errors


def test_backend_pcode_snapshot_capability_requires_reader_struct_fields():
    table = {
        "compiler": "1.2.5n",
        "structs": {
            "PCode": {
                "confidence": "manual-disassembly-confirmed",
                "fields": {
                    "next": 0x00,
                    "opcode": 0x14,
                },
            },
        },
        "backend_reader": {
            "complete": False,
            "partial_pcode_event_families": list(
                struct_map.REQUIRED_BACKEND_PCODE_SNAPSHOT_FAMILIES
            ),
        },
    }

    errors = struct_map.validate_backend_pcode_snapshot_capability(table)

    assert "missing required PCode snapshot struct PCodeBlock" in errors
    assert (
        "struct PCode.arg_count expected offset 0x1a, got None"
        in errors
    )


def test_backend_pcode_snapshot_capability_rejects_extra_partial_family():
    table = {
        "compiler": "1.2.5n",
        "backend_reader": {
            "complete": False,
            "partial_pcode_event_families": [
                "function_start",
                "backend_marker",
                "block",
                "pcode_instruction",
                "node",
            ],
        },
    }

    errors = struct_map.validate_backend_pcode_snapshot_capability(table)

    assert "backend_reader unexpected partial PCode event family node" in errors


def test_backend_pcode_snapshot_capability_rejects_missing_or_malformed_backend_reader():
    assert struct_map.validate_backend_pcode_snapshot_capability({"compiler": "1.2.5n"}) == [
        "missing backend_reader capability gate"
    ]
    assert struct_map.validate_backend_pcode_snapshot_capability(
        {"compiler": "1.2.5n", "backend_reader": "bad"}
    ) == ["backend_reader must be object"]
