#include <Arduino.h>
#include <DNSServer.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <mbedtls/base64.h>

struct AppConfig {
  String wifiSsid;
  String wifiPassword;
  String mqttHost;
  uint16_t mqttPort = 1883;
  String mqttUser;
  String mqttPassword;
  String printerName = "stikka-esp32";
  String printerType = "zpl";
  String zplTargetHost;
  uint16_t zplTargetPort = 9100;
  int dpi = 203;
  int labelWidth = 55;
  int labelLength = 55;
};

Preferences prefs;
WebServer web(80);
DNSServer dnsServer;
WiFiClient mqttNet;
PubSubClient mqtt(mqttNet);

AppConfig cfg;
unsigned long lastWifiAttemptMs = 0;
unsigned long lastMqttAttemptMs = 0;
unsigned long lastStatusMs = 0;
unsigned long wifiDisconnectedSinceMs = 0;
bool apModeActive = false;
bool dnsServerActive = false;

static const unsigned long WIFI_RETRY_EVERY_MS = 5000;
static const unsigned long WIFI_FALLBACK_AP_AFTER_MS = 20000;
static const char* AP_PASSWORD = "stikkaesp32";
static const uint16_t DNS_PORT = 53;

String fallbackApSsid() {
  uint32_t mac = (uint32_t)ESP.getEfuseMac();
  String suffix = String(mac, HEX);
  suffix.toUpperCase();
  return String("Stikka-") + suffix;
}

void ensureFallbackAp() {
  if (apModeActive) return;
  const String ssid = fallbackApSsid();
  if (WiFi.softAP(ssid.c_str(), AP_PASSWORD)) {
    apModeActive = true;
    dnsServer.start(DNS_PORT, "*", WiFi.softAPIP());
    dnsServerActive = true;
  }
}

void disableFallbackAp() {
  if (!apModeActive) return;
  if (dnsServerActive) {
    dnsServer.stop();
    dnsServerActive = false;
  }
  WiFi.softAPdisconnect(true);
  apModeActive = false;
}

String commandTopic() {
  return String("/command/") + cfg.printerName;
}

String statusTopic() {
  return String("/status/") + cfg.printerName;
}

String htmlEscape(const String& in) {
  String out;
  out.reserve(in.length() + 16);
  for (size_t i = 0; i < in.length(); i++) {
    const char c = in[i];
    if (c == '&') out += "&amp;";
    else if (c == '<') out += "&lt;";
    else if (c == '>') out += "&gt;";
    else if (c == '"') out += "&quot;";
    else out += c;
  }
  return out;
}

void loadConfig() {
  if (!prefs.begin("stikka", true)) {
    if (prefs.begin("stikka", false)) {
      prefs.end();
    }
    return;
  }
  cfg.wifiSsid = prefs.getString("wifiSsid", "");
  cfg.wifiPassword = prefs.getString("wifiPwd", "");
  cfg.mqttHost = prefs.getString("mqttHost", "");
  cfg.mqttPort = prefs.getUShort("mqttPort", 1883);
  cfg.mqttUser = prefs.getString("mqttUser", "");
  cfg.mqttPassword = prefs.getString("mqttPwd", "");
  cfg.printerName = prefs.getString("printer", "stikka-esp32");
  cfg.printerType = prefs.getString("ptype", "zpl");
  cfg.zplTargetHost = prefs.getString("zplHost", "");
  cfg.zplTargetPort = prefs.getUShort("zplPort", 9100);
  cfg.dpi = prefs.getInt("dpi", 203);
  cfg.labelWidth = prefs.getInt("labelW", 55);
  cfg.labelLength = prefs.getInt("labelL", 55);
  prefs.end();
}

void saveConfig() {
  prefs.begin("stikka", false);
  prefs.putString("wifiSsid", cfg.wifiSsid);
  prefs.putString("wifiPwd", cfg.wifiPassword);
  prefs.putString("mqttHost", cfg.mqttHost);
  prefs.putUShort("mqttPort", cfg.mqttPort);
  prefs.putString("mqttUser", cfg.mqttUser);
  prefs.putString("mqttPwd", cfg.mqttPassword);
  prefs.putString("printer", cfg.printerName);
  prefs.putString("ptype", cfg.printerType);
  prefs.putString("zplHost", cfg.zplTargetHost);
  prefs.putUShort("zplPort", cfg.zplTargetPort);
  prefs.putInt("dpi", cfg.dpi);
  prefs.putInt("labelW", cfg.labelWidth);
  prefs.putInt("labelL", cfg.labelLength);
  prefs.end();
}

