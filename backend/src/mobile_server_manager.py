import atexit
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import List, Optional

from .config import config_manager
from .paths import get_user_data_dir

logger = logging.getLogger("MobileServerManager")


@dataclass
class MobileServerState:
    running: bool
    status: str
    pid: Optional[int] = None


class MobileServerManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._host: Optional[str] = None
        self._port: Optional[int] = None
        self._last_status = "Stopped"
        atexit.register(self.stop)

    def state(self) -> MobileServerState:
        with self._lock:
            if self._process and self._process.poll() is None:
                return MobileServerState(
                    running=True,
                    status=f"Running on {self._host}:{self._port}",
                    pid=self._process.pid,
                )

            if self._process and self._process.poll() is not None:
                exit_code = self._process.returncode
                self._process = None
                self._last_status = f"Stopped unexpectedly with exit code {exit_code}"
                return MobileServerState(
                    running=False,
                    status=self._last_status,
                )

            return MobileServerState(running=False, status=self._last_status)

    def reconcile(self) -> MobileServerState:
        settings = config_manager.get_config()
        enabled = bool(settings.get("mobile_sync_enabled", False))
        token = (settings.get("mobile_sync_token", "") or "").strip()
        host = (settings.get("mobile_sync_bind_host", "0.0.0.0") or "0.0.0.0").strip()
        port = int(settings.get("mobile_sync_port", 8037))

        with self._lock:
            self._clear_exited_process()

            if not enabled:
                self._stop_locked()
                self._last_status = "Disabled in settings"
                return MobileServerState(False, self._last_status)

            if not token:
                self._stop_locked()
                self._last_status = "Waiting for a sync token"
                return MobileServerState(False, self._last_status)

            if self._process and self._process.poll() is None:
                if self._host == host and self._port == port:
                    return MobileServerState(
                        running=True,
                        status=f"Running on {host}:{port}",
                        pid=self._process.pid,
                    )
                self._stop_locked()

            self._start_locked(host, port)
            if self._process and self._process.poll() is None:
                self._last_status = f"Running on {host}:{port}"
                return MobileServerState(
                    running=True,
                    status=self._last_status,
                    pid=self._process.pid,
                )

            return MobileServerState(False, self._last_status)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _clear_exited_process(self) -> None:
        if self._process and self._process.poll() is not None:
            logger.warning(
                "Mobile sync server exited pid=%s code=%s",
                self._process.pid,
                self._process.returncode,
            )
            self._last_status = (
                f"Stopped unexpectedly with exit code {self._process.returncode}"
            )
            self._process = None

    def _kill_stale_process_on_port(self, port: int) -> None:
        """On Windows, find and kill any process already listening on the target port."""
        if os.name != "nt":
            return
        try:
            import subprocess as sp
            result = sp.run(
                ["cmd", "/c", f"netstat -ano | findstr :{port}"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
                    stale_pid = parts[-1]
                    logger.warning("Port %s is already in use by PID %s. Killing stale process.", port, stale_pid)
                    sp.run(["taskkill", "/F", "/PID", stale_pid], capture_output=True, check=False)
        except Exception as exc:
            logger.warning("Failed to kill stale process on port %s: %s", port, exc)

    def _start_locked(self, host: str, port: int) -> None:
        # Clear any stale process holding our port
        self._kill_stale_process_on_port(port)

        command = self._build_command(host, port)
        env = os.environ.copy()
        env["OURACLE_DISABLE_MOBILE_AUTOSTART"] = "1"
        env["OURACLE_MOBILE_API_ONLY"] = "1"
        env["OURACLE_MOBILE_HOST"] = host
        env["OURACLE_MOBILE_PORT"] = str(port)

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        cwd = self._working_directory()

        log_path = os.path.join(get_user_data_dir(), "mobile_server.log")
        logger.info("Starting mobile sync server host=%s port=%s command=%s log=%s", host, port, command, log_path)
        try:
            self._log_file = open(log_path, "a", encoding="utf-8")
            self._process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=self._log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            self._host = host
            self._port = port
            self._last_status = f"Running on {host}:{port}"
        except OSError as exc:
            self._process = None
            self._host = None
            self._port = None
            self._last_status = f"Failed to start mobile sync server: {exc.strerror or str(exc)}"
            logger.exception("Could not start mobile sync server")

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._host = None
        self._port = None
        self._last_status = "Stopped"

        if not process:
            return

        if process.poll() is None:
            logger.info("Stopping mobile sync server pid=%s", process.pid)
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Mobile sync server did not stop cleanly; killing pid=%s", process.pid)
                process.kill()
                process.wait(timeout=5)
        
        if hasattr(self, '_log_file') and self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _build_command(self, host: str, port: int) -> List[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [
            sys.executable,
            "-m",
            "backend.src.mobile_server",
            "--host",
            host,
            "--port",
            str(port),
        ]

    def _working_directory(self) -> str:
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


mobile_server_manager = MobileServerManager()
