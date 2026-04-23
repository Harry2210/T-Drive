import os
import sys
import shutil
import subprocess
import winreg
from pathlib import Path
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def create_shortcut(target, shortcut_path, name):
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.Targetpath = target
    shortcut.WorkingDirectory = str(Path(target).parent)
    shortcut.IconLocation = target
    shortcut.save()

def install():
    if not is_admin():
        print("Requesting administrator privileges...")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, __file__, None, 1)
        return

    app_name = "T-Drive"
    version = "2.0.0"
    install_dir = Path("C:/Program Files/T-Drive")
    exe_name = "T-Drive.exe"
    
    print(f"Installing {app_name} v{version}...")

    # 1. Create directory
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "Cloud").mkdir(parents=True, exist_ok=True)

    # 2. Copy files
    # Check if we are running as a PyInstaller bundle
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")

    src_exe = Path(base_path) / exe_name
    # Fallback to local dist if not found in bundle (for dev)
    if not src_exe.exists():
        src_exe = Path("dist") / exe_name
        
    if not src_exe.exists():
        print(f"Error: {src_exe} not found.")
        input("Press Enter to exit...")
        return

    shutil.copy2(src_exe, install_dir / exe_name)
    print(f"Files copied to {install_dir}")

    # 3. Create Shortcuts
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    start_menu = Path(os.environ["ProgramData"]) / "Microsoft/Windows/Start Menu/Programs"
    
    try:
        import win32com.client
        create_shortcut(str(install_dir / exe_name), str(desktop / f"{app_name}.lnk"), app_name)
        create_shortcut(str(install_dir / exe_name), str(start_menu / f"{app_name}.lnk"), app_name)
        print("Shortcuts created.")
    except Exception as e:
        print(f"Could not create shortcuts: {e}")

    # 4. Registry for Uninstaller
    uninst_key = fr"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{app_name}"
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, uninst_key) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, app_name)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Syntax Sphere")
        # For simplicity, the 'uninstaller' just runs a command to remove the folder
        # In a real app, you'd bundle a separate uninstall.exe
        uninst_cmd = f'cmd.exe /c "taskkill /F /IM {exe_name} /T & subst T: /D & rd /s /q \\"{install_dir}\\""'
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninst_cmd)

    print("\nSUCCESS! T-Drive has been installed.")
    print("Default Sync Folder: C:/Program Files/T-Drive/Cloud")
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    install()
