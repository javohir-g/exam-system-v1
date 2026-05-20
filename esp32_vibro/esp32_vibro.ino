#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WiFiClientSecure.h>
#include <WiFi.h>

// --- KNOWN NETWORKS ---
struct KnownAP {
  const char* ssid;
  const char* password;
};

KnownAP knownNetworks[] = {
  { "HomeWifi",   "11223344" },
  { "Android",    "11223344" },
  { "#Turin.uz",  "Turin_2024@!" },
};
const int NETWORK_COUNT = sizeof(knownNetworks) / sizeof(knownNetworks[0]);

// Use the Render Cloud URL
const char* pollUrl   = "https://exam-system-v1.onrender.com/poll";
const char* reportUrl = "https://exam-system-v1.onrender.com/esp_report";
const char* secretKey = "super-secret-key";

// Change this ID for each device (1-15)
const int USER_ID = 5;

// Pin for XIAO ESP32C3
const int MOTOR_PIN = D6;

// --- STATE ---
long lastCommandId = 0;

// Scan and connect to the known network with the best RSSI
void connectToBestNetwork() {
  Serial.println("\n[WiFi] Scanning networks...");
  int found = WiFi.scanNetworks();

  int bestIdx = -1;       // index in knownNetworks[]
  int bestRSSI = -999;

  for (int i = 0; i < found; i++) {
    String scannedSSID = WiFi.SSID(i);
    int scannedRSSI    = WiFi.RSSI(i);
    Serial.printf("  Found: %-25s RSSI: %d\n", scannedSSID.c_str(), scannedRSSI);

    for (int k = 0; k < NETWORK_COUNT; k++) {
      if (scannedSSID == knownNetworks[k].ssid && scannedRSSI > bestRSSI) {
        bestRSSI = scannedRSSI;
        bestIdx  = k;
      }
    }
  }

  WiFi.scanDelete();

  if (bestIdx == -1) {
    Serial.println("[WiFi] No known networks found. Retrying in 5s...");
    delay(5000);
    connectToBestNetwork();
    return;
  }

  Serial.printf("[WiFi] Best network: %s (%d dBm). Connecting...\n",
                knownNetworks[bestIdx].ssid, bestRSSI);

  WiFi.begin(knownNetworks[bestIdx].ssid, knownNetworks[bestIdx].password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WiFi] Failed. Rescanning...");
    connectToBestNetwork();
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);

  WiFi.mode(WIFI_STA);
  connectToBestNetwork();
}

void vibrate(int times) {
  Serial.println("--- VIBRATION START ---");
  for (int i = 0; i < times; i++) {
    Serial.print("Pulse ");
    Serial.println(i + 1);
    digitalWrite(MOTOR_PIN, HIGH);
    delay(1000); // 1.0 second vibration
    digitalWrite(MOTOR_PIN, LOW);
    delay(500);  // 0.5 second pause
  }
  Serial.println("--- VIBRATION DONE ---");
}

void vibrateZero() {
  Serial.println("--- ZERO VIBRATION (LONG) ---");
  digitalWrite(MOTOR_PIN, HIGH);
  delay(1500); // 1.5 seconds for a zero
  digitalWrite(MOTOR_PIN, LOW);
  delay(500);
  Serial.println("--- ZERO DONE ---");
}

void vibrateDrag(int from, int to) {
  Serial.println("--- DRAG VIBRATION START ---");
  Serial.print("FROM: "); Serial.println(from);
  vibrate(from);
  delay(2000); // 2 second pause between FROM and TO
  Serial.print("TO: "); Serial.println(to);
  vibrate(to);
  Serial.println("--- DRAG VIBRATION DONE ---");
}

void sendDebugReport(int count, long cmdId, String action) {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClientSecure *client = new WiFiClientSecure;
    if(client) {
      client->setInsecure();
      HTTPClient http;
      http.begin(*client, reportUrl);
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Secret", secretKey);

      StaticJsonDocument<200> doc;
      doc["user_id"] = USER_ID;
      doc["rssi"] = WiFi.RSSI();
      doc["free_heap"] = ESP.getFreeHeap();
      doc["count"] = count;
      doc["cmd_id"] = cmdId;
      doc["action"] = action;
      doc["motor_pin"] = MOTOR_PIN;

      String requestBody;
      serializeJson(doc, requestBody);
      int httpCode = http.POST(requestBody);
      http.end();
      delete client;
    }
  }
}

void loop() {
  // Auto-reconnect if WiFi dropped
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Disconnected. Reconnecting...");
    WiFi.disconnect();
    connectToBestNetwork();
  }

  WiFiClientSecure *client = new WiFiClientSecure;
  if(client) {
    client->setInsecure();
    HTTPClient http;
    String ssid = WiFi.SSID();
    ssid.replace(" ", "%20"); // URL-encode spaces
    String url = String(pollUrl) + "?user_id=" + String(USER_ID)
               + "&rssi=" + String(WiFi.RSSI())
               + "&ssid=" + ssid;
    http.begin(*client, url);
    http.addHeader("X-Secret", secretKey);
    http.setTimeout(5000);

    int httpCode = http.GET();
    if (httpCode == 200) {
      String payload = http.getString();
      StaticJsonDocument<256> doc;
      DeserializationError error = deserializeJson(doc, payload);

      if (!error) {
        // Check for reconnect command
        if (doc["reconnect"] == true) {
          Serial.println("[CMD] Reconnect command received. Scanning best network...");
          http.end();
          delete client;
          WiFi.disconnect();
          delay(500);
          connectToBestNetwork();
          return;
        }

        int count = doc["count"];
        int count2 = doc["count2"] | 0;
        bool isNum = doc["is_num"] | false;
        long cmdId = doc["cmd_id"];

        if ((count > 0 || isNum) && cmdId != lastCommandId) {
          lastCommandId = cmdId;
          sendDebugReport(count, cmdId, "vibrating");
          
          if (isNum) {
            String s = String(count);
            for(int i = 0; i < s.length(); i++) {
              int d = s.charAt(i) - '0';
              if (d == 0) vibrateZero();
              else vibrate(d);
              if (i < s.length() - 1) delay(2000); // 2 sec pause between digits
            }
          } else if (count2 > 0) {
            vibrateDrag(count, count2);
          } else {
            vibrate(count);
          }
          sendDebugReport(0, cmdId, "idle");
          delay(5000);
        } else {
          sendDebugReport(0, lastCommandId, "idle");
        }
      }
    }
    http.end();
    delete client;
  }
  
  delay(3000);
}

