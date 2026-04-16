"""
Telegram Cloud Drive — Entry Point
Launches the desktop GUI application.
"""

import sys

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
        tkinter.messagebox.showerror(
            "T-Drive Not Running", 
            "Please ensure T-Drive is running in the background to open space-saving cloud files."
        )

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].endswith('.tdrive'):
        notify_hydration(sys.argv[1])
    elif len(sys.argv) > 2 and sys.argv[1] == "hydrate" and sys.argv[2].endswith('.tdrive'):
        notify_hydration(sys.argv[2])
    elif len(sys.argv) > 3 and sys.argv[1] == "hydrate":
        notify_hydration(sys.argv[2], sys.argv[3])
    else:
        from app import main
        main()
