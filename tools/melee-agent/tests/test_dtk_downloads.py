from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_download_tool_uses_rosetta_dtk_on_macos_arm64(monkeypatch) -> None:
    download_tool = _load_module(
        REPO_ROOT / "tools" / "download_tool.py",
        "download_tool_under_test",
    )
    uname = platform.uname()._replace(system="Darwin", machine="arm64")

    monkeypatch.setattr(download_tool.platform, "uname", lambda: uname)

    assert download_tool.dtk_url("v1.8.3").endswith("/dtk-macos-x86_64")


def test_checkdiff_download_uses_rosetta_dtk_on_macos_arm64(monkeypatch) -> None:
    checkdiff = _load_module(
        REPO_ROOT / "tools" / "checkdiff.py",
        "checkdiff_under_test",
    )

    monkeypatch.setattr(checkdiff.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(checkdiff.platform, "machine", lambda: "arm64")

    assert checkdiff.get_dtk_download_url().endswith("/dtk-macos-x86_64")
