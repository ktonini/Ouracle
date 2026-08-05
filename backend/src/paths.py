import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger("Paths")

def get_user_data_dir() -> Path:
    """
    Returns the platform-specific user data directory for the application.
    - OURACLE_DATA_DIR env var, when set (containers / servers)
    - Windows: %APPDATA%/CrackedOura
    - macOS: ~/Library/Application Support/CrackedOura
    - Linux: ~/.local/share/CrackedOura
    """
    app_name = "CrackedOura"

    env_dir = os.environ.get("OURACLE_DATA_DIR")
    if env_dir:
        path = Path(env_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    if sys.platform == "win32":
        path = Path(os.environ["APPDATA"]) / app_name
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / app_name
    else:
        path = Path.home() / ".local" / "share" / app_name

    path.mkdir(parents=True, exist_ok=True)
    return path
