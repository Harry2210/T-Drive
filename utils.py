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
VERSION = "2.4.0"

# Mandatory Update Check URL (Gist is used so the main repo can stay private)
UPDATE_CHECK_URL = "https://gist.githubusercontent.com/Harry2210/dda90b344ec8d67846f8eb0717800e7d/raw/version.json"

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

def pin_to_explorer_sidebar(folder_path: str, name: str = "T-Drive") -> bool:
    """
    Pins the cloud folder to the Windows Explorer sidebar as a virtual namespace.
    This provides a professional integration similar to OneDrive or Dropbox.
    """
    if not IS_WINDOWS:
        return True

    import winreg
    from pathlib import Path
    clsid = "{D3B310A7-0E0C-44A7-9753-F96B3E93C3B1}"
    icon_path = str(Path(sys.executable if getattr(sys, 'frozen', False) else "app.ico").resolve())
    folder_path_obj = Path(folder_path).resolve()
    if not folder_path_obj.exists():
        try:
            folder_path_obj.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.error("Could not create folder for pinning: %s", e)
            return False

    folder_path = str(folder_path_obj)
    
    try:
        # 1. Create CLSID entry (Use HKLM since we are Admin, for better system integration)
        hives = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
        for hive in hives:
            try:
                root = fr"Software\Classes\CLSID\{clsid}"
                with winreg.CreateKey(hive, root) as key:
                    winreg.SetValue(key, "", winreg.REG_SZ, name)
                    winreg.SetValueEx(key, "System.IsPinnedToNameSpaceTree", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "SortOrderIndex", 0, winreg.REG_DWORD, 0x42)
                    winreg.SetValueEx(key, "Attributes", 0, winreg.REG_DWORD, 0xF080004D)
                    winreg.SetValueEx(key, "FolderValueFlags", 0, winreg.REG_DWORD, 0x28)
                
                # 2. Icon
                with winreg.CreateKey(hive, fr"{root}\DefaultIcon") as key:
                    winreg.SetValue(key, "", winreg.REG_SZ, f"{icon_path},0")
                
                # 3. Server
                with winreg.CreateKey(hive, fr"{root}\InProcServer32") as key:
                    winreg.SetValue(key, "", winreg.REG_SZ, r"%SystemRoot%\system32\shell32.dll")
                    winreg.SetValueEx(key, "ThreadingModel", 0, winreg.REG_SZ, "Both")
                
                # 4. Instance
                inst_path = fr"{root}\Instance"
                with winreg.CreateKey(hive, inst_path) as key:
                    winreg.SetValueEx(key, "CLSID", 0, winreg.REG_SZ, "{0E5AAE11-A475-4c5b-AB00-C66DE400274E}")
                
                with winreg.CreateKey(hive, fr"{inst_path}\InitPropertyBag") as key:
                    winreg.SetValueEx(key, "Attributes", 0, winreg.REG_DWORD, 0x11)
                    winreg.SetValueEx(key, "TargetFolderPath", 0, winreg.REG_SZ, folder_path)
                
                # 5. ShellFolder
                with winreg.CreateKey(hive, fr"{root}\ShellFolder") as key:
                    winreg.SetValueEx(key, "Attributes", 0, winreg.REG_DWORD, 0xF080004D)
                    winreg.SetValueEx(key, "FolderValueFlags", 0, winreg.REG_DWORD, 0x28)
                    winreg.SetValueEx(key, "System.IsPinnedToNameSpaceTree", 0, winreg.REG_DWORD, 1)
            except:
                continue

        # 6. Register in NameSpace (Desktop AND My Computer)
        ns_paths = [
            fr"Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace\{clsid}",
            fr"Software\Microsoft\Windows\CurrentVersion\Explorer\MyComputer\NameSpace\{clsid}"
        ]
        for ns in ns_paths:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ns) as key:
                winreg.SetValue(key, "", winreg.REG_SZ, name)
        
        # 7. Hide from Desktop icons
        hides = [
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\ClassicStartMenu"
        ]
        for h in hides:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, h) as key:
                winreg.SetValueEx(key, clsid, 0, winreg.REG_DWORD, 1)

        # 8. Notify Explorer to refresh
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        
        # 9. desktop.ini creation removed to keep the folder clean as requested.
        # The Sidebar will still show the logo via the Registry CLSID.

        # 10. Force Quick Access pin using PowerShell
        pin_to_quick_access(folder_path)

        log.info("Pinned %s to Explorer sidebar successfully.", folder_path)
        return True
    except Exception as e:
        log.error("Failed to pin to sidebar: %s", e)
        return False

