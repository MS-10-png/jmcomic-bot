Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
exe = root & "\JMComicBotManager.exe"
shell.Run Chr(34) & exe & Chr(34), 1, False
