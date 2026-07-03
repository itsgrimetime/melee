import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tools.mwcc_retro import struct_map  # noqa: E402


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
    }
    assert struct_map.validate_required_backend_map(table) == []


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
