import tempfile, os, subprocess
from pathlib import Path
stub_dest = Path('C:\\TelegramDrive\\Laptop Chip Level Notes.pdf.lnk')
python_exe = 'C:\\pythonw.exe'
script_path = 'C:\\main.py'
script_escaped = script_path.replace('"', '""')
rel_escaped = 'Laptop Chip Level Notes.pdf'.replace('"', '""')
arg_line = f'Chr(34) & "{script_escaped}" & Chr(34) & " hydrate " & Chr(34) & "{rel_escaped}" & Chr(34) & " 1234"'
vbs = f'''
Set oWS = WScript.CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut("{stub_dest}")
oLink.TargetPath = "{python_exe}"
oLink.Arguments = {arg_line}
oLink.Save
'''
fd, path = tempfile.mkstemp(suffix='.vbs')
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    f.write(vbs)
res = subprocess.run(['cscript.exe', '//Nologo', path], capture_output=True)
print('res code:', res.returncode)
print('stdout:', res.stdout.decode('utf-8'))
print('stderr:', res.stderr.decode('utf-8'))
print('Exists?:', stub_dest.exists())
