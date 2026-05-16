"""Tests for Ghidra install auto-detection."""
from pathlib import Path

import pytest


class TestDetectGhidraInstall:
    """Tests for detect_ghidra_install — finds a usable Ghidra install."""

    @pytest.fixture
    def detect(self):
        from src.cli.ghidra.detect import detect_ghidra_install
        return detect_ghidra_install

    def test_env_var_overrides_detection(self, detect, tmp_path, monkeypatch):
        """GHIDRA_INSTALL_DIR (if valid) takes precedence over auto-detection."""
        # Build a valid Ghidra install layout
        install = tmp_path / "ghidra_install"
        install.mkdir()
        (install / "application.properties").write_text("application.name=Ghidra\n")
        monkeypatch.setenv("GHIDRA_INSTALL_DIR", str(install))
        assert detect() == install

    def test_invalid_env_var_falls_through_to_detection(self, detect, tmp_path, monkeypatch):
        """A non-Ghidra GHIDRA_INSTALL_DIR is ignored; detection continues."""
        monkeypatch.setenv("GHIDRA_INSTALL_DIR", str(tmp_path))  # no application.properties
        # No homebrew etc. installed in test env → returns None
        # Patch the search paths to empty
        from src.cli.ghidra import detect as detect_mod
        monkeypatch.setattr(detect_mod, "_SEARCH_PATHS", [])
        assert detect() is None

    def test_finds_homebrew_install(self, detect, tmp_path, monkeypatch):
        """Detects a Ghidra install under a homebrew-shaped path."""
        # Simulate /opt/homebrew/Cellar/ghidra/12.0.1/libexec layout
        cellar = tmp_path / "Cellar" / "ghidra"
        install = cellar / "12.0.1" / "libexec"
        install.mkdir(parents=True)
        (install / "application.properties").write_text("application.name=Ghidra\n")

        monkeypatch.delenv("GHIDRA_INSTALL_DIR", raising=False)
        from src.cli.ghidra import detect as detect_mod
        monkeypatch.setattr(detect_mod, "_SEARCH_PATHS", [cellar])
        assert detect() == install

    def test_validates_via_application_properties(self, detect, tmp_path, monkeypatch):
        """A directory without application.properties is not a valid install."""
        fake = tmp_path / "fake_ghidra"
        fake.mkdir()
        monkeypatch.setenv("GHIDRA_INSTALL_DIR", str(fake))
        from src.cli.ghidra import detect as detect_mod
        monkeypatch.setattr(detect_mod, "_SEARCH_PATHS", [])
        assert detect() is None

    def test_finds_install_with_nested_ghidra_subdir(self, detect, tmp_path, monkeypatch):
        """Homebrew layout: application.properties lives at <root>/libexec/Ghidra/."""
        # Simulate the real homebrew layout
        cellar = tmp_path / "Cellar" / "ghidra"
        version = cellar / "12.0.1"
        libexec = version / "libexec"
        (libexec / "Ghidra").mkdir(parents=True)
        (libexec / "Ghidra" / "application.properties").write_text("application.name=Ghidra\n")
        # libexec itself does NOT have application.properties (that's the bug being fixed)
        monkeypatch.delenv("GHIDRA_INSTALL_DIR", raising=False)
        from src.cli.ghidra import detect as detect_mod
        monkeypatch.setattr(detect_mod, "_SEARCH_PATHS", [cellar])
        # Should detect libexec as the install dir (pyghidra accepts it)
        assert detect() == libexec
