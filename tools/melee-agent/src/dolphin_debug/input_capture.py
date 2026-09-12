"""Owned Dolphin pipe requests and bounded, decoded native screenshot capture.

Pipe acceptance records host requests, not game consumption or frame timing.
"""

import errno
import hashlib
import math
import os
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path

BUTTONS = ("A", "B", "X", "Y", "Z", "START", "L", "R", "D_UP", "D_DOWN", "D_LEFT", "D_RIGHT")


def bounded(value, name, low=0, high=30):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return float(value)


@contextmanager
def deadline_lock(lock, deadline):
    if not lock.acquire(timeout=max(0, deadline - time.monotonic())):
        raise TimeoutError("Capture queue deadline exceeded")
    try:
        yield
    finally:
        lock.release()


class PipeChannel:
    def __init__(self, path, alive=lambda: True):
        self.path = Path(path)
        self.alive = alive
        self.fd = None
        self.lock = threading.RLock()

    def open(self, timeout=5):
        deadline = time.monotonic() + bounded(timeout, "pipe timeout", 0.001, 300)
        info = self.path.lstat()
        if not stat.S_ISFIFO(info.st_mode):
            raise ValueError(f"Not a FIFO: {self.path}")
        with self.lock:
            while self.fd is None:
                if not self.alive():
                    raise RuntimeError("Owned Dolphin exited while opening input pipe")
                try:
                    fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                    opened = os.fstat(fd)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        os.close(fd)
                        raise RuntimeError("FIFO identity changed")
                    self.fd = fd
                except OSError as exc:
                    if exc.errno not in (errno.ENXIO, errno.EINTR):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"No Dolphin reader for {self.path}") from exc
                    time.sleep(min(0.02, max(0, deadline - time.monotonic())))

    def write(self, command, timeout=2):
        if "\n" in command or "\r" in command:
            raise ValueError("One pipe command required")
        data = (command + "\n").encode("ascii")
        deadline = time.monotonic() + bounded(timeout, "write timeout", 0.001, 300)
        with self.lock:
            if self.fd is None:
                raise RuntimeError("Input pipe is not open")
            if len(data) > os.fpathconf(self.fd, "PC_PIPE_BUF"):
                raise ValueError("Pipe command exceeds PIPE_BUF")
            while data:
                if not self.alive():
                    raise RuntimeError("Owned Dolphin exited during input")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Input pipe write deadline exceeded")
                try:
                    count = os.write(self.fd, data)
                    if not count:
                        raise RuntimeError("Input pipe made no write progress")
                    data = data[count:]
                except OSError as exc:
                    if exc.errno not in (errno.EINTR, errno.EAGAIN):
                        raise RuntimeError(f"Dolphin input pipe failed: {exc}") from exc
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))

    def close(self):
        with self.lock:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None


class Controller:
    def __init__(self, pipe):
        self.pipe = pipe
        self.lock = threading.RLock()
        self.held = set()

    def _button(self, token, press):
        if token not in BUTTONS:
            raise ValueError(f"Unknown button {token!r}; use {', '.join(BUTTONS)}")
        self.pipe.write(f"{'PRESS' if press else 'RELEASE'} {token}")
        if press:
            self.held.add(token)
        else:
            self.held.discard(token)

    def reset(self):
        with self.lock:
            for button in BUTTONS:
                self._button(button, False)
            for stick in ("MAIN", "C"):
                self.pipe.write(f"SET {stick} 0.5 0.5")
            for trigger in ("L", "R"):
                self.pipe.write(f"SET {trigger} 0")

    def request(self, operation, token=None, x=None, y=None, duration=0.3):
        # Validate before any writes, including the finally-release path.
        if operation in ("press", "release", "tap") and token not in BUTTONS:
            raise ValueError(f"Unknown button: {token!r}")
        if operation == "tap":
            duration = bounded(duration, "tap duration", 0.01, 30)
        if operation == "stick":
            if token not in ("MAIN", "C"):
                raise ValueError("Stick must be MAIN or C")
            x, y = bounded(x, "x", 0, 1), bounded(y, "y", 0, 1)
        if operation == "trigger":
            if token not in ("L", "R"):
                raise ValueError("Trigger must be L or R")
            x = bounded(x, "trigger", 0, 1)
        start = time.time()
        with self.lock:
            if operation in ("press", "release"):
                self._button(token, operation == "press")
            elif operation == "tap":
                try:
                    self._button(token, True)
                    end = time.monotonic() + duration
                    while time.monotonic() < end:
                        if not self.pipe.alive():
                            raise RuntimeError("Owned Dolphin stopped during tap")
                        time.sleep(min(0.02, max(0, end - time.monotonic())))
                finally:
                    self._button(token, False)
            elif operation == "release-all":
                self.reset()
            elif operation == "stick":
                self.pipe.write(f"SET {token} {x} {y}")
            elif operation == "trigger":
                self.pipe.write(f"SET {token} {x}")
            else:
                raise ValueError(f"Unknown input operation: {operation}")
        return {
            "operation": operation,
            "token": token,
            "x": x,
            "y": y,
            "requested_at": start,
            "finished_at": time.time(),
            "host_dwell_seconds": duration if operation == "tap" else 0,
            "held": sorted(self.held),
            "delivery_acknowledged": False,
            "timing": "host requests; not frame-exact or acknowledged game consumption",
        }


def image_decoder():
    try:
        from PIL import Image

        return Image
    except ImportError as exc:
        raise RuntimeError("Native capture requires Pillow; install: pip install 'melee-agent[dolphin]'") from exc


def identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Screenshot is not a regular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


