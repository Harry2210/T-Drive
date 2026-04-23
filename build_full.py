import os
import subprocess
import shutil
from pathlib import Path

def run_step(name, command, shell=False):
    print(f"\n>>> Step: {name}...")
    try:
        # If it's a list, it's a direct process call. If it's a string, it might need a shell (especially for Inno Setup paths)
        result = subprocess.run(command, shell=shell, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"DONE: {name} finished successfully.")
            return True
        else:
            print(f"ERROR in {name}:")
            print(result.stdout)
            print(result.stderr)
            return False
    except Exception as e:
        print(f"CRITICAL ERROR: Could not run {name}: {e}")
        return False

def build_all():
    print("====================================================")
    print("      T-Drive Full Application Build System         ")
    print("====================================================\n")

    # 1. CLEANUP
    print(">>> Cleaning old build artifacts...")
    for folder in ["dist", "build"]:
        if os.path.exists(folder):
            shutil.rmtree(folder)
    
    installer_path = Path("T-Drive-Installer.exe")
    if installer_path.exists():
        installer_path.unlink()

    # 2. BUILD THE EXE (via build_windows.py)
    if not run_step("Compiling T-Drive EXE", ["python", "build_windows.py"]):
        return

    # 3. BUILD THE INSTALLER (via Inno Setup)
    # Note: We use shell=True to handle the space-containing path of Inno Setup
    inno_cmd = r'& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss'
    if not run_step("Generating Installer", ["powershell", "-Command", inno_cmd]):
        return

    # 4. FINAL CLEANUP
    print("\n>>> Performing final cleanup...")
    if os.path.exists("build"):
        shutil.rmtree("build")
    if os.path.exists("dist"):
        shutil.rmtree("dist")

    print("\n====================================================")
    print("       SUCCESS! BUILD PROCESS COMPLETE              ")
    print("====================================================")
    print(f"Your final installer is ready: {os.path.abspath('T-Drive-Installer.exe')}")
    print("====================================================")

if __name__ == "__main__":
    build_all()
