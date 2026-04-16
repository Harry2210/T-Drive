"""
Telegram Cloud Drive — Utility Helpers
Hashing, safe file I/O, drive mounting, and the local sync database.
Cross-platform: Windows + macOS.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from logger import get_logger

log = get_logger()

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# Current Application Version (Increment this when you build a new update)
VERSION = "1.0.2"

# Mandatory Update Check URL (Gist is used so the main repo can stay private)
UPDATE_CHECK_URL = "https://gist.githubusercontent.com/Harry2210/dda90b344ec8d67846f8eb0717800e7d/raw/5f44aa19c01ead3fd6a59bd8b1460f80bc142cc0/version.json"

# ---------------------------------------------------------------------------
#  Hashing
# ---------------------------------------------------------------------------

def file_hash(filepath: str | Path, algorithm: str = "md5") -> str:
    """
    Compute the hex-digest of *filepath* using the given algorithm.

    Reads in 64 KiB chunks to stay memory-friendly for large files.
    """
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        while chunk := f.read(65_536):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
#  Safe file writing
# ---------------------------------------------------------------------------

def safe_write(target: str | Path, data: bytes) -> None:
    """
    Atomically write *data* to *target* by writing to a temporary file
    first and then moving it into place.  This prevents partial / corrupt
    writes on crash or power loss.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        os.write(fd, data)
        os.close(fd)
        # On Windows, the target must not exist for os.rename
        if target.exists():
            target.unlink()
        shutil.move(tmp_path, str(target))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
#  Sync Database (JSON backed)
# ---------------------------------------------------------------------------

class SyncDatabase:
    """
    Lightweight JSON-file database that tracks every synced file.

    Schema per entry (keyed by relative path)::

        {
          "filename": "photo.jpg",
          "size": 123456,
          "hash": "ab12cd34…",
          "message_id": 42,
          "last_synced": "2025-01-01T00:00:00",
          "deleted": false
        }
    """

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Corrupt sync DB — starting fresh: %s", exc)
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- CRUD ----

    def get(self, rel_path: str) -> dict[str, Any] | None:
        return self._data.get(rel_path)

    def upsert(self, rel_path: str, entry: dict[str, Any]) -> None:
        self._data[rel_path] = entry
        self.save()

    def remove(self, rel_path: str) -> None:
        self._data.pop(rel_path, None)
        self.save()

    def mark_deleted(self, rel_path: str) -> None:
        if rel_path in self._data:
            self._data[rel_path]["deleted"] = True
            self.save()

    def all_entries(self) -> dict[str, dict[str, Any]]:
        return dict(self._data)

    def active_entries(self) -> dict[str, dict[str, Any]]:
        """Return entries that are not marked as deleted."""
        return {k: v for k, v in self._data.items() if not v.get("deleted")}

    def has_file(self, rel_path: str) -> bool:
        entry = self._data.get(rel_path)
        return entry is not None and not entry.get("deleted", False)

    def message_ids(self) -> set[int]:
        """Return a set of all tracked Telegram message IDs."""
        return {
            v["message_id"]
            for v in self._data.values()
            if "message_id" in v and not v.get("deleted", False)
        }


# ---------------------------------------------------------------------------
#  Cross-Platform Drive / Folder Mounting
# ---------------------------------------------------------------------------

def mount_drive(letter: str, folder: str) -> bool:
    """
    Mount *folder* as a virtual drive or prepare it for easy access.

    - **Windows**: Uses ``SUBST`` to map *folder* to drive *letter*:.
    - **macOS**: Ensures the folder exists (no drive letters on macOS).

    Returns True on success.
    """
    folder_path = Path(folder).resolve()
    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)

    if IS_MACOS:
        log.info("macOS: Sync folder ready at %s", folder_path)
        return True

    if IS_WINDOWS:
        letter = letter.upper().rstrip(":")
        drive = f"{letter}:"

        # Check if already mounted
        result = subprocess.run(
            ["subst"], capture_output=True, text=True, shell=True,
        )
        if f"{drive}\\" in result.stdout or f"{drive} " in result.stdout:
            log.info("Drive %s is already mounted.", drive)
            return True

        proc = subprocess.run(
            ["subst", drive, str(folder_path)],
            capture_output=True, text=True, shell=True,
        )
        if proc.returncode == 0:
            log.info("Mounted %s → %s", drive, folder_path)
            return True

        log.error("Failed to mount drive: %s", proc.stderr.strip())
        return False

    # Unsupported OS — just ensure folder exists
    log.info("Sync folder ready at %s", folder_path)
    return True


def unmount_drive(letter: str) -> bool:
    """Remove the SUBST mapping for *letter*: (Windows only)."""
    if not IS_WINDOWS:
        return True

    letter = letter.upper().rstrip(":")
    drive = f"{letter}:"
    proc = subprocess.run(
        ["subst", drive, "/D"],
        capture_output=True, text=True, shell=True,
    )
    if proc.returncode == 0:
        log.info("Unmounted drive %s", drive)
        return True
    log.warning("Could not unmount %s: %s", drive, proc.stderr.strip())
    return False


def open_folder_in_explorer(folder: str) -> None:
    """Open the given folder in the platform's file manager."""
    folder_path = Path(folder).resolve()
    if IS_WINDOWS:
        os.startfile(str(folder_path))  # type: ignore[attr-defined]
    elif IS_MACOS:
        subprocess.Popen(["open", str(folder_path)])
    else:
        subprocess.Popen(["xdg-open", str(folder_path)])


# ---------------------------------------------------------------------------
#  Misc helpers
# ---------------------------------------------------------------------------

def human_size(nbytes: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} PB"


def sanitise_filename(name: str) -> str:
    """
    Remove or replace characters that are illegal in Windows filenames.
    """
    illegal = '<>:"/\\|?*'
    for ch in illegal:
        name = name.replace(ch, "_")
    return name.strip(". ")


def register_tdrive_extension() -> None:
    """
    Register the .tdrive file extension on Windows so double-clicking
    triggers the app to hydrate the file.
    """
    if not IS_WINDOWS:
        return
    
    import winreg
    
    ext = ".tdrive"
    prog_id = "TDrive.StubFile"
    python_exe = sys.executable
    if "python.exe" in python_exe.lower():
        # Use pythonw instead of python so a black console window doesn't flash
        try_pw = python_exe.replace("python.exe", "pythonw.exe").replace("PYTHON.EXE", "pythonw.exe")
        if os.path.exists(try_pw):
            python_exe = try_pw
            
    script_path = os.path.abspath("main.py")
    
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\\" + ext) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, prog_id)
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\\" + prog_id) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "T-Drive Cloud File")
            winreg.SetValueEx(key, "NeverShowExt", 0, winreg.REG_SZ, "")
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\\" + prog_id + r"\shell\open\command") as key:
            command = f'"{python_exe}" "{script_path}" hydrate "%1"'
            winreg.SetValue(key, "", winreg.REG_SZ, command)
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\\" + prog_id + r"\DefaultIcon") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "imageres.dll,-1001")
            
        log.info("Registered .tdrive file association.")
    except Exception as e:
        log.error("Failed to register .tdrive extension: %s", e)
