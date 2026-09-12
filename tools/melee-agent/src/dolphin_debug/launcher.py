"""
Dolphin emulator launcher with GDB stub support.
"""

import configparser
import subprocess
import tempfile
import time
from pathlib import Path


class DolphinLauncher:
    """Manages Dolphin emulator lifecycle with GDB stub configuration."""

    # Default locations
    DEFAULT_DOLPHIN_APP = "/Applications/Dolphin.app"
    DEFAULT_CONFIG_DIR = Path.home() / "Library/Application Support/Dolphin"

    def __init__(
        self,
        dolphin_path: str | None = None,
        config_dir: Path | None = None,
        gdb_port: int = 9090,
    ):
        self.dolphin_path = dolphin_path or self.DEFAULT_DOLPHIN_APP
        self.config_dir = (
            Path(config_dir) if config_dir is not None else Path(tempfile.mkdtemp(prefix="dolphin-profile-"))
        )
        if self.config_dir.is_symlink() or self.config_dir.resolve() == self.DEFAULT_CONFIG_DIR.resolve():
            raise ValueError("Use an isolated profile, never the normal Dolphin profile")
        self.gdb_port = gdb_port
        self.process: subprocess.Popen | None = None
        self._original_config: str | None = None
        self._config_backed_up = False
        self.debugger = None
        self.log_file = None
        self.retain_config = False

    @property
    def dolphin_binary(self) -> str:
        """Path to the Dolphin executable."""
        if self.dolphin_path.endswith(".app"):
            return f"{self.dolphin_path}/Contents/MacOS/Dolphin"
        return self.dolphin_path

    @property
    def config_file(self) -> Path:
        """Path to Dolphin.ini."""
        return self.config_dir / "Config" / "Dolphin.ini"

    def _backup_config(self):
        """Backup the current config before modification."""
        if not self._config_backed_up:
            self._original_config = self.config_file.read_text() if self.config_file.exists() else None
            self._config_backed_up = True

    def _restore_config(self):
        """Restore the original config."""
        if self._config_backed_up and not self.retain_config:
            if self._original_config is not None:
                self.config_file.write_text(self._original_config)
            else:
                self.config_file.unlink(missing_ok=True)
            self._config_backed_up = False

    def configure_gdb_stub(self) -> bool:
        """
        Configure Dolphin to enable the GDB stub.

        Modifies Dolphin.ini to set GDBPort.
        """
        self._backup_config()

        config = configparser.ConfigParser()
        config.optionxform = str  # Preserve case

        if self.config_file.exists():
            config.read(self.config_file)

        if "General" not in config:
            config["General"] = {}

        config["General"]["GDBPort"] = str(self.gdb_port)

        # Ensure parent directory exists
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w") as f:
            config.write(f)

        return True

    def disable_gdb_stub(self):
        """Disable the GDB stub by setting port to -1."""
        config = configparser.ConfigParser()
        config.optionxform = str

        if self.config_file.exists():
            config.read(self.config_file)

        if "General" not in config:
            config["General"] = {}

        config["General"]["GDBPort"] = "-1"

        with open(self.config_file, "w") as f:
            config.write(f)

    def version(self):
        """Bounded binary provenance query; unsupported version flags remain explicit."""
        try:
            result = subprocess.run(
                [self.dolphin_binary, "--user", str(self.config_dir), "--version"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            output = (result.stdout or result.stderr).strip()
            return output if result.returncode == 0 and output else f"unavailable (exit {result.returncode}): {output}"
        except (OSError, subprocess.SubprocessError) as exc:
            return f"unavailable: {exc}"

    def launch(
        self,
        iso_path: str,
        headless: bool = False,
        wait_for_gdb: bool = True,
        extra_args: list | None = None,
    ) -> bool:
        """
        Launch Dolphin with the specified game.

        Args:
            iso_path: Path to the game ISO/GCM
            headless: Run in batch mode (no GUI)
            wait_for_gdb: If True, Dolphin will wait for GDB connection before starting
            extra_args: Additional command-line arguments

        Returns:
            True if launched successfully
        """
        if not Path(iso_path).exists():
            print(f"ISO not found: {iso_path}")
            return False

        if not Path(self.dolphin_binary).exists():
            print(f"Dolphin not found: {self.dolphin_binary}")
            return False

        # Configure GDB stub
        self.configure_gdb_stub()

        # Build command
        cmd = [self.dolphin_binary, "--user", str(self.config_dir), "--exec", iso_path]

        if headless:
            cmd.append("--batch")

        if extra_args:
            cmd.extend(extra_args)

        self.launch_argv = cmd
        # Launch
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=self.log_file if self.log_file is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            print(f"Launched Dolphin (PID: {self.process.pid})")
            print(f"GDB stub listening on port {self.gdb_port}")

            if wait_for_gdb:
                print("Dolphin is waiting for GDB connection...")

            return True

        except OSError as e:
            print(f"Failed to launch Dolphin: {e}")
            return False

    def wait_for_gdb_ready(self, timeout: float = 30.0):
        """Retain the first real GDB connection; never consume it with a probe."""
        from .debugger import ConnectionMode, DolphinDebugger

        if self.debugger is not None:
            return self.debugger
        deadline = time.monotonic() + timeout
        dbg = DolphinDebugger(mode=ConnectionMode.GDB, gdb_host="127.0.0.1", gdb_port=self.gdb_port)
        while time.monotonic() < deadline:
            if not self.is_running():
                raise RuntimeError("Owned Dolphin exited before GDB readiness")
            if dbg.connect(timeout=min(0.5, max(0.001, deadline - time.monotonic()))):
                self.debugger = dbg
                if not dbg.halt(timeout=max(0.001, deadline - time.monotonic())):
                    raise RuntimeError(f"Initial halt could not be confirmed: {dbg.last_error}")
                return dbg
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        raise TimeoutError("Owned Dolphin GDB readiness deadline exceeded")

    def stop(self):
        """Reap only this launcher's child process, including after forced kill."""
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5.0)
            else:
                self.process.wait()
            self.process = None
        if self.debugger is not None:
            self.debugger.disconnect()
            self.debugger = None

    def cleanup(self):
        """Stop Dolphin and restore original config."""
        self.stop()
        self._restore_config()

    def is_running(self) -> bool:
        """Check if Dolphin is still running."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False


def find_melee_iso() -> str | None:
    """
    Try to find a Melee ISO in common locations.

    Returns the path if found, None otherwise.
    """
    common_locations = [
        Path.home() / "Games",
        Path.home() / "ROMs",
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path("/Volumes"),
    ]

    patterns = ["*melee*.iso", "*melee*.gcm", "*GALE01*.iso", "*GALE01*.gcm"]

    for location in common_locations:
        if not location.exists():
            continue
        for pattern in patterns:
            matches = list(location.rglob(pattern))
            if matches:
                return str(matches[0])

    return None
