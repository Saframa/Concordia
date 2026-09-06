Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = currentDir
If Not fso.FileExists(currentDir & "\bin\ffmpeg.exe") Or Not fso.FileExists(currentDir & "\bin\mpv.exe") Then
    WshShell.Run chr(34) & "instalar_y_jugar.bat" & Chr(34), 1
Else
    WshShell.Run chr(34) & "instalar_y_jugar.bat" & Chr(34), 0
End If
Set WshShell = Nothing