class NativeCapture:
    def __init__(self, pipe, root, alive=lambda: True, provenance=None):
        self.pipe = pipe
        self.root = Path(root).resolve()
        self.alive = alive
        self.provenance = provenance or {}
        self.lock = threading.Lock()

    def _paths(self):
        return {p for p in self.root.rglob("*.png") if not p.is_symlink() and p.resolve().is_relative_to(self.root)}

    def capture(
        self,
        timeout=10,
        attempts=3,
        dwell=0.15,
        release_dwell=0.15,
        settle=0,
        brightness_threshold=32,
        visible_fraction=0.001,
        accept_capture=None,
    ):
        Image = image_decoder()
        timeout = bounded(timeout, "capture timeout", 0.1, 300)
        dwell = bounded(dwell, "capture dwell", 0.01, 2)
        release_dwell = bounded(release_dwell, "release dwell", 0.01, 2)
        settle = bounded(settle, "settle", 0, 30)
        brightness_threshold = bounded(brightness_threshold, "brightness threshold", 0, 255)
        visible_fraction = bounded(visible_fraction, "visible fraction", 0, 1)
        if type(attempts) is not int or not 1 <= attempts <= 20:
            raise ValueError("attempts must be an integer from 1 to 20")
        if settle + dwell + release_dwell >= timeout:
            raise ValueError("capture timeout must exceed settling and hotkey dwell")
        requested_at, start = time.time(), time.monotonic()
        deadline = start + timeout
        with deadline_lock(self.lock, deadline):
            old = self._paths()
            rejected, seen, decode_failures = [], set(), {}

            def check():
                if not self.alive():
                    raise RuntimeError("Owned Dolphin exited during capture")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Native capture deadline exceeded; rejected={rejected}")

            def pause(seconds):
                end = min(deadline, time.monotonic() + seconds)
                while time.monotonic() < end:
                    check()
                    time.sleep(min(0.02, end - time.monotonic()))
                check()

            pause(settle)
            for attempt in range(1, attempts + 1):
                check()
                self.pipe.write("RELEASE X", timeout=max(0.001, deadline - time.monotonic()))
                pause(release_dwell)
                trigger_at = time.time()
                try:
                    self.pipe.write("PRESS X", timeout=max(0.001, deadline - time.monotonic()))
                    pause(dwell)
                finally:
                    self.pipe.write("RELEASE X", timeout=0.25)
                # Do not requeue a hotkey until a candidate was decoded/rejected.
                # A missing frame waits for the overall deadline, avoiding pending-name overwrite.
                retry = False
                while not retry:
                    check()
                    for path in sorted(self._paths() - old - seen):
                        check()
                        try:
                            before = identity(path)
                            pause(0.08)
                            if before != identity(path):
                                continue
                            with Image.open(path) as image:
                                if image.format != "PNG":
                                    raise ValueError("Not PNG")
                                image.verify()
                            with Image.open(path) as image:
                                image.load()
                                pixels = image.convert("RGB")
                                width, height = image.size
                                # Fraction of pixels with any channel above threshold tolerates letterboxing.
                                visible = sum(max(rgb) > brightness_threshold for rgb in pixels.getdata()) / (
                                    width * height
                                )
                                metadata = {
                                    "path": str(path.resolve()),
                                    "dimensions": [width, height],
                                    "visible_fraction": visible,
                                    "brightness_threshold": brightness_threshold,
                                    "minimum_visible_fraction": visible_fraction,
                                }
                                if before != identity(path):
                                    continue
                                if visible < visible_fraction:
                                    reason = "black/near-black quality filter"
                                elif accept_capture is not None:
                                    try:
                                        reason = (
                                            None if accept_capture(image, metadata) else "caller predicate rejected"
                                        )
                                    except Exception as exc:
                                        raise RuntimeError(f"Capture predicate failed: {exc}") from exc
                                else:
                                    reason = None
                            if reason:
                                rejected.append({**metadata, "reason": reason})
                                seen.add(path)
                                retry = True
                                break
                            digest = hashlib.sha256(path.read_bytes()).hexdigest()
                            if before != identity(path):
                                continue
                            check()
                            return {
                                **metadata,
                                "sha256": digest,
                                "requested_at": requested_at,
                                "trigger_at": trigger_at,
                                "observed_at": time.time(),
                                "attempts": attempt,
                                "rejections": rejected,
                                "provenance": self.provenance,
                                "predicate_requested": accept_capture is not None,
                                "predicate_passed": True if accept_capture else None,
                                "game_state_validation": "not established by capture; predicate acceptance alone is not semantic evidence",
                                "settling_host_seconds": settle,
                                "delivery_acknowledged": False,
                            }
                        except (OSError, ValueError, SyntaxError) as exc:
                            # Partial writes and temporary decode failures may recover; retain diagnostic.
                            detail = {"path": str(path), "reason": str(exc)}
                            if detail not in rejected:
                                rejected.append(detail)
                            # A short grace interval allows a paused/in-progress writer to finish.
                            # Once a stable invalid file persists, reject it and request another frame.
                            try:
                                current = identity(path)
                            except (OSError, ValueError):
                                continue
                            failed_identity, failed_at = decode_failures.get(path, (current, time.monotonic()))
                            if failed_identity != current:
                                failed_at = time.monotonic()
                            decode_failures[path] = (current, failed_at)
                            if time.monotonic() - failed_at >= 0.3:
                                seen.add(path)
                                retry = True
                                break
                    if not retry:
                        pause(0.05)
                pause(0.1)
            raise TimeoutError(f"Native capture exhausted {attempts} attempts; rejected={rejected}")
