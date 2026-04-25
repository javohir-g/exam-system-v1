EXAM SYSTEM FINAL BUILD
======================

Folder Structure:

1. Agent/
   - seb_ghost_v10.exe: The Windows stealth agent. Run this on student PCs.
   - seb_stealth.cpp: Source code for the agent.

2. Server/
   - cloud_bridge.py: The Flask server. Run with 'python cloud_bridge.py'.
   - .env: Contains your OPENAI_API_KEY and SECRET_KEY.
   - templates/: HTML files for the dashboard and user history.
   - database.json: Persistent storage for all history and logs.

3. ESP32/
   - esp32_vibro.ino: Final firmware for XIAO ESP32C3. Upload via Arduino IDE.

Usage:
1. Start the server in the 'Server' folder.
2. Ensure ESP32 is flashed and connected to Wi-Fi.
3. Run the Agent on the PC and use Ctrl+Shift+A..O to trigger captures.
4. Monitor everything at http://127.0.0.1:5000/dashboard
