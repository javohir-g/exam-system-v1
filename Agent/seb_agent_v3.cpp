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

#pragma comment(lib, "User32.lib")
#pragma comment(lib, "Gdi32.lib")
#pragma comment(lib, "Advapi32.lib")
#pragma comment(lib, "Wininet.lib")

// --- CONFIG ---
const char* HOST = "exam-system-v1.onrender.com";
const int   PORT = INTERNET_DEFAULT_HTTPS_PORT;
const char* SECRET_KEY = "super-secret-key"; 

// --- GLOBALS ---
char            g_activeDeskName[256] = "";
volatile int    g_currentUser = 1;
std::string     g_answerText = "";

enum DotState { DOT_RED, DOT_YELLOW, DOT_GREEN };
volatile DotState g_dotState = DOT_RED;
volatile bool g_agentEnabled = false;

void Log(const char* format, ...) {
    SYSTEMTIME st;
    GetLocalTime(&st);
    printf("[%02d:%02d:%02d.%03d] ", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
    
    va_list args;
    va_start(args, format);
    vprintf(format, args);
    va_end(args);
    printf("\n");
}

// -------------------------------------------------------------
// HTTP Utilities
// -------------------------------------------------------------
std::string HttpGetPoll(int user_id) {
    HINTERNET hSession = InternetOpenA("SEB-Agent", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) {
        Log("HttpGetPoll: InternetOpenA failed. Error: %lu", GetLastError());
        return "";
    }
    
    // Set timeouts to prevent hanging (in milliseconds)
    DWORD timeout = 8000;
    InternetSetOptionA(hSession, INTERNET_OPTION_CONNECT_TIMEOUT, &timeout, sizeof(timeout));
    InternetSetOptionA(hSession, INTERNET_OPTION_RECEIVE_TIMEOUT, &timeout, sizeof(timeout));
    InternetSetOptionA(hSession, INTERNET_OPTION_SEND_TIMEOUT,    &timeout, sizeof(timeout));
    
    HINTERNET hConnect = InternetConnectA(hSession, HOST, PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) {
        Log("HttpGetPoll: InternetConnectA failed. Error: %lu", GetLastError());
        InternetCloseHandle(hSession);
        return "";
    }
    
    char path[256];
    sprintf(path, "/agent_poll?user_id=%d&secret=%s", user_id, SECRET_KEY);
    Log("HttpGetPoll: Sending GET %s", path);
    
    HINTERNET hRequest = HttpOpenRequestA(hConnect, "GET", path, NULL, NULL, NULL, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (!hRequest) {
        Log("HttpGetPoll: HttpOpenRequestA failed. Error: %lu", GetLastError());
        InternetCloseHandle(hConnect);
        InternetCloseHandle(hSession);
        return "";
    }
    
    // Ignore SSL certificate errors (common issue with Let's Encrypt / modern certs on old WinINet)
    DWORD dwFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA |
                    SECURITY_FLAG_IGNORE_WRONG_USAGE |
                    SECURITY_FLAG_IGNORE_CERT_CN_INVALID |
                    SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &dwFlags, sizeof(dwFlags));
    
    std::string response = "";
    if (HttpSendRequestA(hRequest, NULL, 0, NULL, 0)) {
        char buf[1024];
        DWORD bytesRead = 0;
        while (InternetReadFile(hRequest, buf, sizeof(buf) - 1, &bytesRead) && bytesRead > 0) {
            buf[bytesRead] = '\0';
            response += buf;
        }
    } else {
        Log("HttpGetPoll: HttpSendRequestA failed. Error: %lu", GetLastError());
    }
    
    InternetCloseHandle(hRequest);
    InternetCloseHandle(hConnect);
    InternetCloseHandle(hSession);
    return response;
}

void UploadToCloud(const std::vector<uint8_t>& jpegData, int user_id) {
    HINTERNET hSession = InternetOpenA("SEB-Agent", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (!hSession) return;
    HINTERNET hConnect = InternetConnectA(hSession, HOST, PORT, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 0);
    if (!hConnect) { InternetCloseHandle(hSession); return; }
    HINTERNET hRequest = HttpOpenRequestA(hConnect, "POST", "/upload", NULL, NULL, NULL, INTERNET_FLAG_RELOAD | INTERNET_FLAG_SECURE, 0);
    if (!hRequest) { InternetCloseHandle(hConnect); InternetCloseHandle(hSession); return; }
    
    // Ignore SSL certificate errors
    DWORD dwFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA |
                    SECURITY_FLAG_IGNORE_WRONG_USAGE |
                    SECURITY_FLAG_IGNORE_CERT_CN_INVALID |
                    SECURITY_FLAG_IGNORE_CERT_DATE_INVALID;
    InternetSetOptionA(hRequest, INTERNET_OPTION_SECURITY_FLAGS, &dwFlags, sizeof(dwFlags));
    
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
        Log("UploadToCloud: Successfully uploaded screenshot for user %d (Size: %zu bytes)", user_id, jpegData.size());
        Beep(1000, 100); 
    } else {
        Log("UploadToCloud: Failed to upload screenshot. Error: %lu", GetLastError());
        Beep(200, 500); 
    }
    InternetCloseHandle(hRequest); InternetCloseHandle(hConnect); InternetCloseHandle(hSession);
}

// -------------------------------------------------------------
// Polling Thread
// -------------------------------------------------------------
void PollingThreadFunc() {
    bool wasEnabled = false;
    Log("PollingThread: Started.");
    while (true) {
        std::string res = HttpGetPoll(g_currentUser);
        if (res.empty()) {
            Log("PollingThread: Empty response (network error or timeout).");
        } else {
            Log("PollingThread: Response: %s", res.c_str());
        }
        if (!res.empty()) {
            if (res.find("\"status\":\"disabled\"") != std::string::npos ||
                res.find("\"status\": \"disabled\"") != std::string::npos) {
                if (g_agentEnabled || !wasEnabled) Log("Server state: GLOBAL_AGENT_ENABLED is OFF. Agent sleeps.");
                g_agentEnabled = false;
                wasEnabled = true;
            } else if (res.find("\"status\":\"pending\"") != std::string::npos ||
                       res.find("\"status\": \"pending\"") != std::string::npos) {
                if (!g_agentEnabled) Log("Server state: GLOBAL_AGENT_ENABLED is ON. Agent active.");
                g_agentEnabled = true;
                wasEnabled = true;
            } else if (res.find("\"status\":\"ready\"") != std::string::npos ||
                       res.find("\"status\": \"ready\"") != std::string::npos) {
                g_agentEnabled = true;
                wasEnabled = true;
                size_t textPos = res.find("\"text\"");
                if (textPos != std::string::npos) {
                    size_t startQuote = res.find("\"", textPos + 6);
                    if (startQuote != std::string::npos) {
                        size_t endQuote = res.find("\"", startQuote + 1);
                        if (endQuote != std::string::npos) {
                            std::string ans = res.substr(startQuote + 1, endQuote - startQuote - 1);
                            if (!ans.empty()) {
                                Log("PollingThread: Received answer for user %d: '%s'", g_currentUser, ans.c_str());
                                g_answerText = ans;
                                g_dotState = DOT_GREEN;
                                Beep(1500, 100);
                                Beep(2000, 100);
                            }
                        }
                    }
                }
            }
        }
        Sleep(1000);
    }
}

// -------------------------------------------------------------
// Capture (Screenshot) logic — proven method from seb_stealth.cpp
// Opens the input desktop FIRST, then captures with GetDC(NULL)
// -------------------------------------------------------------
void TakeScreenshotAndUpload(int user_id) {
    // 1. Switch this thread to the active (SEB) desktop
    HDESK hInput    = OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED);
    HDESK hOriginal = GetThreadDesktop(GetCurrentThreadId());
    if (hInput) SetThreadDesktop(hInput);

    // 2. Grab virtual screen dimensions
    int x = GetSystemMetrics(SM_XVIRTUALSCREEN);
    int y = GetSystemMetrics(SM_YVIRTUALSCREEN);
    int w = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    int h = GetSystemMetrics(SM_CYVIRTUALSCREEN);

    HDC hdc = GetDC(NULL);
    if (hdc) {
        HDC memdc     = CreateCompatibleDC(hdc);
        HBITMAP hbmp  = CreateCompatibleBitmap(hdc, w, h);
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
                Log("TakeScreenshotAndUpload: Captured %dx%d image, compressing to JPEG...", w, h);
                UploadToCloud(jpegBuffer, user_id);
            } else {
                Log("TakeScreenshotAndUpload: JPEG compression failed.");
            }
        } else {
            Log("TakeScreenshotAndUpload: BitBlt failed! Make sure desktop is accessible.");
        }
        SelectObject(memdc, oldbmp);
        DeleteObject(hbmp);
        DeleteDC(memdc);
        ReleaseDC(NULL, hdc);
    }

    // 3. Restore original desktop
    if (hInput) { SetThreadDesktop(hOriginal); CloseDesktop(hInput); }
}


