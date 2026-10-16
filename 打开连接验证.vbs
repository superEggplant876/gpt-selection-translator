Option Explicit
Dim shell, files, folder, pythonExe, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
pythonExe = folder & "\runtime\pythonw.exe"
If Not files.FileExists(pythonExe) Then pythonExe = folder & "\.venv\Scripts\pythonw.exe"
If Not files.FileExists(pythonExe) Then
  MsgBox "Python runtime unavailable. Please open README.md.", 16, "GPT Selection Translator"
  WScript.Quit 1
End If
command = Chr(34) & pythonExe & Chr(34) & " " & Chr(34) & folder & "\verify_connection.py" & Chr(34)
shell.Run command, 0, False
