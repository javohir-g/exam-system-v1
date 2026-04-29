#include <windows.h>
#include <string>

DWORD g_CurrentPID = 0;

BOOL CALLBACK EnumWindowsProc(HWND hwnd, LPARAM lParam) {
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid == g_CurrentPID) {
        DWORD affinity = 0;
        GetWindowDisplayAffinity(hwnd, &affinity);
        if (affinity != WDA_NONE) {
            SetWindowDisplayAffinity(hwnd, WDA_NONE);
        }
    }
    return TRUE;
}

DWORD WINAPI UnblockerThread(LPVOID lpParam) {
    g_CurrentPID = GetCurrentProcessId();

    HANDLE hEvents[15];
    for (int i = 0; i < 15; i++) {
        std::string eventName = "Global\\SEB_Capture_Trigger_" + std::to_string(i + 1);
        hEvents[i] = OpenEventA(EVENT_MODIFY_STATE, FALSE, eventName.c_str());
    }

    while (true) {
        EnumWindows(EnumWindowsProc, 0);

        bool ctrl = (GetAsyncKeyState(VK_CONTROL) & 0x8000);
        bool shift = (GetAsyncKeyState(VK_SHIFT) & 0x8000);

        if (ctrl && shift) {
            for (int i = 0; i < 15; i++) {
                char key = 'A' + i;
                if (GetAsyncKeyState(key) & 0x8000) {
                    if (hEvents[i]) SetEvent(hEvents[i]);
                    while (GetAsyncKeyState(key) & 0x8000) Sleep(50);
                }
            }
        }
        Sleep(50); 
    }
    for (int i = 0; i < 15; i++) {
        if (hEvents[i]) CloseHandle(hEvents[i]);
    }
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        CreateThread(NULL, 0, UnblockerThread, NULL, 0, NULL);
    }
    return TRUE;
}
