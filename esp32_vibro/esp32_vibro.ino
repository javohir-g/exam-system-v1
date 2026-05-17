#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WiFiClientSecure.h>
#include <WiFiMulti.h>

// --- CONFIGURATION ---
// --- WIFI NETWORKS ---
WiFiMulti wifiMulti;
// Add as many networks as you want here
void setupWiFi() {
  wifiMulti.addAP("HomeWifi", "11223344");
  wifiMulti.addAP("Android",   "11223344");
  wifiMulti.addAP("#Turin.uz",  "Turin_2024@!");
}

// Use the Render Cloud URL
const char* pollUrl   = "https://exam-system-v1.onrender.com/poll";
const char* reportUrl = "https://exam-system-v1.onrender.com/esp_report";
const char* secretKey = "super-secret-key";

// Change this ID for each device (1-15)
const int USER_ID = 6; 

// Pin for XIAO ESP32C3
const int MOTOR_PIN = D6; 

// --- STATE ---
long lastCommandId = 0; // Tracks the ID of the last processed command

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);

  WiFi.mode(WIFI_STA);
  setupWiFi();

  Serial.print("Connecting to WiFi");
  while (wifiMulti.run() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
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

void sendDebugReport(int count, long cmdId, String action) {
  if (wifiMulti.run() == WL_CONNECTED) {
    WiFiClientSecure *client = new WiFiClientSecure;
    if(client) {
      client->setInsecure();
      HTTPClient http;
      http.begin(*client, reportUrl);
      http.addHeader("Content-Type", "json");
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
  if (wifiMulti.run() == WL_CONNECTED) {
    WiFiClientSecure *client = new WiFiClientSecure;
    if(client) {
      client->setInsecure(); // Skip SSL certificate verification
      HTTPClient http;
      String url = String(pollUrl) + "?user_id=" + String(USER_ID);
      http.begin(*client, url);
      http.addHeader("X-Secret", secretKey);
      http.setTimeout(5000); // 5 sec timeout

      int httpCode = http.GET();
      if (httpCode == 200) {
        String payload = http.getString();
        StaticJsonDocument<200> doc;
        DeserializationError error = deserializeJson(doc, payload);

        if (!error) {
          int count = doc["count"];
          long cmdId = doc["cmd_id"];

          if (count > 0 && cmdId != lastCommandId) {
            lastCommandId = cmdId;
            sendDebugReport(count, cmdId, "vibrating");
            vibrate(count);
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
  } else {
    Serial.println("WiFi Disconnected. Waiting for reconnection...");
  }
  
  delay(3000); // Regular poll delay
}
