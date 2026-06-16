import pytest

import src.cli.debug as debugcli


def test_source_restore_guard_restores_after_exception(tmp_path):
    source = tmp_path / "source.c"
    original = "void f(void) {}\n"
    source.write_text(original)

    with pytest.raises(RuntimeError, match="probe failed"):
        with debugcli._source_restore_guard(source, original):
            assert source in debugcli._ACTIVE_SOURCE_RESTORES
            source.write_text("void f(void) { duplicate; }\n")
            raise RuntimeError("probe failed")

    assert source.read_text() == original
    assert source not in debugcli._ACTIVE_SOURCE_RESTORES