String buildStatusJson(const char* phase, const char* lastError) {
  JsonDocument doc;
  doc["printer_name"] = cfg.printerName;
  doc["name"] = cfg.printerName;
  doc["online"] = true;
  doc["busy"] = String(phase) == "printing";
  doc["phase"] = phase;
  doc["type"] = cfg.printerType;
  doc["serial"] = String((uint32_t)ESP.getEfuseMac(), HEX);
  doc["dpi"] = cfg.dpi;
  doc["last_error"] = lastError;

  JsonObject label = doc["label"].to<JsonObject>();
  label["width"] = cfg.labelWidth;
  label["length"] = cfg.labelLength;
  label["isRound"] = false;
  label["verticalOffset"] = 0;
  label["cut"] = false;

  JsonObject capabilities = doc["capabilities"].to<JsonObject>();
  capabilities["type"] = cfg.printerType;
  capabilities["dpi"] = cfg.dpi;
  JsonObject capLabel = capabilities["label"].to<JsonObject>();
  capLabel["width"] = cfg.labelWidth;
  capLabel["length"] = cfg.labelLength;
  capLabel["isRound"] = false;
  capLabel["verticalOffset"] = 0;
  capLabel["cut"] = false;

  String out;
  serializeJson(doc, out);
  return out;
}

void publishStatus(const char* phase = "ready", const char* lastError = "") {
  if (!mqtt.connected()) return;
  const String payload = buildStatusJson(phase, lastError);
  mqtt.publish(statusTopic().c_str(), payload.c_str(), true);
}

bool sendZPLToTarget(const String& zpl, String& err) {
  if (cfg.zplTargetHost.isEmpty()) {
    err = "zplTargetHost is empty";
    return false;
  }

  WiFiClient printerClient;
  if (!printerClient.connect(cfg.zplTargetHost.c_str(), cfg.zplTargetPort)) {
    err = "cannot connect to target printer";
    return false;
  }

  size_t sent = printerClient.print(zpl);
  printerClient.stop();
  if (sent == 0) {
    err = "zero bytes sent";
    return false;
  }
  return true;
}

bool sendBytesToTarget(const uint8_t* data, size_t len, String& err) {
  if (cfg.zplTargetHost.isEmpty()) {
    err = "zplTargetHost is empty";
    return false;
  }

  WiFiClient printerClient;
  if (!printerClient.connect(cfg.zplTargetHost.c_str(), cfg.zplTargetPort)) {
    err = "cannot connect to target printer";
    return false;
  }

  size_t sent = printerClient.write(data, len);
  printerClient.stop();
  if (sent != len) {
    err = "could not send complete payload";
    return false;
  }
  return true;
}

bool decodeBase64Payload(const String& in, std::unique_ptr<uint8_t[]>& out, size_t& outLen, String& err) {
  size_t needed = 0;
  int rc = mbedtls_base64_decode(nullptr, 0, &needed,
                                 reinterpret_cast<const unsigned char*>(in.c_str()),
                                 in.length());
  if (rc != MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL && rc != 0) {
    err = "invalid base64 payload";
    return false;
  }

  out.reset(new uint8_t[needed]);
  rc = mbedtls_base64_decode(out.get(), needed, &outLen,
                             reinterpret_cast<const unsigned char*>(in.c_str()),
                             in.length());
  if (rc != 0) {
    err = "base64 decode failed";
    return false;
  }

  return true;
}

