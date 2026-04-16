import tempfile, os, subprocess
from pathlib import Path
stub_dest = Path('C:\\TelegramDrive\\test_jpg_icon.url')
jpg_path = 'C:\\TelegramDrive\\test.jpg'

with open(jpg_path, 'wb') as f:
    f.write(b'\x89PNG\r\n\x1a\n') # dummy

vbs = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut("{stub_dest}")
oLink.TargetPath = "C:\\main.py"
oLink.IconLocation = "{jpg_path}, 0"
oLink.Save
'''
fd, path = tempfile.mkstemp(suffix='.vbs')
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    f.write(vbs)
subprocess.run(['cscript.exe', '//Nologo', path])
