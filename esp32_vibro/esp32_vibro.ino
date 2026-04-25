#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// --- CONFIGURATION ---
const char* ssid = "HomeWifi";
const char* password = "11223344";

// Use the IP address of your computer running the server
const char* serverUrl = "http://192.168.0.121:5000/poll";
const char* secretKey = "super-secret-key";

// Change this ID for each device (1-15)
const int USER_ID = 1; 

// Pin for XIAO ESP32C3
const int MOTOR_PIN = D6; 

// --- STATE ---
long lastCommandId = 0; // Tracks the ID of the last processed command

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN, OUTPUT);
  digitalWrite(MOTOR_PIN, LOW);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
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

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    String url = String(serverUrl) + "?user_id=" + String(USER_ID);
    http.begin(url);
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

        // Only vibrate if count > 0 AND this is a NEW command ID
        if (count > 0 && cmdId != lastCommandId) {
          Serial.print("New Command Received! ID: ");
          Serial.print(cmdId);
          Serial.print(", Pulses: ");
          Serial.println(count);
          
          lastCommandId = cmdId; // Update last processed ID
          vibrate(count);
          
          Serial.println("Waiting 5s before next poll to ensure stability...");
          delay(5000); // Extra safety delay after vibration
        } else if (count > 0 && cmdId == lastCommandId) {
          Serial.println("Command already processed. Skipping.");
        }
      } else {
        Serial.print("JSON Parse Error: ");
        Serial.println(error.c_str());
      }
    } else {
      Serial.print("HTTP Error: ");
      Serial.println(httpCode);
    }
    http.end();
  } else {
    Serial.println("WiFi Disconnected. Reconnecting...");
    WiFi.begin(ssid, password);
  }
  
  delay(3000); // Regular poll delay
}