void publishJobStatus(const char* jobId, const char* status, const char* message) {
  if (!mqtt.connected()) return;

  JsonDocument doc;
  doc["printer_name"] = cfg.printerName;
  doc["job_id"] = jobId;
  doc["status"] = status;
  doc["message"] = message;

  String payload;
  serializeJson(doc, payload);
  mqtt.publish(statusTopic().c_str(), payload.c_str(), false);
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String incomingTopic(topic);
  if (incomingTopic != commandTopic()) return;

  String msg;
  msg.reserve(length + 1);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  JsonDocument doc;
  const auto err = deserializeJson(doc, msg);
  if (err) {
    publishJobStatus("", "failed", "invalid JSON payload");
    return;
  }

  const char* jobId = doc["job_id"] | "";
  const char* payloadType = doc["payload_type"] | "";
  const char* payloadEncoding = doc["payload_encoding"] | "";
  const char* body = doc["payload"] | "";

  publishStatus("printing", "");
  publishJobStatus(jobId, "accepted", "job accepted");

  if (String(payloadType) == "zpl") {
    if (String(payloadEncoding) != "utf8") {
      publishJobStatus(jobId, "failed", "payload_encoding must be utf8 for zpl");
      publishStatus("error", "payload_encoding must be utf8 for zpl");
      return;
    }

    String sendErr;
    const bool ok = sendZPLToTarget(String(body), sendErr);
    if (!ok) {
      publishJobStatus(jobId, "failed", sendErr.c_str());
      publishStatus("error", sendErr.c_str());
      return;
    }

    publishJobStatus(jobId, "done", "zpl sent");
    publishStatus("ready", "");
    return;
  }

  if (String(payloadType) == "image") {
    String encoded = String(body);
    if (String(payloadEncoding) == "data_url") {
      const int comma = encoded.indexOf(',');
      if (comma < 0) {
        publishJobStatus(jobId, "failed", "invalid data_url payload");
        publishStatus("error", "invalid data_url payload");
        return;
      }
      encoded = encoded.substring(comma + 1);
    } else if (String(payloadEncoding) != "base64_png") {
      publishJobStatus(jobId, "failed", "unsupported image payload_encoding");
      publishStatus("error", "unsupported image payload_encoding");
      return;
    }

    std::unique_ptr<uint8_t[]> bytes;
    size_t decodedLen = 0;
    String decodeErr;
    if (!decodeBase64Payload(encoded, bytes, decodedLen, decodeErr)) {
      publishJobStatus(jobId, "failed", decodeErr.c_str());
      publishStatus("error", decodeErr.c_str());
      return;
    }

    String sendErr;
    if (!sendBytesToTarget(bytes.get(), decodedLen, sendErr)) {
      publishJobStatus(jobId, "failed", sendErr.c_str());
      publishStatus("error", sendErr.c_str());
      return;
    }

    publishJobStatus(jobId, "done", "image bytes sent");
    publishStatus("ready", "");
    return;
  }

  publishJobStatus(jobId, "failed", "unsupported payload_type");
  publishStatus("error", "unsupported payload_type");
}

void connectWifi() {
  const unsigned long now = millis();

  if (cfg.wifiSsid.isEmpty()) {
    ensureFallbackAp();
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiDisconnectedSinceMs = 0;
    disableFallbackAp();
    return;
  }

  if (wifiDisconnectedSinceMs == 0) {
    wifiDisconnectedSinceMs = now;
  }

  if (now - wifiDisconnectedSinceMs >= WIFI_FALLBACK_AP_AFTER_MS) {
    ensureFallbackAp();
  }

  if (now - lastWifiAttemptMs < WIFI_RETRY_EVERY_MS) return;
  lastWifiAttemptMs = now;

  WiFi.begin(cfg.wifiSsid.c_str(), cfg.wifiPassword.c_str());
}

void connectMqtt() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (cfg.mqttHost.isEmpty()) return;
  if (mqtt.connected()) return;

  const unsigned long now = millis();
  if (now - lastMqttAttemptMs < 5000) return;
  lastMqttAttemptMs = now;

  mqtt.setServer(cfg.mqttHost.c_str(), cfg.mqttPort);
  mqtt.setCallback(onMqttMessage);

  const String clientId = cfg.printerName + "-bridge";
  bool connected;
  if (cfg.mqttUser.isEmpty()) {
    connected = mqtt.connect(clientId.c_str());
  } else {
    connected = mqtt.connect(clientId.c_str(), cfg.mqttUser.c_str(), cfg.mqttPassword.c_str());
  }

  if (!connected) return;

  mqtt.subscribe(commandTopic().c_str(), 1);
  publishStatus("ready", "");
}

