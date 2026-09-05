# tools/melee-agent/tests/test_checkdiff_checker.py
from unittest import mock
from src.mwcc_debug.checkdiff_checker import CheckdiffChecker


def _checker(tmp_path, build_obj):
    return CheckdiffChecker(function="fn_x", melee_root=tmp_path, build_obj_path=build_obj)


def test_is_clean_false_when_obj_missing(tmp_path):
    # a real editor must produce a readable .o; a missing artifact degrades to
    # "not clean" rather than crashing the loop, and no subprocess runs.
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    with mock.patch("subprocess.run") as m:
        assert _checker(tmp_path, build_obj).is_clean(tmp_path / "nope.o") is False
        assert not m.called
    assert build_obj.read_bytes() == b"ORIG"


def test_is_clean_true_on_checkdiff_exit_0(tmp_path):
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    new_obj = tmp_path / "new.o"; new_obj.write_bytes(b"NEW")
    ck = _checker(tmp_path, build_obj)
    with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout='{"match": true}')) as m:
        assert ck.is_clean(new_obj) is True
        assert m.called
    assert build_obj.read_bytes() == b"ORIG"          # restored after the check

def test_uses_fingerprint_free_env(tmp_path):
    # the verdict must NOT record to the shared attempts DB (review P1): the env
    # passed to checkdiff must carry CHECKDIFF_NO_FINGERPRINT=1.
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    new_obj = tmp_path / "new.o"; new_obj.write_bytes(b"NEW")
    captured = {}
    def fake_run(cmd, **kw): captured.update(kw); return mock.Mock(returncode=0, stdout='{"match": true}')
    with mock.patch("subprocess.run", side_effect=fake_run):
        _checker(tmp_path, build_obj).is_clean(new_obj)
    assert captured["env"].get("CHECKDIFF_NO_FINGERPRINT") == "1"

def test_is_clean_false_on_mismatch(tmp_path):
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    new_obj = tmp_path / "new.o"; new_obj.write_bytes(b"NEW")
    with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout='{"match": false}')):
        assert _checker(tmp_path, build_obj).is_clean(new_obj) is False
    assert build_obj.read_bytes() == b"ORIG"

def test_is_clean_false_on_checkdiff_error(tmp_path):
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    new_obj = tmp_path / "new.o"; new_obj.write_bytes(b"NEW")
    with mock.patch("subprocess.run", return_value=mock.Mock(returncode=2, stdout="")):
        assert _checker(tmp_path, build_obj).is_clean(new_obj) is False
    assert build_obj.read_bytes() == b"ORIG"          # restored even on error

def test_is_clean_false_on_none_obj(tmp_path):
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    # no subprocess should run when there's no .o to check
    with mock.patch("subprocess.run") as m:
        assert _checker(tmp_path, build_obj).is_clean(None) is False
        assert not m.called

def test_restores_build_obj_even_if_checkdiff_raises(tmp_path):
    build_obj = tmp_path / "unit.o"; build_obj.write_bytes(b"ORIG")
    new_obj = tmp_path / "new.o"; new_obj.write_bytes(b"NEW")
    with mock.patch("subprocess.run", side_effect=RuntimeError("boom")):
        try:
            _checker(tmp_path, build_obj).is_clean(new_obj)
        except RuntimeError:
            pass
    assert build_obj.read_bytes() == b"ORIG"          # finally-restore holds
