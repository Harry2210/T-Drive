# 🎉 T‑Drive – Quick‑Start & UI Polish Guide

## 📦 What is T‑Drive?
T‑Drive turns your **Telegram Saved Messages** into a personal cloud drive with two‑way sync. It runs on **Windows** and **macOS** with a sleek CustomTkinter GUI.

---

## 🛠️ Prerequisites
| Requirement | Why? |
|---|---|
| **Python 3.10+** (recommended 3.12) | Core language for the app. |
| **Internet connection** | Needed to talk to Telegram servers. |
| **Telegram API credentials** (`api_id` & `api_hash`) | Authenticates your app with Telegram. |

If you **don’t have Python installed**, you can still use T‑Drive by running the pre‑built executable (see *Packaging* below). No manual Python install is required for end‑users.

---

## 🚀 One‑Click Installation (No Python Needed)
1. **Download the latest release** from the GitHub releases page (e.g., `T-Drive-2.0.0-windows.zip`).
2. Extract the zip to a folder of your choice.
3. Run `T-Drive.exe` (Windows) or `T-Drive.app` (macOS).
4. The app will launch directly – no Python, no pip, no virtual environment.

> The executable is built with **PyInstaller** and bundles the Python interpreter, all dependencies, and the app code.

---

## 🖥️ Manual Installation (For developers or custom builds)
1. **Install Python** (if not present):
   - Windows: download from https://www.python.org/downloads/windows/ and **check “Add Python to PATH”.**
   - macOS: `brew install python@3.12` (or use the official installer).
2. Open a terminal/PowerShell and **navigate** to the project folder:
   ```bash
   cd "C:/Users/hario/Desktop/T-drive"
   ```
3. **Create a virtual environment** (optional but recommended):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   source .venv/bin/activate  # macOS
   ```
4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
5. **Run the app**:
   ```bash
   python main.py
   ```

---

## 📋 Step‑by‑Step Setup Inside the App
1. **Launch T‑Drive** (either the executable or `python main.py`).
2. **Setup Page** appears automatically.
   - **API ID** – enter the numeric ID from my.telegram.org.
   - **API Hash** – paste the 32‑character hash.
   - **Local Sync Folder** – default is `C:/TelegramDrive`. Click **Browse** to pick another folder.
   - **Drive Letter** (Windows only) – choose a free letter (default `G`).
   - **Sync Interval** – seconds between each sync (default `60`).
3. Click **Save & Connect**.
4. A series of modal dialogs will ask for:
   - **Phone number** (with country code, e.g., `+1234567890`).
   - **Verification code** sent to your Telegram app.
   - **2FA password** (if you have two‑factor authentication enabled).
5. Once connected, the **Dashboard** shows:
   - Connection status (green dot when online).
   - File count, total size, last sync time.
   - Live activity log.
6. Press **▶ Start Sync** to begin the two‑way synchronization.
7. Use the **Settings** page to tweak:
   - Hash algorithm (`md5` or `sha256`).
   - Delete‑sync toggle (mirrors deletions both ways).
   - Max retries & retry delay.
   - Session name.
8. The **Open Folder** button in the sidebar opens the sync folder in Explorer/Finder.

---

## 🎨 UI Polish Recommendations (Make it *even* more beautiful)
| Area | Current | Suggested Upgrade |
|---|---|---|
| **Color palette** | Dark‑blue theme with static colors. | Use a **gradient background** for the sidebar (e.g., `linear-gradient(135deg, #1e293b, #111827)`). |
| **Typography** | Default system fonts. | Load **Google Font “Inter”** via `customtkinter`'s `CTkFont` for a modern look. |
| **Buttons** | Solid colors, plain hover. | Add **subtle scaling** on hover (`hover_color` + `hover=True` with `scale=1.02`). |
| **Icons** | Emoji text. | Replace emojis with **SVG icons** (e.g., from `tabler-icons`). Load them with `CTkImage`. |
| **Cards** | Flat rectangles. | Apply **glass‑morphism**: semi‑transparent background (`#ffffff20`), backdrop blur, and soft shadows. |
| **Animations** | None. | Use `after`‑based fade‑in for the dashboard stats and a **spinner** while connecting. |
| **Responsive layout** | Fixed widths. | Make the sidebar width **percentage‑based** (`0.2 * window_width`) so it adapts to different screen sizes. |
| **Dark/Light mode** | Forced dark. | Add a **toggle** in Settings to switch between dark and light themes (`ctk.set_appearance_mode`). |

**Implementation tip**: Most of these can be done by tweaking the `app.py` constants (colors, fonts) and adding a few helper functions for gradients and icons. No external UI framework is needed.

---

## 📦 Packaging the App (No‑Python End‑User Experience)
1. **Install PyInstaller** in your development environment:
   ```bash
   pip install pyinstaller
   ```
2. **Create a spec file** (optional) to include resources like the app icon and the `README.md`.
3. Build the executable:
   ```bash
   pyinstaller --onefile --windowed --name T-Drive main.py
   ```
   - `--windowed` hides the console window.
   - `--onefile` bundles everything into a single exe.
4. The output will be in `dist/T-Drive.exe`. Distribute this file (or zip it with any needed config files).
5. For **macOS**, use:
   ```bash
   pyinstaller --onefile --windowed --name T-Drive main.py
   ```
   Then wrap the binary into an `.app` bundle using `py2app` or a simple script.

---

## ❓ Frequently Asked Questions
**Q: Do I need to keep Python installed after using the exe?**
- No. The bundled executable contains its own Python interpreter.

**Q: Can I run the app from a USB stick?**
- Yes. The portable exe works from any location; just keep the `sync_db.json` and `config.json` alongside it.

**Q: What if I want to change the sync folder later?**
- Open **Settings**, modify the **Local Sync Folder**, and click **Save Settings**. The app will re‑scan the new folder on the next sync.

---

## 📞 Need More Help?
Open an issue on the GitHub repo or drop a message in the **Telegram Support Channel** (link in the About page). Happy syncing! 🚀
