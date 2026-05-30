import json
import os
import threading
import logging
from datetime import datetime
from typing import Dict, Any

from .paths import get_user_data_dir

CONFIG_FILE = "oura_config.json"
DASHBOARD_FILE = "oura_dashboard.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ConfigManager")

DEFAULT_CONFIG = {
    "email": "",
    "schedule_time": "11:00",
    "last_run": None,
    "next_run": None,
    "status": "Idle",
    "logged_in": False,
    "is_active": True,
    "headless": True,
    "llm_model": "llama3.1:latest",
    "llm_host": "http://localhost:1234/v1",
    "llm_api_key": "not-needed",
    "mobile_sync_enabled": False,
    "mobile_sync_token": "",
    "mobile_sync_default_window_days": 180,
    "mobile_sync_bind_host": "0.0.0.0",
    "mobile_sync_port": 8037,
    "last_export_request_at": None,
    "otp_requested_at": None,
    "status_started_at": None,
}

_PROCESSING_STATUSES = frozenset({
    "Processing",
    "Starting...",
    "Initializing...",
    "Running Automation...",
    "Running Automation",
    "Downloading...",
    "Ingesting...",
    "Ingesting",
    "Submitting OTP...",
    "Starting manual run...",
    "Installing dependency (Chromium)...",
})

DEFAULT_DASHBOARD = {"dashboard": {"dashboards": [], "activeDashboardId": None}}


class ConfigManager:
    """
    Manages application configuration and dashboard state.
    Handles reading/writing to JSON files with thread safety.
    """
    def __init__(self):
        self.data_dir = get_user_data_dir()
        self.config_path = os.path.join(self.data_dir, CONFIG_FILE)
        self.dashboard_path = os.path.join(self.data_dir, DASHBOARD_FILE)
        self._lock = threading.Lock()
        self._ensure_config()

    def _ensure_config(self):
        """Ensures configuration files exist with all required keys."""
        # Main config: create or backfill missing keys
        main_conf = self._load_file(self.config_path) if os.path.exists(self.config_path) else {}
        changed = False
        for key, value in DEFAULT_CONFIG.items():
            if key not in main_conf:
                main_conf[key] = value
                changed = True
        if changed or not os.path.exists(self.config_path):
            self._save_file(self.config_path, main_conf)

        # Dashboard config: create if missing
        if not os.path.exists(self.dashboard_path):
            self._save_file(self.dashboard_path, DEFAULT_DASHBOARD)

    def _load_file(self, path: str) -> Dict[str, Any]:
        """Loads JSON content from a file safely."""
        try:
            if not os.path.exists(path):
                return {}
            with open(path, 'r', encoding='utf-8-sig') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except Exception as e:
            logger.error(f"Error loading config from {path}: {e}")
            return {}

    def _save_file(self, path: str, data: Dict[str, Any]):
        """Saves data to a JSON file atomically."""
        import uuid
        tmp_path = f"{path}.{uuid.uuid4()}.tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                f.flush()
                # Ensure write to disk
                os.fsync(f.fileno())
            # Atomic rename
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"Error saving config to {path}: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def get_config(self) -> Dict[str, Any]:
        """Returns merged configuration from both config and dashboard files."""
        with self._lock:
            main_conf = self._load_file(self.config_path)
            dash_conf = self._load_file(self.dashboard_path)
            
            # Merge: dashboard config overrides main if keys collide
            return {**main_conf, **dash_conf}

    def update_config(self, **kwargs):
        """Updates configuration, routing keys to the appropriate file based on context."""
        with self._lock:
            main_conf = self._load_file(self.config_path)
            dash_conf = self._load_file(self.dashboard_path)
            
            main_changed = False
            dash_changed = False
            
            for key, value in kwargs.items():
                if value is None: continue
                
                if key == "dashboard":
                    # Dashboard update
                    dash_conf["dashboard"] = value
                    dash_changed = True
                else:
                    # General config update
                    main_conf[key] = value
                    main_changed = True
            
            if main_changed:
                self._save_file(self.config_path, main_conf)
            if dash_changed:
                self._save_file(self.dashboard_path, dash_conf)

    def update_status(self, status: str, **kwargs):
        """
        Helper to update status specific fields in the main config.
        Accepts flexible kwargs like 'message', 'last_run', 'next_run'.
        """
        if status in ("otp_needed", "Waiting"):
            kwargs.setdefault("logged_in", False)
        if status in _PROCESSING_STATUSES:
            kwargs.setdefault(
                "status_started_at",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        elif status == "Idle":
            kwargs.setdefault("status_started_at", None)
        self.update_config(status=status, **kwargs)

config_manager = ConfigManager()
