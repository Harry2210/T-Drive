import os
import sys
import subprocess
import shutil
from pathlib import Path

def build():
    print("Starting T-Drive Windows Build...")
    
    # 1. Locate CustomTkinter (it needs to be bundled specially)
    import customtkinter
    ctk_path = os.path.dirname(customtkinter.__file__)
    
    # 2. Command preparation
    # --noconsole: Hide the black CMD window
    # --onefile: Pack everything into one EXE
    # --add-data: Include CustomTkinter themes
    dist_path = Path("dist")
    if dist_path.exists():
        shutil.rmtree(dist_path)

    cmd = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        "--icon=app.ico",
        "--add-data=" + f"{ctk_path}{os.pathsep}customtkinter",
        "--name=T-Drive",
        "--uac-admin",
        "main.py"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("\nSUCCESS! Your app is ready in the 'dist' folder.")
        print("File: dist/T-Drive.exe")
    else:
        print("\nFAILED! Build process exited with error.")
        print(result.stdout)
        print(result.stderr)

if __name__ == "__main__":
    build()