String renderConfigPage() {
  String html;
  html.reserve(4500);
  html += "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>";
  html += "<title>Stikka ESP32</title><style>";
  html += "body{font-family:Arial,sans-serif;max-width:820px;margin:1rem auto;padding:0 1rem;}";
  html += "h1{margin-bottom:.25rem;} .sub{color:#555;margin-top:0;margin-bottom:1rem;}";
  html += "label{display:block;font-weight:600;margin-top:.75rem;} input{width:100%;padding:.5rem;margin-top:.25rem;}";
  html += "button{margin-top:1rem;padding:.6rem 1rem;} .grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;}";
  html += "@media(max-width:700px){.grid{grid-template-columns:1fr;}} .box{border:1px solid #ddd;border-radius:8px;padding:1rem;}";
  html += "small{color:#666;} code{background:#f3f3f3;padding:.1rem .3rem;border-radius:3px;}";
  html += "</style></head><body>";
  html += "<h1>Stikka ESP32 Bridge</h1>";
  html += "<p class='sub'>Configure Wi-Fi, MQTT and ZPL target for this printer bridge.</p>";

  html += "<div class='box'><strong>Runtime status</strong><br>";
  html += "Wi-Fi: ";
  html += (WiFi.status() == WL_CONNECTED) ? "connected" : "disconnected";
  if (WiFi.status() == WL_CONNECTED) {
    html += " (" + WiFi.localIP().toString() + ")";
  }
  html += "<br>MQTT: ";
  html += mqtt.connected() ? "connected" : "disconnected";
  html += "<br>Fallback AP: ";
  if (apModeActive) {
    html += "active (SSID: <code>" + fallbackApSsid() + "</code>, password: <code>" + String(AP_PASSWORD) + "</code>)";
    html += "<br>AP IP: " + WiFi.softAPIP().toString();
  } else {
    html += "inactive";
  }
  html += "<br>Command topic: <code>" + commandTopic() + "</code>";
  html += "<br>Status topic: <code>" + statusTopic() + "</code>";
  html += "</div>";

  html += "<form method='POST' action='/save'>";
  html += "<div class='grid'>";
  html += "<div class='box'><h3>Wi-Fi</h3>";
  html += "<label>SSID<input name='wifiSsid' value='" + htmlEscape(cfg.wifiSsid) + "'></label>";
  html += "<label>Password<input type='password' name='wifiPassword' value='" + htmlEscape(cfg.wifiPassword) + "'></label>";
  html += "</div>";

  html += "<div class='box'><h3>MQTT</h3>";
  html += "<label>Broker host<input name='mqttHost' value='" + htmlEscape(cfg.mqttHost) + "'></label>";
  html += "<label>Broker port<input name='mqttPort' value='" + String(cfg.mqttPort) + "'></label>";
  html += "<label>User<input name='mqttUser' value='" + htmlEscape(cfg.mqttUser) + "'></label>";
  html += "<label>Password<input type='password' name='mqttPassword' value='" + htmlEscape(cfg.mqttPassword) + "'></label>";
  html += "</div>";

  html += "<div class='box'><h3>Printer identity</h3>";
  html += "<label>Printer name<input name='printerName' value='" + htmlEscape(cfg.printerName) + "'></label>";
  html += "<label>Printer type (zpl / brother_ql)<input name='printerType' value='" + htmlEscape(cfg.printerType) + "'></label>";
  html += "<small>Published status topic: /status/&lt;printername&gt;</small>";
  html += "</div>";

  html += "<div class='box'><h3>ZPL target</h3>";
  html += "<label>Target host<input name='zplTargetHost' value='" + htmlEscape(cfg.zplTargetHost) + "'></label>";
  html += "<label>Target port<input name='zplTargetPort' value='" + String(cfg.zplTargetPort) + "'></label>";
  html += "<label>DPI<input name='dpi' value='" + String(cfg.dpi) + "'></label>";
  html += "<label>Label width mm<input name='labelWidth' value='" + String(cfg.labelWidth) + "'></label>";
  html += "<label>Label length mm<input name='labelLength' value='" + String(cfg.labelLength) + "'></label>";
  html += "</div>";
  html += "</div>";

  html += "<button type='submit'>Save and reconnect</button>";
  html += "</form>";

  html += "<form method='POST' action='/test'><button type='submit'>Send test ZPL</button></form>";
  html += "</body></html>";

  return html;
}

