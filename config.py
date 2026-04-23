"""
Telegram Cloud Drive — Configuration Loader
Reads config.json, validates required fields, and exposes a typed
dataclass for the rest of the application.  Also supports saving
config back to disk from the GUI.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from logger import get_logger

log = get_logger()

import os

if getattr(sys, "frozen", False):
    # Check for portable mode first (config.json next to EXE)
    _EXE_DIR = Path(sys.executable).parent
    _PORTABLE_CONFIG = _EXE_DIR / "config.json"
    
    # If the EXE is in a protected folder (like Program Files), we MUST use AppData
    # unless we are running as Admin. A good heuristic is to check if we can write to _EXE_DIR.
    try:
        _test_file = _EXE_DIR / ".write_test"
        _test_file.touch()
        _test_file.unlink()
        _CAN_WRITE_EXE = True
    except:
        _CAN_WRITE_EXE = False

    if _PORTABLE_CONFIG.exists() and _CAN_WRITE_EXE:
        DATA_DIR = _EXE_DIR
        _CONFIG_PATH = _PORTABLE_CONFIG
    else:
        DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "T-Drive"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH = DATA_DIR / "config.json"
else:
    DATA_DIR = Path(__file__).parent
    _CONFIG_PATH = DATA_DIR / "config.json"



class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


@dataclass
class AppConfig:
    """Strongly-typed application configuration."""

    api_id: int
    api_hash: str
    local_folder: str = str(Path.home() / "T-Drive")
    sync_interval: int = 10
    drive_letter: str = "T"
    log_file: str = str(DATA_DIR / "log.txt")
    db_file: str = str(DATA_DIR / "sync_db.json")
    session_name: str = str(DATA_DIR / "telegram_drive_session")
    hash_algorithm: Literal["md5", "sha256"] = "md5"
    delete_sync: bool = True
    on_demand_sync: bool = True
    max_retries: int = 999999
    retry_delay: int = 3
    autostart: bool = True

    def __post_init__(self) -> None:
        # Normalise paths
        self.local_folder = str(Path(self.local_folder).resolve())

        # Ensure data files are in DATA_DIR if they are relative paths
        for attr in ["log_file", "db_file", "session_name"]:
            val = getattr(self, attr)
            if val and not os.path.isabs(val):
                setattr(self, attr, str(DATA_DIR / os.path.basename(val)))
        # Ensure the local folder exists
        try:
            Path(self.local_folder).mkdir(parents=True, exist_ok=True)
            # Test write access
            test_file = Path(self.local_folder) / ".td_test"
            test_file.touch()
            test_file.unlink()
        except (PermissionError, OSError) as e:
            log.error("CRITICAL: No write access to sync folder %s: %s", self.local_folder, e)
            log.error("Please run T-Drive as Administrator or choose a different folder.")

    def to_dict(self) -> dict:
        """Serialise config to a plain dict for JSON storage."""
        return {
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "local_folder": self.local_folder,
            "sync_interval": self.sync_interval,
            "drive_letter": self.drive_letter,
            "log_file": self.log_file,
            "db_file": self.db_file,
            "session_name": self.session_name,
            "hash_algorithm": self.hash_algorithm,
            "delete_sync": self.delete_sync,
            "on_demand_sync": self.on_demand_sync,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "autostart": self.autostart,
        }


def load_config(path: Path | str | None = None) -> AppConfig:
    """
    Load configuration from *path* (defaults to ``config.json`` next to
    this module).

    Raises
    ------
    ConfigError
        If the file is missing, unreadable, or lacks required keys.
    """
    config_path = Path(path) if path else _CONFIG_PATH

    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        raw: dict = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Malformed JSON in {config_path}: {exc}") from exc

    # ---- Validate required fields ----
    missing = [k for k in ("api_id", "api_hash") if not raw.get(k)]
    if missing:
        raise ConfigError(f"Missing required config keys: {', '.join(missing)}")

    try:
        raw["api_id"] = int(raw["api_id"])
    except (ValueError, TypeError) as exc:
        raise ConfigError("'api_id' must be a valid integer.") from exc

    # Build the dataclass, ignoring unknown keys gracefully
    known_fields = {f.name for f in AppConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in known_fields}
    return AppConfig(**filtered)


def save_config(config: AppConfig | dict, path: Path | str | None = None) -> None:
    """
    Write configuration to disk as JSON.

    Parameters
    ----------
    config : AppConfig | dict
        Either an AppConfig instance or a plain dict.
    path : Path | str | None
        Target file (defaults to ``config.json`` next to this module).
    """
    config_path = Path(path) if path else _CONFIG_PATH
    data = config.to_dict() if isinstance(config, AppConfig) else config
    config_path.write_text(
        json.dumps(data, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )
