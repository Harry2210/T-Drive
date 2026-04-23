"""
Telegram Cloud Drive — Entry Point
Launches the desktop GUI application.
"""

import sys
import ctypes
import os

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def notify_hydration(path: str, msg_id: str = "") -> None:
    import socket
    import tkinter.messagebox
    import tkinter as tk
    root = tk.Tk()
    root.withdraw() # Hide the main window
    try:
        payload = f"{path}|{msg_id}" if msg_id else path
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(('127.0.0.1', 50321))
        s.sendall(payload.encode('utf-8'))
        s.recv(1024)
        s.close()
    except Exception:
        return False
    return True

if __name__ == "__main__":
    if not is_admin():
        # Re-launch the program with admin rights
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()

    # Robust argument parsing:
    # If we are running from a script, sys.argv[1] might be 'main.py' or 'hydrate'.
    # If we are running from a bundled EXE, sys.argv[1] should be 'hydrate'.
    
    args = sys.argv[1:]
    
    # Skip the script name if it somehow ended up in the arguments (common in some bundling/shortcut scenarios)
    if args and (args[0].endswith('.py') or 'main.py' in args[0].lower()):
        args = args[1:]
        
    # Check if we should try to notify a running instance
    success = False
    
    if not args:
        # User just opened the app manually
        if notify_hydration("FOCUS"):
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("T-Drive", "T-Drive is already running.")
            sys.exit()

    if args and args[0].endswith('.tdrive'):
        success = notify_hydration(args[0])
    elif len(args) > 1 and args[0] == "hydrate" and args[1].endswith('.tdrive'):
        success = notify_hydration(args[1])
    elif len(args) > 2 and args[0] == "hydrate":
        success = notify_hydration(args[1], args[2])
    elif "hydrate" in sys.argv:
        try:
            idx = sys.argv.index("hydrate")
            h_args = sys.argv[idx+1:]
            if len(h_args) >= 2:
                success = notify_hydration(h_args[0], h_args[1])
            elif len(h_args) >= 1:
                success = notify_hydration(h_args[0])
        except Exception:
            pass
            
    # If not a hydration request, or if notification failed (app not running), start the app
    if not success:
        if "unpin" in sys.argv:
            from utils import unpin_from_explorer_sidebar
            unpin_from_explorer_sidebar()
        else:
            from app import main
            main()