uint16_t parsePort(const String& value, uint16_t fallback) {
  const long p = value.toInt();
  if (p <= 0 || p > 65535) return fallback;
  return (uint16_t)p;
}

void handleRoot() {
  web.send(200, "text/html", renderConfigPage());
}

void handleCaptivePortal() {
  web.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  web.sendHeader("Pragma", "no-cache");
  web.sendHeader("Expires", "-1");
  handleRoot();
}

void handleCaptivePortalRedirect() {
  if (apModeActive) {
    web.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/", true);
    web.send(302, "text/plain", "");
    return;
  }
  web.send(404, "text/plain", "not found");
}

void handleSave() {
  cfg.wifiSsid = web.arg("wifiSsid");
  cfg.wifiPassword = web.arg("wifiPassword");
  cfg.mqttHost = web.arg("mqttHost");
  cfg.mqttPort = parsePort(web.arg("mqttPort"), 1883);
  cfg.mqttUser = web.arg("mqttUser");
  cfg.mqttPassword = web.arg("mqttPassword");
  cfg.printerName = web.arg("printerName");
  cfg.printerType = web.arg("printerType");
  cfg.zplTargetHost = web.arg("zplTargetHost");
  cfg.zplTargetPort = parsePort(web.arg("zplTargetPort"), 9100);
  cfg.dpi = web.arg("dpi").toInt();
  if (cfg.dpi <= 0) cfg.dpi = 203;
  cfg.labelWidth = web.arg("labelWidth").toInt();
  if (cfg.labelWidth <= 0) cfg.labelWidth = 55;
  cfg.labelLength = web.arg("labelLength").toInt();
  if (cfg.labelLength <= 0) cfg.labelLength = 55;

  if (cfg.printerName.isEmpty()) cfg.printerName = "stikka-esp32";
  if (cfg.printerType.isEmpty()) cfg.printerType = "zpl";

  saveConfig();

  WiFi.disconnect(true);
  wifiDisconnectedSinceMs = millis();
  disableFallbackAp();
  mqtt.disconnect();

  web.send(200, "text/plain", "saved; reconnecting wifi and mqtt");
}

void handleTest() {
  String err;
  const String zpl = "^XA^CF0,30^FO40,40^FDStikka ESP32 test^FS^XZ";
  const bool ok = sendZPLToTarget(zpl, err);
  if (!ok) {
    web.send(500, "text/plain", "test failed: " + err);
    return;
  }
  web.send(200, "text/plain", "test label sent");
}

void setupWeb() {
  web.on("/", HTTP_GET, handleRoot);
  web.on("/generate_204", HTTP_GET, handleCaptivePortalRedirect);
  web.on("/gen_204", HTTP_GET, handleCaptivePortalRedirect);
  web.on("/hotspot-detect.html", HTTP_GET, handleCaptivePortal);
  web.on("/connecttest.txt", HTTP_GET, handleCaptivePortal);
  web.on("/ncsi.txt", HTTP_GET, handleCaptivePortal);
  web.on("/fwlink", HTTP_GET, handleCaptivePortalRedirect);
  web.on("/save", HTTP_POST, handleSave);
  web.on("/test", HTTP_POST, handleTest);
  web.onNotFound(handleCaptivePortalRedirect);
  web.begin();
}

void setup() {
  Serial.begin(115200);
  delay(200);

  loadConfig();

  WiFi.mode(WIFI_AP_STA);
  connectWifi();

  setupWeb();
}

void loop() {
  if (dnsServerActive) {
    dnsServer.processNextRequest();
  }
  web.handleClient();
  connectWifi();
  connectMqtt();

  if (mqtt.connected()) {
    mqtt.loop();
    const unsigned long now = millis();
    if (now - lastStatusMs > 30000) {
      publishStatus("ready", "");
      lastStatusMs = now;
    }
  }
}
