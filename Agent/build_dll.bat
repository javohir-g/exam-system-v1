@echo off
call "D:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if %errorlevel% neq 0 (
    echo [!] Failed to load vcvars64.bat
    exit /b 1
)

echo [*] Compiling DLL...
cl.exe /LD /EHsc /O2 /W3 wda_unblocker.cpp User32.lib /link /OUT:wda_unblocker.dll

if %errorlevel% neq 0 (
    echo [!] DLL Build FAILED.
    exit /b 1
)

echo [*] Converting to header...
python bin2h.py

if exist wda_bytes.h (
    echo [+] Successfully created wda_bytes.h
) else (
    echo [!] Missing wda_bytes.h
    exit /b 1
)
