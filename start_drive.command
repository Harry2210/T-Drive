#!/bin/bash
# ================================================================
#  T-Drive — macOS Auto-Start Script
#  Launches the T-Drive desktop application.
#
#  To auto-start on login:
#    System Settings → General → Login Items → add this file
# ================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[*] Launching T-Drive …"
cd "$SCRIPT_DIR"
python3 main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "[!] T-Drive exited with an error."
    read -p "Press Enter to close…"
fi