// -------------------------------------------------------------
// Desktop Interaction Thread (Runs on SEB Desktop)
// -------------------------------------------------------------
struct ThreadParam {
    char desktopName[256];
};

DWORD WINAPI ActiveDesktopThreadProc(LPVOID lpParam) {
    ThreadParam* param = (ThreadParam*)lpParam;
    char targetDesktop[256];
    strcpy(targetDesktop, param->desktopName);
    delete param;

    HDESK hDesk = OpenDesktopA(targetDesktop, 0, FALSE, GENERIC_ALL);
    if (!hDesk) {
        Log("Thread: Failed to open desktop '%s'. Error: %lu", targetDesktop, GetLastError());
        return 1;
    }
    if (!SetThreadDesktop(hDesk)) { 
        Log("Thread: Failed to set thread desktop '%s'. Error: %lu", targetDesktop, GetLastError());
        CloseDesktop(hDesk); 
        return 1; 
    }

    Log("Thread: Successfully attached GDI loop to desktop '%s'", targetDesktop);

    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);

    HFONT bigFont = CreateFontA(36, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE, ANSI_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH, "Arial");

    bool wasSpaceHeld = false;
    bool wasShowingText = false;
    int  cleanupFrames = 0;

    while (strcmp(g_activeDeskName, targetDesktop) == 0) {
        if (!g_agentEnabled) {
            Sleep(100);
            continue;
        }

        // 1. Hotkey for Screenshot (Ctrl + Shift + 1..0)
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
            Log("Hotkey pressed! Setting user_id = %d and capturing screen...", pressedNode);
            g_currentUser = pressedNode;
            g_dotState = DOT_YELLOW;
            g_answerText = "";
            std::thread t(TakeScreenshotAndUpload, pressedNode);
            t.detach();
            // Wait until keys are released to prevent multiple triggers
            while ((GetAsyncKeyState(VK_CONTROL) & 0x8000) ||
                   (GetAsyncKeyState(VK_SHIFT)   & 0x8000)) {
                Sleep(16);
            }
        }

        // 2. GDI Drawing Logic
        HDC hdc = GetDC(NULL);
        if (hdc) {
            bool shift2 = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
            bool rmbHeld = (GetAsyncKeyState(VK_RBUTTON) & 0x8000) != 0;
            bool showText = shift2 && rmbHeld && !g_answerText.empty();

            if (showText && !wasShowingText && g_dotState == DOT_GREEN) {
                g_dotState = DOT_RED;
            }

            if (!showText && wasShowingText) {
                cleanupFrames = 30; // Force refresh for 0.5s after release
            }
            wasShowingText = showText;

            if (cleanupFrames > 0 && !showText) {
                InvalidateRect(NULL, NULL, TRUE);
                RedrawWindow(NULL, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW | RDW_ALLCHILDREN);
                cleanupFrames--;
            }

            if (showText) {
                // Draw Text
                SetTextColor(hdc, RGB(232, 232, 232)); // Extremely light, almost blends with #f0f0f0
                SetBkMode(hdc, OPAQUE);
                SetBkColor(hdc, RGB(240, 240, 240)); // #f0f0f0 background
                HGDIOBJ oldFont = SelectObject(hdc, bigFont);

                SIZE sz;
                GetTextExtentPoint32A(hdc, g_answerText.c_str(), g_answerText.length(), &sz);
                int tx = (sw - sz.cx) / 2;
                int ty = sh - sz.cy - 4; // Minimal bottom margin (4px)

                TextOutA(hdc, tx, ty, g_answerText.c_str(), g_answerText.length());
                SelectObject(hdc, oldFont);
            } else {
                COLORREF dotColor;
                switch (g_dotState) {
                    case DOT_RED:    dotColor = RGB(220, 160, 160);  break; // More visible but muted red
                    case DOT_YELLOW: dotColor = RGB(225, 220, 160);  break; // More visible but muted yellow
                    case DOT_GREEN:  dotColor = RGB(160, 220, 160);  break; // More visible but muted green
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
        Sleep(16);
    }

    DeleteObject(bigFont);
    CloseDesktop(hDesk);
    return 0;
}

// -------------------------------------------------------------
// Desktop Switch Detection Thread
// -------------------------------------------------------------
DWORD WINAPI MonitorThreadProc(LPVOID) {
    Log("MonitorDesktops: Thread started. Waiting for desktop switches...");
    while (true) {
        HDESK hDesk = OpenInputDesktop(0, FALSE, MAXIMUM_ALLOWED);
        if (hDesk) {
            char name[256];
            DWORD needed = 0;
            if (GetUserObjectInformationA(hDesk, UOI_NAME, name, sizeof(name), &needed)) {
                if (strcmp(name, g_activeDeskName) != 0) {
                    Log("MonitorDesktops: Desktop switched from '%s' to '%s'", g_activeDeskName, name);
                    strcpy(g_activeDeskName, name);

                    ThreadParam* p = new ThreadParam();
                    strcpy(p->desktopName, name);
                    HANDLE hThread = CreateThread(NULL, 0, ActiveDesktopThreadProc, p, 0, NULL);
                    if (hThread) CloseHandle(hThread);
                }
            }
            CloseDesktop(hDesk);
        }
        Sleep(500);
    }
    return 0;
}

// -------------------------------------------------------------
// Main
// -------------------------------------------------------------
int main() {
    printf("=== SEB Agent v3 (Screenshot + Text Overlay) ===\n");
    printf("1. Run this BEFORE starting SEB.\n");
    printf("2. Inside SEB, wait for the global Agent System to be ENABLED on the dashboard.\n");
    printf("3. Press [Ctrl + Shift + 1..0] to capture and upload.\n");
    printf("4. Wait for the dot to turn from YELLOW to GREEN.\n");
    printf("5. Hold [Shift + Right Mouse Button] to reveal answer text.\n\n");
    
    Log("Main: Agent started.");
    Log("Main: Host: %s:%d", HOST, PORT);

    SetProcessDPIAware();

    // Spawn polling thread
    std::thread poller(PollingThreadFunc);
    poller.detach();

    // Spawn desktop monitor
    HANDLE hMon = CreateThread(NULL, 0, MonitorThreadProc, NULL, 0, NULL);
    if (hMon) CloseHandle(hMon);

    while (true) {
        Sleep(1000);
    }
    return 0;
}
