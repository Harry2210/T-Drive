"""
Telegram Cloud Drive — Desktop Application
Cross-platform GUI (Windows + macOS) built with CustomTkinter.

All user configuration (API credentials, folder paths, etc.) is done
entirely within this application — no manual file editing needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any
import webbrowser
import pystray
from PIL import Image, ImageDraw
try:
    from plyer import notification
except ImportError:
    notification = None

import customtkinter as ctk

# ── Local imports ──
from config import AppConfig, ConfigError, load_config, save_config
from logger import setup_logger, get_logger
from sync import SyncEngine
from utils import (
    IS_MACOS,
    IS_WINDOWS,
    SyncDatabase,
    human_size,
    mount_drive,
    open_folder_in_explorer,
    unmount_drive,
    VERSION,
    UPDATE_CHECK_URL,
)

# ══════════════════════════════════════════════════════════════════════
#  Appearance
# ══════════════════════════════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

APP_NAME = "T-Drive"
VERSION = "2.0.0"
WINDOW_W, WINDOW_H = 980, 660
SIDEBAR_W = 190

# ── Colour palette ──
CLR_BG = "#0f111a"
CLR_SIDEBAR_BG = "#151822"
CLR_SIDEBAR_HOVER = "#232838"
CLR_CARD = "#1c1f2b"
CLR_ACCENT = "#4f46e5"
CLR_SUCCESS = "#10b981"
CLR_WARNING = "#f59e0b"
CLR_ERROR = "#ef4444"
CLR_TEXT_DIM = "#94a3b8"
CLR_DIVIDER = "#2a2f40"


# ══════════════════════════════════════════════════════════════════════
#  Custom Prompt Dialog (supports password masking)
# ══════════════════════════════════════════════════════════════════════
class PromptDialog(ctk.CTkToplevel):
    """Modal dialog that asks for a single text input."""

    def __init__(
        self,
        parent: Any,
        title: str = "Input",
        text: str = "",
        show: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("420x210")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._result: str | None = None

        ctk.CTkLabel(
            self, text=text, wraplength=360,
            font=ctk.CTkFont(size=14),
        ).pack(padx=30, pady=(28, 12))

        show_kw = {"show": show} if show else {}
        self._entry = ctk.CTkEntry(self, width=320, height=40, **show_kw)
        self._entry.pack(padx=30)
        self._entry.focus_force()
        self._entry.bind("<Return>", lambda _: self._on_ok())

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=18)
        ctk.CTkButton(
            btn_row, text="Cancel", width=100, fg_color="transparent",
            border_width=1, command=self._on_cancel,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_row, text="OK", width=100, command=self._on_ok,
        ).pack(side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window()

    def _on_ok(self) -> None:
        self._result = self._entry.get()
        self.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.destroy()

    def get_input(self) -> str | None:
        return self._result


# ══════════════════════════════════════════════════════════════════════
#  GUI Log Handler  (async → GUI text widget)
# ══════════════════════════════════════════════════════════════════════
class _GUILogHandler(logging.Handler):
    """Pushes log records into a CTkTextbox via root.after()."""

    def __init__(self, textbox: ctk.CTkTextbox, root: ctk.CTk) -> None:
        super().__init__()
        self._tb = textbox
        self._root = root
        self.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-8s  %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        try:
            self._root.after(0, self._append, msg)
        except RuntimeError:
            pass  # window already destroyed

    def _append(self, msg: str) -> None:
        self._tb.configure(state="normal")
        self._tb.insert("end", msg + "\n")
        self._tb.see("end")
        self._tb.configure(state="disabled")


# ══════════════════════════════════════════════════════════════════════
#  Main Application
# ══════════════════════════════════════════════════════════════════════
class TelegramDriveApp(ctk.CTk):
    """T-Drive desktop application."""

    def __init__(self) -> None:
        super().__init__()

        self.title(f"{APP_NAME}  —  Telegram Cloud Drive")
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.minsize(820, 520)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.configure(fg_color=CLR_BG)

        # ── Window Icon ──
        if os.path.exists("app.ico"):
            self.iconbitmap("app.ico")


        # ── State ──
        self._config: AppConfig | None = None
        self._engine: SyncEngine | None = None
        self._client: Any = None          # TelegramClient
        self._sync_running = False
        self._connected = False
        self._bg_loop: asyncio.AbstractEventLoop | None = None
        self._bg_thread: threading.Thread | None = None
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._stat_cards: dict[str, ctk.CTkFrame] = {}

        # ── Try loading existing config ──
        try:
            self._config = load_config()
        except ConfigError:
            self._config = None

        # ── Logger ──
        log_file = self._config.log_file if self._config else "log.txt"
        setup_logger(log_file)

        # ── OS Registration ──
        from utils import register_tdrive_extension
        register_tdrive_extension()

        # ── Build UI ──
        self._build_sidebar()
        self._build_pages()

        # ── Background event loop ──
        self._start_async_bridge()

        # ── Show the right page ──
        if self._config and self._config.api_id and self._config.api_hash:
            self._show_page("dashboard")
            self.after(600, self._auto_connect)
        else:
            self._show_page("setup")
            
        # ── Check for Updates ──
        self.after(2000, self._check_updates)

    # ================================================================
    #  SIDEBAR
    # ================================================================
    def _build_sidebar(self) -> None:
        sb = ctk.CTkFrame(
            self, width=SIDEBAR_W, corner_radius=0,
            fg_color=CLR_SIDEBAR_BG,
        )
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── App branding ──
        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(22, 4))
        ctk.CTkLabel(
            brand, text="☁️", font=ctk.CTkFont(size=30),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text=APP_NAME,
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand, text="Telegram Cloud Drive",
            font=ctk.CTkFont(size=11), text_color=CLR_TEXT_DIM,
        ).pack(anchor="w")

        ctk.CTkFrame(sb, height=1, fg_color=CLR_DIVIDER).pack(
            fill="x", padx=16, pady=16,
        )

        # ── Navigation buttons ──
        nav_items = [
            ("setup", "🔑  Setup"),
            ("dashboard", "📂  Dashboard"),
            ("settings", "⚙  Settings"),
            ("about", "ℹ️  About"),
            ("help", "❓  Help"),
        ]
        for name, label in nav_items:
            btn = ctk.CTkButton(
                sb, text=label, anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=CLR_SIDEBAR_HOVER,
                height=40, corner_radius=8,
                font=ctk.CTkFont(size=14),
                command=lambda n=name: self._show_page(n),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[name] = btn

        # ── Open folder button ──
        ctk.CTkFrame(sb, height=1, fg_color=CLR_DIVIDER).pack(
            fill="x", padx=16, pady=12,
        )
        ctk.CTkButton(
            sb, text="📁  Open Folder", anchor="w",
            fg_color="transparent", hover_color=CLR_SIDEBAR_HOVER,
            height=36, corner_radius=8, font=ctk.CTkFont(size=13),
            command=self._open_sync_folder,
        ).pack(fill="x", padx=10, pady=2)

        # ── Branding (Created by Harry) ──
        ctk.CTkLabel(
            sb, text="Created by Harry",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=CLR_ACCENT,
        ).pack(side="bottom", pady=30)

        # ── Spacer ──
        ctk.CTkFrame(sb, fg_color="transparent").pack(fill="both", expand=True)

        # ── Connection status ──
        self._status_dot = ctk.CTkLabel(
            sb, text="●  Disconnected",
            font=ctk.CTkFont(size=12), text_color=CLR_ERROR,
        )
        self._status_dot.pack(padx=16, pady=(0, 4), anchor="w")

        ctk.CTkLabel(
            sb, text=f"v{VERSION}",
            font=ctk.CTkFont(size=10), text_color=CLR_TEXT_DIM,
        ).pack(padx=16, pady=(0, 16), anchor="w")

    # ================================================================
    #  PAGE CONTAINER
    # ================================================================
    def _build_pages(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=0, column=1, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        self._container = container

        self._build_setup_page(container)
        self._build_dashboard_page(container)
        self._build_settings_page(container)
        self._build_about_page(container)
        self._build_help_page(container)

    def _show_page(self, name: str) -> None:
        for frame in self._pages.values():
            frame.grid_forget()
        self._pages[name].grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        for n, btn in self._nav_buttons.items():
            btn.configure(fg_color=CLR_ACCENT if n == name else "transparent")

    # ================================================================
    #  SETUP PAGE
    # ================================================================
    def _build_setup_page(self, parent: ctk.CTkFrame) -> None:
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._pages["setup"] = page

        ctk.CTkLabel(
            page, text="Welcome to T-Drive",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(anchor="w", pady=(10, 2))
        ctk.CTkLabel(
            page,
            text="Enter your Telegram API credentials to get started.",
            font=ctk.CTkFont(size=13), text_color=CLR_TEXT_DIM,
            wraplength=620,
        ).pack(anchor="w", pady=(0, 4))

        ctk.CTkButton(
            page,
            text="Get API credentials at my.telegram.org ↗",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=CLR_ACCENT,
            fg_color="transparent",
            hover_color=CLR_SIDEBAR_HOVER,
            height=28,
            command=lambda: webbrowser.open("https://my.telegram.org/auth")
        ).pack(anchor="w", pady=(0, 22), padx=(0, 0))

        card = ctk.CTkFrame(page, fg_color=CLR_CARD, corner_radius=14, border_width=1, border_color=CLR_DIVIDER)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=32, pady=28)

        # ── API ID ──
        self._inp_api_id = self._labelled_entry(
            inner, "API ID", "e.g. 12345678",
        )
        # ── API Hash ──
        self._inp_api_hash = self._labelled_entry(
            inner, "API Hash", "e.g. 0123456789abcdef0123456789abcdef",
        )
        # ── Local Folder ──
        ctk.CTkLabel(
            inner, text="Local Sync Folder",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(0, 16))
        self._inp_folder = ctk.CTkEntry(
            row, placeholder_text="C:/TelegramDrive", height=40,
        )
        self._inp_folder.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            row, text="Browse", width=90, height=40,
            command=self._browse_folder,
        ).pack(side="right")

        # ── Drive letter (Windows only) ──
        if IS_WINDOWS:
            self._inp_drive = self._labelled_entry(
                inner, "Drive Letter (Windows)", "G", width=90,
            )
        else:
            self._inp_drive = None

        # ── Sync interval ──
        self._inp_interval = self._labelled_entry(
            inner, "Sync Interval (seconds)", "60", width=120,
        )

        # ── Pre-fill from existing config ──
        if self._config:
            self._set_entry(self._inp_api_id, str(self._config.api_id) if self._config.api_id else "")
            self._set_entry(self._inp_api_hash, self._config.api_hash or "")
            self._set_entry(self._inp_folder, self._config.local_folder or "C:/TelegramDrive")
            if self._inp_drive:
                self._set_entry(self._inp_drive, self._config.drive_letter or "G")
            self._set_entry(self._inp_interval, str(self._config.sync_interval or 60))

        # ── Connect button ──
        self._btn_connect = ctk.CTkButton(
            inner, text="Save & Connect", height=46,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._save_and_connect,
        )
        self._btn_connect.pack(fill="x", pady=(8, 0))

        self._setup_status = ctk.CTkLabel(
            inner, text="", font=ctk.CTkFont(size=12),
        )
        self._setup_status.pack(pady=(10, 0))

    # ── helpers ──

    @staticmethod
    def _labelled_entry(
        parent: ctk.CTkFrame,
        label: str,
        placeholder: str,
        width: int | None = None,
    ) -> ctk.CTkEntry:
        ctk.CTkLabel(
            parent, text=label,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        kw: dict[str, Any] = {"placeholder_text": placeholder, "height": 40}
        if width:
            kw["width"] = width
        entry = ctk.CTkEntry(parent, **kw)
        entry.pack(anchor="w", pady=(0, 16), fill="x" if not width else None)
        return entry

    @staticmethod
    def _set_entry(entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    def _browse_folder(self) -> None:
        path = filedialog.askdirectory(title="Select Sync Folder")
        if path:
            self._set_entry(self._inp_folder, path)

    def _open_sync_folder(self) -> None:
        folder = self._config.local_folder if self._config else None
        if folder and Path(folder).exists():
            open_folder_in_explorer(folder)
        else:
            messagebox.showinfo("T-Drive", "Sync folder not configured yet.")

    def _save_and_connect(self) -> None:
        api_id = self._inp_api_id.get().strip()
        api_hash = self._inp_api_hash.get().strip()
        folder = self._inp_folder.get().strip() or "C:/TelegramDrive"
        drive = self._inp_drive.get().strip() if self._inp_drive else ""
        interval = self._inp_interval.get().strip() or "60"

        if not api_id or not api_hash:
            self._setup_status.configure(
                text="⚠  API ID and API Hash are required.",
                text_color=CLR_WARNING,
            )
            return
        try:
            api_id_int = int(api_id)
        except ValueError:
            self._setup_status.configure(
                text="⚠  API ID must be a number.",
                text_color=CLR_WARNING,
            )
            return

        cfg_data = {
            "api_id": api_id_int,
            "api_hash": api_hash,
            "local_folder": folder,
            "sync_interval": int(interval),
            "drive_letter": drive or "G",
            "log_file": "log.txt",
            "db_file": "sync_db.json",
            "session_name": "telegram_drive_session",
            "hash_algorithm": self._config.hash_algorithm if self._config else "md5",
            "delete_sync": self._config.delete_sync if self._config else True,
            "max_retries": self._config.max_retries if self._config else 5,
            "retry_delay": self._config.retry_delay if self._config else 10,
        }
        save_config(cfg_data)
        self._config = AppConfig(**cfg_data)

        self._setup_status.configure(text="Connecting …", text_color=CLR_ACCENT)
        self._btn_connect.configure(state="disabled", text="Connecting …")
        self._run_async(self._connect_telegram())

    # ================================================================
    #  DASHBOARD PAGE
    # ================================================================
    def _build_dashboard_page(self, parent: ctk.CTkFrame) -> None:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self._pages["dashboard"] = page
        page.grid_columnconfigure(0, weight=1)

        # ── Header ──
        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", pady=(8, 16))

        self._dash_title = ctk.CTkLabel(
            header, text="Dashboard",
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        self._dash_title.pack(side="left")

        self._btn_sync = ctk.CTkButton(
            header, text="▶  Start Sync", width=150, height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=CLR_SUCCESS, hover_color="#16a34a",
            command=self._toggle_sync,
        )
        self._btn_sync.pack(side="right")

        # ── Stat cards ──
        cards_row = ctk.CTkFrame(page, fg_color="transparent")
        cards_row.pack(fill="x", pady=(0, 16))
        cards_row.grid_columnconfigure((0, 1, 2, 3), weight=1)

        card_defs = [
            ("status", "Status", "🔗", "—"),
            ("files", "Files", "📄", "0"),
            ("size", "Total Size", "💾", "0.0 B"),
            ("last_sync", "Last Sync", "🕐", "—"),
        ]
        for i, (key, label, icon, default) in enumerate(card_defs):
            card = self._make_stat_card(cards_row, icon, label, default)
            card.grid(row=0, column=i, sticky="nsew", padx=6)
            self._stat_cards[key] = card

        # ── File list ──
        ctk.CTkLabel(
            page, text="Synced Files",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", pady=(4, 6))

        self._file_list = ctk.CTkTextbox(
            page, height=160,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=CLR_CARD, corner_radius=10, state="disabled",
        )
        self._file_list.pack(fill="both", expand=False, pady=(0, 12))

        # ── Activity log ──
        ctk.CTkLabel(
            page, text="Activity Log",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", pady=(4, 6))

        self._log_box = ctk.CTkTextbox(
            page, height=170,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=CLR_CARD, corner_radius=10, state="disabled",
        )
        self._log_box.pack(fill="both", expand=True)

        # ── Attach log handler ──
        gui_handler = _GUILogHandler(self._log_box, self)
        gui_handler.setLevel(logging.DEBUG)
        logging.getLogger("TelegramDrive").addHandler(gui_handler)

    @staticmethod
    def _make_stat_card(
        parent: ctk.CTkFrame, icon: str, label: str, value: str,
    ) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent, fg_color=CLR_CARD, corner_radius=12, height=100,
            border_width=1, border_color=CLR_DIVIDER,
        )
        card.pack_propagate(False)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(expand=True, padx=14, pady=10)

        ctk.CTkLabel(inner, text=icon, font=ctk.CTkFont(size=20)).pack(anchor="w")
        val_lbl = ctk.CTkLabel(
            inner, text=value, font=ctk.CTkFont(size=18, weight="bold"),
        )
        val_lbl.pack(anchor="w")
        ctk.CTkLabel(
            inner, text=label,
            font=ctk.CTkFont(size=11), text_color=CLR_TEXT_DIM,
        ).pack(anchor="w")

        card._value_label = val_lbl  # type: ignore[attr-defined]
        return card

    def _update_stat(self, key: str, value: str) -> None:
        card = self._stat_cards.get(key)
        if card:
            card._value_label.configure(text=value)  # type: ignore[attr-defined]

    # ================================================================
    #  SETTINGS PAGE
    # ================================================================
    def _build_settings_page(self, parent: ctk.CTkFrame) -> None:
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._pages["settings"] = page

        ctk.CTkLabel(
            page, text="Settings",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).pack(anchor="w", pady=(8, 18))

        card = ctk.CTkFrame(page, fg_color=CLR_CARD, corner_radius=14, border_width=1, border_color=CLR_DIVIDER)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=32, pady=28)

        # ── Delete sync ──
        self._set_delete = ctk.CTkSwitch(
            inner, text="Delete sync (When turned on, files are deleted from cloud when deleted from PC)",
            font=ctk.CTkFont(size=13),
        )
        if self._config and self._config.delete_sync:
            self._set_delete.select()
        self._set_delete.pack(anchor="w", pady=(0, 18))

        # ── On-Demand Sync ──
        self._set_on_demand = ctk.CTkSwitch(
            inner, text="On-Demand Sync (Saves disk space; files download from cloud only when opened)",
            font=ctk.CTkFont(size=13),
        )
        if self._config and getattr(self._config, "on_demand_sync", False):
            self._set_on_demand.select()
        self._set_on_demand.pack(anchor="w", pady=(0, 18))

        # ── Max retries ──
        ctk.CTkLabel(
            inner, text="Max Retries",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        self._set_retries = ctk.CTkEntry(inner, height=38, width=100)
        self._set_retries.insert(
            0, str(self._config.max_retries if self._config else 5),
        )
        self._set_retries.pack(anchor="w", pady=(0, 18))

        # ── Retry delay ──
        ctk.CTkLabel(
            inner, text="Retry Delay (seconds)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        self._set_delay = ctk.CTkEntry(inner, height=38, width=100)
        self._set_delay.insert(
            0, str(self._config.retry_delay if self._config else 10),
        )
        self._set_delay.pack(anchor="w", pady=(0, 18))

        # ── Session name ──
        ctk.CTkLabel(
            inner, text="Session Name",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        self._set_session = ctk.CTkEntry(inner, height=38, width=280)
        self._set_session.insert(
            0,
            self._config.session_name
            if self._config
            else "telegram_drive_session",
        )
        self._set_session.pack(anchor="w", pady=(0, 22))

        # ── Save button ──
        ctk.CTkButton(
            inner, text="Save Settings", height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._save_settings,
        ).pack(anchor="w")

        self._settings_status = ctk.CTkLabel(
            inner, text="", font=ctk.CTkFont(size=12),
        )
        self._settings_status.pack(anchor="w", pady=(10, 0))

    def _save_settings(self) -> None:
        if not self._config:
            self._settings_status.configure(
                text="⚠  Complete setup first.", text_color=CLR_WARNING,
            )
            return

        self._config.hash_algorithm = "md5" # Hardcoded for simplicity
        self._config.delete_sync = bool(self._set_delete.get())
        self._config.on_demand_sync = bool(self._set_on_demand.get())
        self._config.max_retries = int(self._set_retries.get() or 5)
        self._config.retry_delay = int(self._set_delay.get() or 10)
        self._config.session_name = (
            self._set_session.get() or "telegram_drive_session"
        )

        save_config(self._config)
        self._settings_status.configure(
            text="✓  Settings saved.", text_color=CLR_SUCCESS,
        )

    # ================================================================
    #  ABOUT PAGE
    # ================================================================
    def _build_about_page(self, parent: ctk.CTkFrame) -> None:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self._pages["about"] = page

        ctk.CTkLabel(
            page, text="About T-Drive",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).pack(anchor="w", pady=(8, 16))

        card = ctk.CTkFrame(page, fg_color=CLR_CARD, corner_radius=14, border_width=1, border_color=CLR_DIVIDER)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=32, pady=28)

        lines: list[tuple[str, ctk.CTkFont, str | None]] = [
            ("☁️  T-Drive", ctk.CTkFont(size=22, weight="bold"), None),
            (f"Version {VERSION}", ctk.CTkFont(size=13), CLR_TEXT_DIM),
            ("Created by Harry", ctk.CTkFont(size=14, weight="bold"), CLR_ACCENT),
            ("", ctk.CTkFont(size=6), None),
            (
                "A lightweight cloud storage powered by Telegram.",
                ctk.CTkFont(size=14),
                None,
            ),
            (
                "Files are synced to your Saved Messages.",
                ctk.CTkFont(size=14),
                None,
            ),
            ("", ctk.CTkFont(size=10), None),
            ("Features", ctk.CTkFont(size=15, weight="bold"), None),
            ("  •  Two-way file synchronisation", ctk.CTkFont(size=13), None),
            ("  •  Delete sync (mirror deletions)", ctk.CTkFont(size=13), None),
            ("  •  Sub-folder support", ctk.CTkFont(size=13), None),
            ("  •  Duplicate prevention (hash-based)", ctk.CTkFont(size=13), None),
            ("  •  Virtual drive mount (Windows)", ctk.CTkFont(size=13), None),
            ("  •  Automatic retry on errors", ctk.CTkFont(size=13), None),
            ("  •  Cross-platform (Windows + macOS)", ctk.CTkFont(size=13), None),
            ("", ctk.CTkFont(size=10), None),
            (
                "Built with Python · Telethon · CustomTkinter",
                ctk.CTkFont(size=12),
                CLR_TEXT_DIM,
            ),
        ]
        for text, font, color in lines:
            kw: dict[str, Any] = {}
            if color:
                kw["text_color"] = color
            ctk.CTkLabel(inner, text=text, font=font, **kw).pack(anchor="w")
    def _build_help_page(self, parent: ctk.CTkFrame) -> None:
        page = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self._pages["help"] = page

        ctk.CTkLabel(
            page, text="How to Use T‑Drive",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).pack(anchor="w", pady=(8, 16))

        card = ctk.CTkFrame(page, fg_color=CLR_CARD, corner_radius=14, border_width=1, border_color=CLR_DIVIDER)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=32, pady=28)

        guide_text = (
            "1️⃣  Launch the app.\n\n"
            "2️⃣  In the Setup page, enter your Telegram API ID and Hash.\n\n"
            "3️⃣  Choose a local sync folder (default: C:/TelegramDrive).\n\n"
            "4️⃣  (Windows) Set a drive letter, e.g., G.\n\n"
            "5️⃣  Click ‘Save & Connect’; follow the phone‑number, code, and 2FA dialogs.\n\n"
            "6️⃣  Once connected, go to Dashboard and press ▶ Start Sync.\n\n"
            "7️⃣  Files placed in the sync folder will upload to Telegram; messages tagged with #TDrive will download locally.\n\n"
            "8️⃣  Use Settings to adjust hash algorithm, delete‑sync, retry policy, and appearance mode.\n\n"
            "9️⃣  The Open Folder button opens the sync directory in Explorer/Finder.\n\n"
            "🔟  For a portable version without Python, download the pre‑built executable from the releases page."
        )
        ctk.CTkLabel(
            inner, text=guide_text,
            font=ctk.CTkFont(size=14),
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=0)

    # ================================================================
    #  ASYNC BRIDGE  (background event loop in a daemon thread)
    # ================================================================
    def _start_async_bridge(self) -> None:
        self._bg_loop = asyncio.new_event_loop()
        self._bg_thread = threading.Thread(
            target=self._run_bg_loop, daemon=True,
        )
        self._bg_thread.start()

    def _run_bg_loop(self) -> None:
        asyncio.set_event_loop(self._bg_loop)
        self._bg_loop.create_task(self._start_ipc_server())
        self._bg_loop.run_forever()

    async def _start_ipc_server(self) -> None:
        try:
            server = await asyncio.start_server(self._handle_ipc_client, '127.0.0.1', 50321)
            async with server:
                await server.serve_forever()
        except Exception:
            pass

    async def _handle_ipc_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await reader.read(4096)
            path = data.decode('utf-8').strip()
            
            # Instantly acknowledge receipt so main.py doesn't timeout!
            writer.write(b"OK")
            await writer.drain()
            
            # Fire and forget the hydration task
            if "|" in path:
                rel, mid = path.split("|", 1)
                self._bg_loop.create_task(self._hydrate_lnk(rel, mid))
            elif path.endswith(".tdrive"):
                self._bg_loop.create_task(self._hydrate_file(path))
        except Exception:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _hydrate_file(self, stub_path: str) -> None:
        if not self._client or not self._engine: return
        log = get_logger()
        log.info("Hydrating stub file: %s", stub_path)
        try:
            sp = Path(stub_path)
            if not sp.exists(): return
            data = json.loads(sp.read_text(encoding="utf-8"))
            msg_id = data.get("message_id")
            if not msg_id: return
            
            self._gui_status(f"Hydrating {sp.name}...", CLR_ACCENT)
            messages = await self._client.get_messages("me", ids=[msg_id])
            if messages and messages[0]:
                msg = messages[0]
                dest = sp.with_suffix('') # Remove .tdrive
                await self._engine._download_file(msg, data.get("rel_path", ""), dest)
                sp.unlink() # Delete stub
                self._gui_status(f"Hydrated {dest.name}", CLR_SUCCESS)
                
                if IS_WINDOWS:
                    import os
                    os.startfile(str(dest))
                
                self._bg_loop.create_task(self._revert_schedule(dest, data))
        except Exception as e:
            log.error("Failed to hydrate file: %s", e)

    async def _hydrate_lnk(self, rel_path: str, msg_id_str: str) -> None:
        if not self._client or not self._engine: return
        log = get_logger()
        log.info("Hydrating smart stub: %s", rel_path)
        try:
            msg_id = int(msg_id_str)
            dest = self._engine.local / rel_path
            stub_path = dest.with_name(dest.name + ".lnk")
            
            self._gui_status(f"Hydrating {dest.name}...", CLR_ACCENT)
            messages = await self._client.get_messages("me", ids=[msg_id])
            if messages and messages[0]:
                msg = messages[0]
                await self._engine._download_file(msg, rel_path, dest)
                try:
                    if stub_path.exists():
                        stub_path.unlink() # Delete LNK stub
                except OSError:
                    pass
                self._gui_status(f"Hydrated {dest.name}", CLR_SUCCESS)
                
                if IS_WINDOWS:
                    import os
                    os.startfile(str(dest))
                
                data = {"rel_path": rel_path, "message_id": msg_id, "size": dest.stat().st_size}
                self._bg_loop.create_task(self._revert_schedule(dest, data))
        except Exception as e:
            log.error("Failed to hydrate smart stub: %s", e)

    async def _revert_schedule(self, dest: Path, data: dict) -> None:
        """Wait 2 minutes and revert the file back to a stub to save space."""
        import os
        import json
        log = get_logger()
        rel_path = data.get("rel_path", "")
        
        # Try reverting after 2 mins, if failed (in use), retry again up to 5 times
        for _ in range(5):
            await asyncio.sleep(120)
            if not dest.exists():
                break # User manually deleted
            
            log.info("Attempting to revert %s back to stub...", dest.name)
            try:
                # Try unlinking first so we know it's not locked
                dest.unlink()
                
                if self._engine and self._client:
                    # Fetch live message_id from DB in case file was re-uploaded
                    entry = self._engine.db.get(rel_path) or {}
                    live_msg_id = entry.get("message_id", data.get("message_id"))
                    
                    # Fetch message to regenerate smart stub thumbnail
                    messages = await self._client.get_messages("me", ids=[live_msg_id])
                    if messages and messages[0]:
                        msg = messages[0]
                        from sync import create_lnk_stub
                        await create_lnk_stub(self._client, msg, self._engine.local, rel_path)
                        
                        self._engine.db.upsert(rel_path, {
                            "filename": dest.name,
                            "size": entry.get("size", data.get("size", 0)),
                            "hash": "STUB",
                            "message_id": live_msg_id,
                            "last_synced": entry.get("last_synced", ""),
                            "deleted": False,
                        })
                log.info("Reverted %s to save space.", dest.name)
                break
            except PermissionError:
                log.info("File %s is in use by another program. Will retry reverting later.", dest.name)
            except Exception as e:
                log.error("Error reverting stub %s: %s", dest.name, e)
                break

    def _run_async(self, coro: Any) -> asyncio.Future:
        """Submit a coroutine to the background event loop."""
        return asyncio.run_coroutine_threadsafe(coro, self._bg_loop)  # type: ignore[arg-type]

    # ================================================================
    #  TELEGRAM CONNECTION  (runs in background loop)
    # ================================================================
    def _auto_connect(self) -> None:
        """Auto-connect on startup if credentials exist."""
        self._run_async(self._connect_telegram())

    async def _connect_telegram(self) -> None:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError

        log = get_logger()
        cfg = self._config
        if not cfg:
            return

        try:
            client = TelegramClient(
                cfg.session_name, cfg.api_id, cfg.api_hash,
            )
            await client.connect()

            if not await client.is_user_authorized():
                # ── Phone number ──
                phone = await self._prompt_gui(
                    "Enter your phone number\n(with country code, e.g. +1234567890):",
                    "Phone Number",
                )
                if not phone:
                    self._gui_status("Cancelled.", CLR_WARNING)
                    return

                await client.send_code_request(phone)

                # ── Verification code ──
                code = await self._prompt_gui(
                    "Enter the code sent to your Telegram app:",
                    "Verification Code",
                )
                if not code:
                    self._gui_status("Cancelled.", CLR_WARNING)
                    return

                try:
                    await client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    # ── 2FA password ──
                    password = await self._prompt_gui(
                        "Enter your Two-Factor Authentication password:",
                        "2FA Password",
                        show="•",
                    )
                    if not password:
                        self._gui_status("Cancelled.", CLR_WARNING)
                        return
                    await client.sign_in(password=password)

            me = await client.get_me()
            self._client = client
            self._connected = True
            name = me.first_name or "User"
            log.info("Authenticated as %s (ID: %s)", name, me.id)
            self.after(0, self._on_connected, name)

        except Exception as exc:
            log.error("Connection failed: %s", exc)
            self.after(0, self._on_connect_failed, str(exc))

    async def _prompt_gui(
        self, text: str, title: str, show: str | None = None,
    ) -> str | None:
        """
        Show a modal dialog from the main thread while awaiting in the
        background event loop (non-blocking for asyncio).
        """
        result: list[str | None] = [None]
        done = asyncio.Event()

        def _show() -> None:
            dialog = PromptDialog(self, title=title, text=text, show=show)
            result[0] = dialog.get_input()
            self._bg_loop.call_soon_threadsafe(done.set)  # type: ignore[union-attr]

        self.after(0, _show)
        await done.wait()
        return result[0]

    # ── GUI callbacks (main thread) ──

    def _on_connected(self, name: str) -> None:
        self._status_dot.configure(
            text=f"●  {name}", text_color=CLR_SUCCESS,
        )
        self._update_stat("status", "Connected")
        self._setup_status.configure(
            text=f"✓  Connected as {name}", text_color=CLR_SUCCESS,
        )
        self._btn_connect.configure(state="normal", text="Save & Connect")
        self._show_page("dashboard")

    def _on_connect_failed(self, error: str) -> None:
        self._status_dot.configure(
            text="●  Disconnected", text_color=CLR_ERROR,
        )
        self._update_stat("status", "Error")
        short = error[:80] + ("…" if len(error) > 80 else "")
        self._setup_status.configure(
            text=f"✗  {short}", text_color=CLR_ERROR,
        )
        self._btn_connect.configure(state="normal", text="Save & Connect")

    def _gui_status(self, text: str, color: str) -> None:
        """Thread-safe helper to update setup status."""
        self.after(
            0,
            lambda: (
                self._setup_status.configure(text=text, text_color=color),
                self._btn_connect.configure(state="normal", text="Save & Connect"),
            ),
        )

    # ================================================================
    #  SYNC CONTROL
    # ================================================================
    def _toggle_sync(self) -> None:
        if self._sync_running:
            self._run_async(self._stop_sync())
        else:
            if not self._connected:
                messagebox.showwarning(
                    "Not Connected",
                    "Please connect to Telegram first via the Setup page.",
                )
                return
            self._run_async(self._start_sync())

    async def _start_sync(self) -> None:
        log = get_logger()
        cfg = self._config
        if not cfg:
            return

        # Mount virtual drive (Windows)
        if IS_WINDOWS:
            mount_drive(cfg.drive_letter, cfg.local_folder)

        self._engine = SyncEngine(cfg)
        self._engine.client = self._client
        self._engine._running = True
        self._sync_running = True
        self.after(0, self._on_sync_started)
        log.info("Sync engine started.")

        # Start periodic status polling
        self.after(2000, self._poll_status)

        try:
            await self._engine.run_forever()
        except asyncio.CancelledError:
            pass

    async def _stop_sync(self) -> None:
        log = get_logger()
        if self._engine:
            self._engine._running = False
        self._sync_running = False
        log.info("Sync engine stopped.")
        self.after(0, self._on_sync_stopped)

    def _on_sync_started(self) -> None:
        self._btn_sync.configure(
            text="⏹  Stop Sync",
            fg_color=CLR_ERROR,
            hover_color="#dc2626",
        )

    def _on_sync_stopped(self) -> None:
        self._btn_sync.configure(
            text="▶  Start Sync",
            fg_color=CLR_SUCCESS,
            hover_color="#16a34a",
        )

    # ================================================================
    #  STATUS POLLING
    # ================================================================
    def _poll_status(self) -> None:
        if not self._sync_running or not self._engine:
            return

        db = self._engine.db
        entries = db.active_entries()
        total = sum(e.get("size", 0) for e in entries.values())

        self._update_stat("files", str(len(entries)))
        self._update_stat("size", human_size(total))

        # ── Last-sync time ──
        times = [
            e.get("last_synced", "")
            for e in entries.values()
            if e.get("last_synced")
        ]
        if times:
            try:
                latest = max(times)
                dt = datetime.fromisoformat(latest)
                now = datetime.now(timezone.utc)
                ago = int((now - dt).total_seconds())
                if ago < 60:
                    self._update_stat("last_sync", f"{ago}s ago")
                elif ago < 3600:
                    self._update_stat("last_sync", f"{ago // 60}m ago")
                else:
                    self._update_stat("last_sync", f"{ago // 3600}h ago")
            except Exception:
                self._update_stat("last_sync", "—")

        self._refresh_file_list(entries)
        self.after(3000, self._poll_status)

    def _refresh_file_list(self, entries: dict[str, Any] | None = None) -> None:
        if entries is None:
            if self._engine:
                entries = self._engine.db.active_entries()
            else:
                return

        self._file_list.configure(state="normal")
        self._file_list.delete("1.0", "end")

        if not entries:
            self._file_list.insert("end", "  No files synced yet.\n")
        else:
            hdr = f"  {'File':<45} {'Size':>10}  {'Msg ID':>8}\n"
            self._file_list.insert("end", hdr)
            self._file_list.insert("end", "  " + "─" * 68 + "\n")
            for rel, e in sorted(entries.items()):
                line = (
                    f"  {rel:<45} "
                    f"{human_size(e.get('size', 0)):>10}  "
                    f"{e.get('message_id', '?'):>8}\n"
                )
                self._file_list.insert("end", line)

        self._file_list.configure(state="disabled")

    # ================================================================
    #  Updates
    # ================================================================
    def _check_updates(self) -> None:
        """Fetch remote version and force update if local is old."""
        import urllib.request
        
        def run_check():
            try:
                # We expect a JSON file like: {"version": "1.1.0", "url": "https://..."}
                with urllib.request.urlopen(UPDATE_CHECK_URL, timeout=10) as response:
                    resp_data = response.read().decode()
                    data = json.loads(resp_data)
                    latest_version = data.get("version")
                    download_url = data.get("url", "https://github.com/") 
                    
                    if latest_version and latest_version > VERSION:
                        # Update found! Force the UI to show the update modal
                        self.after(0, lambda: self._show_update_modal(latest_version, download_url))
            except Exception as e:
                # Silently ignore failures (e.g. no internet) during the background check
                pass

        threading.Thread(target=run_check, daemon=True).start()

    def _show_update_modal(self, new_version: str, url: str) -> None:
        """Show a mandatory, blocking update window."""
        modal = ctk.CTkToplevel(self)
        modal.title("Update Required")
        modal.geometry("450x320")
        modal.resizable(False, False)
        modal.attributes("-topmost", True)
        
        # Center the modal
        modal.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (modal.winfo_width() // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (modal.winfo_height() // 2)
        modal.geometry(f"+{x}+{y}")

        # Kill app if they try to close modal
        modal.protocol("WM_DELETE_WINDOW", lambda: self._quit_app(None, None))
        
        ctk.CTkLabel(
            modal, text="🚀", font=ctk.CTkFont(size=60)
        ).pack(pady=(30, 10))
        
        from utils import CLR_ACCENT, CLR_TEXT_DIM
        ctk.CTkLabel(
            modal, text="A New Version is Available!",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=CLR_ACCENT
        ).pack()
        
        ctk.CTkLabel(
            modal, text=f"Current: v{VERSION}  ➡  Latest: v{new_version}",
            font=ctk.CTkFont(size=14), text_color=CLR_TEXT_DIM
        ).pack(pady=5)

        ctk.CTkLabel(
            modal, text="This update is critical for security and\nperformance. You must update to continue.",
            font=ctk.CTkFont(size=13), justify="center"
        ).pack(pady=15)

        def go_to_url():
            webbrowser.open(url)
            self._quit_app(None, None)

        ctk.CTkButton(
            modal, text="Download & Install Update", 
            fg_color=CLR_ACCENT, hover_color="#4338ca",
            height=40, font=ctk.CTkFont(weight="bold"),
            command=go_to_url
        ).pack(pady=10)
        
        # Block interaction with main window
        modal.grab_set()

    # ================================================================
    #  SYSTEM TRAY & CLEANUP
    # ================================================================
    def _create_tray_image(self) -> Image.Image:
        image = Image.new('RGB', (64, 64), color="#151822")
        d = ImageDraw.Draw(image)
        d.ellipse((16, 16, 48, 48), fill="#4f46e5")
        return image

    def _minimize_to_tray(self) -> None:
        self.withdraw()  # Hide window
        
        if notification:
            try:
                notification.notify(
                    title="T-Drive",
                    message="T-Drive is now running in the background.",
                    app_name="T-Drive",
                    timeout=3
                )
            except Exception:
                pass

        if not hasattr(self, "_tray_icon") or self._tray_icon is None:
            menu = pystray.Menu(
                pystray.MenuItem('Show Dashboard', self._show_window, default=True),
                pystray.MenuItem('Quit T-Drive', self._quit_app)
            )
            self._tray_icon = pystray.Icon("TDrive", self._create_tray_image(), "T-Drive", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _show_window(self, icon: Any, item: Any) -> None:
        self.after(0, self.deiconify)

    def _quit_app(self, icon: Any, item: Any) -> None:
        if hasattr(self, "_tray_icon") and self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self._actual_close)

    def _on_close(self) -> None:
        self._minimize_to_tray()

    def _actual_close(self) -> None:
        if self._sync_running and self._engine:
            self._engine._running = False
        if self._client:
            try:
                self._run_async(self._client.disconnect())
            except Exception:
                pass
        if self._bg_loop:
            self._bg_loop.call_soon_threadsafe(self._bg_loop.stop)
        if self._bg_thread:
            self._bg_thread.join(timeout=3)
        self.destroy()


# ══════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════
def main() -> None:
    app = TelegramDriveApp()
    app.mainloop()


if __name__ == "__main__":
    main()
