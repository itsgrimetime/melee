"""Tests for Ghidra project path resolution."""
from pathlib import Path

import pytest


class TestProjectPath:
    """Tests for ghidra_project_dir and ghidra_project_name."""

    def test_project_dir_is_under_decomp_config(self, monkeypatch, tmp_path):
        """Project lives in $DECOMP_CONFIG_DIR/ghidra by default."""
        monkeypatch.setattr("src.cli.ghidra.project.DECOMP_CONFIG_DIR", tmp_path)
        from src.cli.ghidra.project import ghidra_project_dir
        assert ghidra_project_dir() == tmp_path / "ghidra"

    def test_project_name_is_melee(self):
        from src.cli.ghidra.project import GHIDRA_PROJECT_NAME
        assert GHIDRA_PROJECT_NAME == "melee"

    def test_is_project_populated_returns_false_for_missing(self, tmp_path):
        from src.cli.ghidra.project import is_project_populated
        assert is_project_populated(tmp_path) is False

    def test_is_project_populated_returns_false_for_empty(self, tmp_path):
        """A .gpr+placeholder layout with no real program is not populated."""
        (tmp_path / "melee.gpr").touch()
        rep = tmp_path / "melee.rep" / "idata"
        rep.mkdir(parents=True)
        (rep / "~index.dat").write_bytes(b"\x00" * 16)  # placeholder
        from src.cli.ghidra.project import is_project_populated
        assert is_project_populated(tmp_path) is False

    def test_is_project_populated_returns_true_with_program_data(self, tmp_path):
        """An idata folder with non-placeholder files indicates a real program."""
        (tmp_path / "melee.gpr").touch()
        rep = tmp_path / "melee.rep" / "idata"
        rep.mkdir(parents=True)
        # Real Ghidra programs leave hex-named subdirectories under idata
        (rep / "00").mkdir()
        (rep / "00" / "0000000001.f").write_bytes(b"fake program data" * 100)
        from src.cli.ghidra.project import is_project_populated
        assert is_project_populated(tmp_path) is True
