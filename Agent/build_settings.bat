@echo off
call "D:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if %errorlevel% neq 0 (
    echo [!] Failed to load vcvars64.bat
    exit /b 1
)
cl.exe /EHsc /O2 /W3 seb_stealth.cpp User32.lib Gdi32.lib Advapi32.lib Wininet.lib /link /OUT:settings.exe
if %errorlevel% equ 0 (
    echo [+] SUCCESS! settings.exe is ready.
) else (
    echo [!] Build FAILED.
    exit /b 1
)
