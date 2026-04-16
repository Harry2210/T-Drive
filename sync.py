"""
Telegram Cloud Drive — Two-Way Sync Engine
Handles uploads, downloads, delete-sync, and rename detection via
the Telethon async Telegram client.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import (
    DocumentAttributeFilename,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from logger import get_logger
from utils import SyncDatabase, file_hash, human_size, safe_write, sanitise_filename

if TYPE_CHECKING:
    from config import AppConfig

log = get_logger()


class SyncEngine:
    """
    Bi-directional synchronisation between a local folder and
    Telegram Saved Messages.
    """

    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        self.local = Path(config.local_folder)
        self.db = SyncDatabase(config.db_file)
        self.client: TelegramClient | None = None
        self._first_run = True # Track if this is the first sync after clicking Start
        self._running = False

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Authenticate and kick off the sync loop."""
        self.client = TelegramClient(
            self.cfg.session_name,
            self.cfg.api_id,
            self.cfg.api_hash,
        )
        await self.client.start()
        me = await self.client.get_me()
        log.info("Authenticated as %s (ID %s)", me.first_name, me.id)
        self._running = True

    async def stop(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        if self.client:
            await self.client.disconnect()
            log.info("Telegram client disconnected.")

    async def run_forever(self) -> None:
        """Run the sync loop until stopped."""
        while self._running:
            try:
                if self.client and not await self.client.is_user_authorized():
                     # If the client completely dropped connection or session
                     log.debug("Session check failed, verifying connection...")
                     if not self.client.is_connected():
                         await self.client.connect()
                         
                await self.sync_once()
            except FloodWaitError as exc:
                log.warning(
                    "Telegram rate-limit hit — sleeping %d s", exc.seconds
                )
                await asyncio.sleep(exc.seconds + 1)
            except RPCError as exc:
                log.error("Telegram RPC error: %s", exc)
                await asyncio.sleep(self.cfg.retry_delay)
            except OSError as exc:
                log.error("I/O error during sync: %s", exc)
                await asyncio.sleep(self.cfg.retry_delay)
            except Exception as exc:
                log.exception("Unexpected error during sync: %s", exc)
                await asyncio.sleep(self.cfg.retry_delay)

            if self._running:
                log.debug("Next sync in %d s ...", self.cfg.sync_interval)
                await asyncio.sleep(self.cfg.sync_interval)

    # ------------------------------------------------------------------
    #  Core sync
    # ------------------------------------------------------------------

    async def sync_once(self) -> None:
        """Perform a single full sync cycle."""
        log.info("-- Sync cycle starting --")
        t0 = time.monotonic()

        self.uploads_in_cycle = 0
        self.downloads_in_cycle = 0

        await self._upload_new_local_files()
        await self._download_new_telegram_files()

        if self.cfg.delete_sync:
            await self._delete_sync_local_to_remote()
            await self._delete_sync_remote_to_local()

        self._first_run = False # Cycle completed, now we're in 'Live' mode
        elapsed = time.monotonic() - t0
        log.info("-- Sync cycle finished in %.1f s --", elapsed)

        # OS Notification logic
        if self.uploads_in_cycle > 0 or self.downloads_in_cycle > 0:
            try:
                from plyer import notification
                msg = []
                if self.uploads_in_cycle > 0:
                    msg.append(f"Uploaded {self.uploads_in_cycle} file(s)")
                if self.downloads_in_cycle > 0:
                    msg.append(f"Downloaded {self.downloads_in_cycle} file(s)")
                
                notification.notify(
                    title="T-Drive Sync Complete",
                    message=", ".join(msg),
                    app_name="T-Drive",
                    timeout=4
                )
            except Exception as e:
                log.debug("Notification failed: %s", e)

    # ------------------------------------------------------------------
    #  Upload: local → Telegram
    # ------------------------------------------------------------------

    async def _upload_new_local_files(self) -> None:
        """Scan the local folder and upload anything not yet tracked."""
        for root, _dirs, files in os.walk(self.local):
            for fname in files:
                full = Path(root) / fname
                rel = str(full.relative_to(self.local)).replace("\\", "/")

                # NEVER upload shortcut/stub files back to Telegram
                if fname.endswith(".lnk") or fname.endswith(".tdrive"):
                    continue
                    
                if fname.endswith(".tmp") or fname.startswith("~"):
                    continue

                existing = self.db.get(rel)

                # Already tracked?
                if existing and not existing.get("deleted"):
                    # HYDRATION PROTECTION: If we have a stub tracked but found a local full file,
                    # it means the user is currently using it. DO NOT RE-UPLOAD.
                    if existing.get("hash") == "STUB" and full.exists():
                        continue
 
                    # OFF-LOAD ENFORCEMENT: If On-Demand is enabled but we have a full file, offload it!
                    if getattr(self.cfg, "on_demand_sync", False) and existing.get("hash") != "STUB":
                        import time
                        file_age = time.time() - full.stat().st_mtime
                        if file_age < 120:
                             # File is too young! Wait 2 minutes before stubbing it.
                             continue

                        local_size = full.stat().st_size
                        if existing.get("size") == local_size:
                            log.info("Offloading synced file after 2 min inactivity: %s", rel)
                            messages = await self.client.get_messages("me", ids=[existing["message_id"]])
                            if messages and messages[0]:
                                await create_lnk_stub(self.client, messages[0], self.local, rel)
                                try:
                                    full.unlink()
                                    existing["hash"] = "STUB"
                                    self.db.upsert(rel, existing)
                                except Exception: pass
                                continue

                    # Check if file has changed (size / hash)
                    local_size = full.stat().st_size
                    if existing.get("size") == local_size:
                        local_h = file_hash(full, self.cfg.hash_algorithm)
                        if existing.get("hash") == local_h:
                            continue  # identical — skip
                    # File has changed → re-upload
                    log.info("File changed, re-uploading: %s", rel)
                    await self._delete_telegram_message(existing["message_id"])
                    remove_cached_icon(existing["message_id"])

                await self._upload_file(full, rel)

    async def _upload_file(self, full_path: Path, rel_path: str) -> None:
        """Upload a single file with retries."""
        size = full_path.stat().st_size
        h = file_hash(full_path, self.cfg.hash_algorithm)

        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                log.info(
                    "Uploading %s (%s) [attempt %d]",
                    rel_path,
                    human_size(size),
                    attempt,
                )
                # Use the relative path as caption so we can reconstruct
                # folder structure on download.
                msg: Message = await self.client.send_file(  # type: ignore[union-attr]
                    "me",
                    str(full_path),
                    caption=f"#TDrive {rel_path}",
                    force_document=True,
                )
                if getattr(self.cfg, "on_demand_sync", False):
                    # Replace actual file with stub to free up space
                    await create_lnk_stub(self.client, msg, self.local, rel_path)
                    
                    self.db.upsert(rel_path, {
                        "filename": full_path.name,
                        "size": size,
                        "hash": "STUB",
                        "message_id": msg.id,
                        "last_synced": _now_iso(),
                        "deleted": False,
                    })
                    try:
                        full_path.unlink()
                        log.info("Freed up disk space for: %s", rel_path)
                    except Exception as e:
                        log.error("Could not delete original file %s: %s", rel_path, e)
                else:
                    self.db.upsert(rel_path, {
                        "filename": full_path.name,
                        "size": size,
                        "hash": h,
                        "message_id": msg.id,
                        "last_synced": _now_iso(),
                        "deleted": False,
                    })
                self.uploads_in_cycle += 1
                log.info("Uploaded  OK  %s (msg %d)", rel_path, msg.id)
                return
            except FloodWaitError as exc:
                log.warning("Flood wait: %d s", exc.seconds)
                await asyncio.sleep(exc.seconds + 1)
            except RPCError as exc:
                log.error("Upload RPC error: %s", exc)
                await asyncio.sleep(self.cfg.retry_delay)

        log.error("Upload FAILED after %d attempts: %s", self.cfg.max_retries, rel_path)

    # ------------------------------------------------------------------
    #  Download: Telegram → local
    # ------------------------------------------------------------------

    async def _download_new_telegram_files(self) -> None:
        """Iterate Saved Messages and download files we don't have."""
        known_ids = self.db.message_ids()

        async for msg in self.client.iter_messages("me"):  # type: ignore[union-attr]
            if not _is_tdrive_message(msg):
                continue

            if msg.id in known_ids:
                continue  # already tracked

            rel_path = _extract_rel_path(msg)
            if not rel_path:
                continue

            local_dest = self.local / rel_path

            # Already exists locally with same size?  Skip.
            if local_dest.exists():
                remote_size = _media_size(msg)
                if remote_size and local_dest.stat().st_size == remote_size:
                    # Track it but don't download again
                    h = file_hash(local_dest, self.cfg.hash_algorithm)
                    self.db.upsert(rel_path, {
                        "filename": local_dest.name,
                        "size": remote_size,
                        "hash": h,
                        "message_id": msg.id,
                        "last_synced": _now_iso(),
                        "deleted": False,
                    })
                    continue

            if getattr(self.cfg, "on_demand_sync", False):
                # Create a placeholder file instead of full download
                remote_size = _media_size(msg)
                await create_lnk_stub(self.client, msg, self.local, rel_path)
                
                self.db.upsert(rel_path, {
                    "filename": Path(rel_path).name,
                    "size": remote_size,
                    "hash": "STUB",
                    "message_id": msg.id,
                    "last_synced": _now_iso(),
                    "deleted": False,
                })
                log.info("Created smart stub for on-demand: %s", rel_path)
                continue

            await self._download_file(msg, rel_path, local_dest)

    async def _download_file(
        self, msg: Message, rel_path: str, dest: Path,
    ) -> None:
        """Download a single Telegram file with retries."""
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                log.info(
                    "Downloading %s (msg %d) [attempt %d]",
                    rel_path,
                    msg.id,
                    attempt,
                )
                dest.parent.mkdir(parents=True, exist_ok=True)
                
                # Download to hidden AppData temp first
                import tempfile, shutil
                appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
                hiddentemp_dir = Path(appdata) / "TDrive" / "Temp"
                hiddentemp_dir.mkdir(parents=True, exist_ok=True)
                
                temp_fd, temp_path = tempfile.mkstemp(dir=str(hiddentemp_dir), suffix=".td_tmp")
                os.close(temp_fd) # Just need the path
                
                await self.client.download_media(msg, file=temp_path)  # type: ignore[union-attr]
 
                # Atomic move: Move from secret temp to final destination
                if dest.exists():
                    dest.unlink()
                shutil.move(temp_path, str(dest))
 
                size = dest.stat().st_size
                h = file_hash(dest, self.cfg.hash_algorithm)
                self.db.upsert(rel_path, {
                    "filename": dest.name,
                    "size": size,
                    "hash": h,
                    "message_id": msg.id,
                    "last_synced": _now_iso(),
                    "deleted": False,
                })
                self.downloads_in_cycle += 1
                log.info("Downloaded OK  %s (%s)", rel_path, human_size(size))
                return
            except FloodWaitError as exc:
                log.warning("Flood wait: %d s", exc.seconds)
                await asyncio.sleep(exc.seconds + 1)
            except RPCError as exc:
                log.error("Download RPC error: %s", exc)
                await asyncio.sleep(self.cfg.retry_delay)

        log.error(
            "Download FAILED after %d attempts: %s", self.cfg.max_retries, rel_path,
        )

    # ------------------------------------------------------------------
    #  Delete sync
    # ------------------------------------------------------------------

    async def _delete_sync_local_to_remote(self) -> None:
        """
        If a file was tracked but no longer exists locally, delete
        the corresponding Telegram message and mark it deleted.
        """
        for rel, entry in list(self.db.active_entries().items()):
            local_path = self.local / rel
            stub_path = self.local / (rel + ".tdrive")
            stub_lnk = self.local / (rel + ".lnk")
            
            p_exist = local_path.exists()
            t_exist = stub_path.exists()
            l_exist = stub_lnk.exists()
            
            # Wait a beat before confirming a delete to allow "moves" to register
            if not p_exist and not t_exist and not l_exist:
                # Double-check if the file was just moved elsewhere in the drive
                moved = False
                for other_rel in self.db.active_entries():
                    if Path(other_rel).name == Path(rel).name:
                        moved = True # Likely just a folder move
                        break
                
                if not moved:
                    if self._first_run:
                        # OFF-LOAD MODE: The file was gone before we started. 
                        # Restore the stub instead of deleting from Telegram.
                        log.info("File missing at start -> Offloading to stub: %s", rel)
                        messages = await self.client.get_messages("me", ids=[entry["message_id"]])
                        if messages and messages[0]:
                            await create_lnk_stub(self.client, messages[0], self.local, rel)
                    else:
                        # LIVE DELETE MODE: File deleted while sync is active.
                        log.info("Live delete confirmed -> removing from Telegram: %s", rel)
                        await self._delete_telegram_message(entry["message_id"])
                        remove_cached_icon(entry["message_id"])
                        self.db.mark_deleted(rel)
                else:
                    # MOVE DETECTED: Delete the OLD location on Telegram so it doesn't re-download!
                    log.info("Move detected for %s -> cleanup old Telegram copy", rel)
                    await self._delete_telegram_message(entry["message_id"])
                    remove_cached_icon(entry["message_id"])
                    self.db.remove(rel)

    async def _delete_sync_remote_to_local(self) -> None:
        """
        If a tracked Telegram message no longer exists, delete the
        local copy and mark it deleted.
        """
        active = self.db.active_entries()
        if not active:
            return

        # Collect all known message IDs
        id_to_rel: dict[int, str] = {
            v["message_id"]: k for k, v in active.items()
        }

        # Fetch those messages; missing ones were deleted on Telegram
        msgs = await self.client.get_messages(  # type: ignore[union-attr]
            "me", ids=list(id_to_rel.keys()),
        )
        found_ids = {m.id for m in msgs if m is not None}

        for mid, rel in id_to_rel.items():
            if mid not in found_ids:
                local_path = self.local / rel
                stub_lnk = self.local / (rel + ".lnk")
                if local_path.exists():
                    log.info(
                        "Telegram delete detected -> removing local: %s", rel
                    )
                    local_path.unlink()
                if stub_lnk.exists():
                    stub_lnk.unlink()
                remove_cached_icon(mid)
                self.db.mark_deleted(rel)

    async def _delete_telegram_message(self, msg_id: int) -> None:
        """Best-effort deletion of a Telegram message."""
        try:
            await self.client.delete_messages("me", [msg_id])  # type: ignore[union-attr]
            log.debug("Deleted Telegram message %d", msg_id)
        except RPCError as exc:
            log.warning("Could not delete message %d: %s", msg_id, exc)


# ======================================================================
#  Private helpers
# ======================================================================

_TDRIVE_TAG = "#TDrive"

def remove_cached_icon(msg_id: int) -> None:
    """Safely delete the cached thumbnail icon from AppData."""
    import os
    from pathlib import Path
    try:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        icon_path = Path(appdata) / "TDrive" / "Icons" / f"{msg_id}.ico"
        if icon_path.exists():
            icon_path.unlink()
    except OSError:
        pass


def _is_tdrive_message(msg: Message) -> bool:
    """Return True if *msg* has attached media. 
    Syncs every file/photo in saved messages.
    """
    return bool(msg.media)


def _extract_rel_path(msg: Message) -> str | None:
    """
    Parse the relative path from a TDrive message caption.
    Falls back to the msg.file attribute to get the original extension.
    """
    text = (msg.message or "").strip()
    if text.startswith(_TDRIVE_TAG):
        candidate = text[len(_TDRIVE_TAG):].strip()
        if candidate:
            return candidate

    from utils import sanitise_filename
    file_info = getattr(msg, "file", None)
    if file_info:
        if file_info.name:
            return sanitise_filename(file_info.name)
        if file_info.ext:
            return f"file_{msg.id}{file_info.ext}"

    # Photos fallback if msg.file is missing
    from telethon.tl.types import MessageMediaPhoto
    if getattr(msg, "photo", None) or isinstance(msg.media, MessageMediaPhoto):
        return f"photo_{msg.id}.jpg"

    # Last resort
    return f"unknown_{msg.id}.file"


def _media_size(msg: Message) -> int | None:
    """Return the byte-size of the file attached to *msg*, if any."""
    if isinstance(msg.media, MessageMediaDocument) and msg.media.document:
        return msg.media.document.size  # type: ignore[return-value]
    if isinstance(msg.media, MessageMediaPhoto):
        return None  # photos don't expose size reliably
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

async def create_lnk_stub(client, msg, local_dir: Path, rel_path: str) -> None:
    """Create a native Windows Shortcut as a stub, with optional thumbnail."""
    stub_dest = local_dir / (rel_path + ".lnk")
    stub_dest.parent.mkdir(parents=True, exist_ok=True)
    
    icon_path = ""
    try:
        from telethon.tl.types import MessageMediaPhoto
        has_thumb = getattr(msg, "photo", None) or isinstance(getattr(msg, "media", None), MessageMediaPhoto)
        if not has_thumb and getattr(msg, "document", None) and getattr(msg.document, "thumbs", None):
            has_thumb = True
            
        if has_thumb:
            import os
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            thumb_dir = Path(appdata) / "TDrive" / "Icons"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            
            thumb_jpg = thumb_dir / f"{msg.id}.jpg"
            icon_path_obj = thumb_dir / f"{msg.id}.ico"
            
            if not icon_path_obj.exists():
                await client.download_media(msg, thumb=-1, file=thumb_jpg)
                if thumb_jpg.exists():
                    from PIL import Image
                    with Image.open(thumb_jpg) as img:
                        img = img.resize((256, 256))
                        img.save(icon_path_obj, format="ICO")
                    thumb_jpg.unlink()
            
            if icon_path_obj.exists():
                icon_path = str(icon_path_obj).replace('\\', '\\\\')
    except Exception as e:
        log.debug("No thumb for msg %s: %s", msg.id, e)

    import sys, os, subprocess, tempfile
    python_exe = sys.executable
    if "python.exe" in python_exe.lower():
        try_pw = python_exe.lower().replace("python.exe", "pythonw.exe")
        if os.path.exists(try_pw): python_exe = try_pw
        
    script_path = os.path.abspath("main.py")
    
    # Escape for VBScript
    script_escaped = script_path.replace('"', '""')
    rel_escaped = rel_path.replace('"', '""')
    arg_line = f'Chr(34) & "{script_escaped}" & Chr(34) & " hydrate " & Chr(34) & "{rel_escaped}" & Chr(34) & " {msg.id}"'
    
    vbs = f"""
Set oWS = WScript.CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut("{stub_dest}")
oLink.TargetPath = "{python_exe}"
oLink.Arguments = {arg_line}
"""
    if icon_path:
        vbs += f'oLink.IconLocation = "{icon_path}, 0"\n'
    vbs += "oLink.Save\n"
    
    fd, path = tempfile.mkstemp(suffix=".vbs")
    with os.fdopen(fd, 'w', encoding="utf-8") as f:
        f.write(vbs)
    res = subprocess.run(['cscript.exe', '//Nologo', path], capture_output=True)
    if res.returncode != 0:
        log.error("Failed to create lnk: %s", res.stderr.decode(errors='ignore'))
    os.unlink(path)