def pin_to_quick_access(folder_path: str) -> bool:
    """Pins a folder to Windows Quick Access (Home) using PowerShell."""
    if not IS_WINDOWS: return True
    import subprocess
    
    # Use a more robust PowerShell script to check if already pinned before invoking the verb.
    # This prevents the 'toggle' behavior where clicking it again unpins it.
    ps_cmd = (
        f'$s = New-Object -ComObject shell.application; '
        f'$f = $s.Namespace("{folder_path}"); '
        f'$q = $s.Namespace("shell:::{{679f85cb-0220-4080-b29b-5540cc05aab6}}"); '
        f'$already = $q.Items() | Where-Object {{ $_.Path -eq $f.Self.Path }}; '
        f'if (-not $already) {{ $f.Self.InvokeVerb("PinToHome") }}'
    )
    try:
        subprocess.run(['powershell.exe', '-WindowStyle', 'Hidden', '-Command', ps_cmd], capture_output=True)
        return True
    except:
        return False

def unpin_from_explorer_sidebar() -> bool:
    """Removes the T-Drive entry from the Explorer sidebar."""
    if not IS_WINDOWS:
        return True
        
    import winreg
    clsid = "{D3B310A7-0E0C-44A7-9753-F96B3E93C3B1}"
    
    try:
        # Delete from NameSpace
        ns_path = fr"Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace"
        try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER, fr"{ns_path}\{clsid}")
        except: pass
        
        # Delete CLSID
        clsid_path = fr"Software\Classes\CLSID"
        # Registry keys with subkeys must be deleted recursively
        def delete_key_recursive(root, subkey):
            try:
                hkey = winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS)
                while True:
                    try:
                        name = winreg.EnumKey(hkey, 0)
                        delete_key_recursive(hkey, name)
                    except OSError: break
                winreg.CloseKey(hkey)
                winreg.DeleteKey(root, subkey)
            except: pass

        delete_key_recursive(winreg.HKEY_CURRENT_USER, fr"Software\Classes\CLSID\{clsid}")
        
        # Notify Explorer
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        return True
    except Exception as e:
        log.debug("Unpinning error: %s", e)
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
    is_frozen = getattr(sys, 'frozen', False)
    python_exe = sys.executable
    if not is_frozen and "python.exe" in python_exe.lower():
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
            if is_frozen:
                command = f'"{python_exe}" hydrate "%1"'
            else:
                command = f'"{python_exe}" "{script_path}" hydrate "%1"'
            winreg.SetValue(key, "", winreg.REG_SZ, command)
            
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\\" + prog_id + r"\DefaultIcon") as key:
            icon_path = str(Path(sys.executable if getattr(sys, 'frozen', False) else "app.ico").resolve())
            winreg.SetValue(key, "", winreg.REG_SZ, icon_path)
            
        log.info("Registered .tdrive file association.")
    except Exception as e:
        log.error("Failed to register .tdrive extension: %s", e)

def set_autostart(enabled: bool) -> None:
    """Add or remove the app from Windows startup using Task Scheduler."""
    if not IS_WINDOWS: return
    import subprocess
    app_name = "T-Drive"
    exe_path = sys.executable if getattr(sys, 'frozen', False) else f"{sys.executable} {os.path.abspath('main.py')}"
    
    try:
        if enabled:
            # Create a scheduled task that runs with highest privileges on logon
            cmd = ['schtasks', '/create', '/tn', app_name, '/tr', f'"{exe_path}"', '/sc', 'onlogon', '/rl', 'highest', '/f']
            subprocess.run(cmd, capture_output=True, check=True)
            log.info("Autostart (Scheduled Task) enabled.")
        else:
            # Delete the scheduled task
            cmd = ['schtasks', '/delete', '/tn', app_name, '/f']
            subprocess.run(cmd, capture_output=True)
            log.info("Autostart (Scheduled Task) disabled.")
    except Exception as e:
        log.error("Failed to set autostart (Scheduled Task): %s", e)
