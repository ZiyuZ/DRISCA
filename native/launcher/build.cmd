@echo off
setlocal
set "ROOT=%~dp0..\.."
set "TMPDIR=%ROOT%\.cache\launcher-exe"
if not exist "%TMPDIR%" mkdir "%TMPDIR%"

rc.exe /nologo /fo "%TMPDIR%\drisca.res" "%~dp0drisca.rc" || exit /b 1
cl.exe /nologo /utf-8 /O2 /W4 /MT ^
  /Fo"%TMPDIR%\main.obj" ^
  /Fe"%ROOT%\DRISCA.exe" ^
  "%~dp0main.c" "%TMPDIR%\drisca.res" ^
  user32.lib /link /SUBSYSTEM:WINDOWS || exit /b 1
echo Built %ROOT%\DRISCA.exe
