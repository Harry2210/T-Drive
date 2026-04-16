import tempfile, os, subprocess
vbs = '''Set oWS = WScript.CreateObject("WScript.Shell")
Set oLink = oWS.CreateShortcut("C:\\Users\\hario\\Desktop\\T-drive\\test.jpg.lnk")
oLink.TargetPath = "C:\\Windows\\System32\\cmd.exe"
oLink.Arguments = "/c echo Hello"
oLink.IconLocation = "shell32.dll, 13"
oLink.Save
'''
fd, path = tempfile.mkstemp(suffix='.vbs')
os.write(fd, vbs.encode('utf-8'))
os.close(fd)
subprocess.run(['cscript.exe', '//Nologo', path])
os.unlink(path)
