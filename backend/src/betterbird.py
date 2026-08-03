"""Portable Betterbird discovery and launch helpers.

The OTP reader can use Betterbird's optional local mailbox bridge when it is
available.  Betterbird is intentionally treated as an optional integration:
the helpers in this module never assume a particular user's home directory,
and failure to find or launch Betterbird is allowed to fall back to the
read-only Thunderbird mbox reader.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable


class BetterbirdUnavailable(RuntimeError):
    """Betterbird cannot be started or was not found on this machine."""


PROCESS_NAMES = frozenset(
    {
        "betterbird",
        "betterbird-bin",
        "betterbird.exe",
    }
)


def is_betterbird_running() -> bool:
    """Return whether a Betterbird process is currently running.

    Process inspection uses only commands that are standard on the host OS;
    no third-party process-management dependency is required.
    """
    if os.name == "nt":
        return _is_betterbird_running_windows()
    return _is_betterbird_running_posix()


def discover_betterbird_executable(config: dict[str, Any]) -> Path | None:
    """Find Betterbird using an explicit override, PATH, or standard locations."""
    configured = str(config.get("auto_otp_betterbird_executable", "")).strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
        raise BetterbirdUnavailable(
            "Configured Betterbird executable does not exist: " + configured
        )

    names = (
        "betterbird.exe",
        "betterbird",
        "Betterbird",
        "betterbird-bin",
    )
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)

    for candidate in _standard_executable_candidates():
        if candidate.is_file():
            return candidate
    return None


def ensure_betterbird_running(config: dict[str, Any]) -> bool:
    """Start Betterbird when it is not running.

    Returns ``True`` when this call launched Betterbird and ``False`` when it
    was already running.  The caller is responsible for waiting for any
    mailbox bridge/extension to become ready.
    """
    if is_betterbird_running():
        return False

    executable = discover_betterbird_executable(config)
    if executable is None:
        raise BetterbirdUnavailable(
            "Betterbird was not found. Install Betterbird or set "
            "auto_otp_betterbird_executable in oura_config.json."
        )

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": os.name != "nt",
    }
    if os.name == "nt":
        # Keep the mail client independent from the desktop backend process.
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen([str(executable)], **kwargs)
    except OSError as exc:
        raise BetterbirdUnavailable(
            f"Could not launch Betterbird from {executable}: {exc}"
        ) from exc
    return True


def _standard_executable_candidates() -> Iterable[Path]:
    """Yield conventional installation paths without embedding user paths."""
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if not root:
                continue
            base = Path(root)
            yield base / "Betterbird" / "betterbird.exe"
            yield base / "Betterbird" / "Betterbird.exe"
        return

    if sys_platform_is_macos():
        yield Path("/Applications/Betterbird.app/Contents/MacOS/betterbird")
        yield Path.home() / "Applications" / "Betterbird.app" / "Contents" / "MacOS" / "betterbird"
        return

    yield Path("/usr/bin/betterbird")
    yield Path("/usr/local/bin/betterbird")
    yield Path.home() / ".local" / "bin" / "betterbird"


def sys_platform_is_macos() -> bool:
    """Small seam for tests while avoiding import-time platform branching."""
    import sys

    return sys.platform == "darwin"


def _is_betterbird_running_windows() -> bool:
    for name in PROCESS_NAMES:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        for row in csv.reader(io.StringIO(result.stdout)):
            if row and row[0].casefold() in PROCESS_NAMES:
                return True
    return False


def _is_betterbird_running_posix() -> bool:
    for name in PROCESS_NAMES:
        if name.endswith(".exe"):
            continue
        try:
            result = subprocess.run(
                ["pgrep", "-x", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return True

    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return any(
        Path(line.strip()).name.casefold() in PROCESS_NAMES
        for line in result.stdout.splitlines()
        if line.strip()
    )
