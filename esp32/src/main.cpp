#include <Arduino.h>
#include <DNSServer.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <mbedtls/base64.h>
#include <Adafruit_NeoPixel.h>
#include <utility>

struct AppConfig {
  String wifiSsid;
  String wifiPassword;
  String mqttHost;
  uint16_t mqttPort = 1883;
  bool mqttUseTls = true;
  bool mqttTlsInsecure = true;
  String mqttCaCert;
  String mqttUser;
  String mqttPassword;
  uint16_t statusIntervalSec = 30;
  String printerName = "stikka-esp32";
  String printerType = "zpl";
  String zplTargetHost;
  uint16_t zplTargetPort = 9100;
  int dpi = 203;
  int labelWidth = 55;
  int labelLength = 55;
  bool debugOutput = true;
  String debugOutputMode = "usb"; // usb | uart
  int debugUartTxPin = 17;
  int debugUartRxPin = 16;
  String ledMode = "none";      // none | neopixel | rgb
  int ledPin = -1;               // neopixel data pin
  int ledPinR = -1;              // discrete RGB R pin
  int ledPinG = -1;              // discrete RGB G pin
  int ledPinB = -1;              // discrete RGB B pin
  String ledOrder = "GRB";      // NeoPixel byte order (RGB, GRB, ...)
  uint16_t ledBlinkMs = 700;     // full blink cycle in ms
};

Preferences prefs;
WebServer web(80);
DNSServer dnsServer;
WiFiClient mqttNet;
WiFiClientSecure mqttNetSecure;
PubSubClient mqtt(mqttNet);
HardwareSerial debugUart(1);

AppConfig cfg;
unsigned long lastWifiAttemptMs = 0;
unsigned long lastMqttAttemptMs = 0;
unsigned long lastStatusMs = 0;
unsigned long wifiDisconnectedSinceMs = 0;
bool apModeActive = false;
bool dnsServerActive = false;
int lastWifiStatus = -1;
bool lastApModeState = false;
bool debugOutputEnabled = true;
bool debugUsbActive = false;
bool debugUartActive = false;
Print* debugOut = nullptr;

Adafruit_NeoPixel* statusPixel = nullptr;
bool ledConfigured = false;
unsigned long ledLastToggleMs = 0;
bool ledBlinkOn = false;
unsigned long ledEventUntilMs = 0;

enum class LedEventType {
  none,
  rx,
  tx,
};

LedEventType ledEventType = LedEventType::none;

String imageChunkJobId;
String imageChunkData;
uint16_t imageChunkExpected = 0;
uint16_t imageChunkReceived = 0;
String zplChunkJobId;
String zplChunkData;
uint16_t zplChunkExpected = 0;
uint16_t zplChunkReceived = 0;

struct RgbColor {
  uint8_t r;
  uint8_t g;
  uint8_t b;
};

static const unsigned long WIFI_RETRY_EVERY_MS = 5000;
static const unsigned long WIFI_FALLBACK_AP_AFTER_MS = 20000;
static const char* AP_PASSWORD = "stikkaesp32";
static const uint16_t DNS_PORT = 53;
// The frontend now caps individual chunks at 8000 bytes specifically so
// this buffer (and everything downstream that copies a message-sized
// String -- onMqttMessage's `msg`, extractJsonStringField's `out`) only
// ever needs to hold a few KB at a time instead of a full multi-KB image.
// Keeping this small also leaves far more free/contiguous heap for those
// copies -- a permanently-reserved 65535-byte buffer was crowding out the
// exact allocations needed to process what it received.
static const uint16_t MQTT_PACKET_BUFFER_SIZE = 16384;

String fallbackApSsid();
String commandTopic();
String statusTopic();
bool sendBytesToTarget(const uint8_t* data, size_t len, String& err);

String normalizeMqttHost(const String& raw) {
  String host = raw;
  host.trim();

  if (host.startsWith("mqtt://")) host = host.substring(7);
  if (host.startsWith("mqtts://")) host = host.substring(8);
  if (host.startsWith("ws://")) host = host.substring(5);
  if (host.startsWith("wss://")) host = host.substring(6);

  const int slash = host.indexOf('/');
  if (slash >= 0) host = host.substring(0, slash);
  return host;
}

String shortenForLog(const String& text, size_t maxLen = 160) {
  if (text.length() <= maxLen) return text;
  return text.substring(0, maxLen) + "...";
}

void resetImageChunkState() {
  imageChunkJobId = "";
  imageChunkData = "";
  imageChunkExpected = 0;
  imageChunkReceived = 0;
}

void resetZplChunkState() {
  zplChunkJobId = "";
  zplChunkData = "";
  zplChunkExpected = 0;
  zplChunkReceived = 0;
}

template <typename T>
inline void dbgPrint(const T& value) {
  if (!debugOutputEnabled || debugOut == nullptr) return;
  debugOut->print(value);
}

template <typename T>
inline void dbgPrintln(const T& value) {
  if (!debugOutputEnabled || debugOut == nullptr) return;
  debugOut->println(value);
}

inline void dbgPrintln() {
  if (!debugOutputEnabled || debugOut == nullptr) return;
  debugOut->println();
}

// Printing tens of KB in one blocking println() can starve the WiFi/MQTT
// background tasks long enough to trip the watchdog, and most serial
// monitors truncate output that long anyway. Head+tail is enough to confirm
// the body wasn't cut off (in particular, that it still ends in ^FS/^XZ).
void dbgPrintHeadTailBytes(const uint8_t* data, size_t len, size_t n = 300) {
  if (!debugOutputEnabled || debugOut == nullptr) return;
  dbgPrint("[zpl] body length=");
  dbgPrintln((unsigned long)len);
  if (len <= n * 2) {
    debugOut->write(data, len);
    debugOut->println();
    return;
  }
  dbgPrintln("[zpl] head:");
  debugOut->write(data, n);
  debugOut->println();
  dbgPrintln("[zpl] tail:");
  debugOut->write(data + (len - n), n);
  debugOut->println();
}

void dbgPrintHeadTail(const String& s, size_t n = 300) {
  dbgPrintHeadTailBytes(reinterpret_cast<const uint8_t*>(s.c_str()), s.length(), n);
}

void stopDebugTransport() {
  if (debugUartActive) {
    debugUart.flush();
    debugUart.end();
    debugUartActive = false;
  }
  if (debugUsbActive) {
    Serial.flush();
    Serial.end();
    debugUsbActive = false;
  }
  debugOut = nullptr;
}

void applyDebugOutputSetting(bool enabled) {
  debugOutputEnabled = enabled;
  if (!debugOutputEnabled) {
    stopDebugTransport();
    return;
  }

  String mode = cfg.debugOutputMode;
  mode.toLowerCase();

  stopDebugTransport();
  if (mode == "uart") {
    if (cfg.debugUartTxPin < 0 || cfg.debugUartRxPin < 0) {
      mode = "usb";
    } else {
      debugUart.begin(115200, SERIAL_8N1, cfg.debugUartRxPin, cfg.debugUartTxPin);
      debugUartActive = true;
      debugOut = &debugUart;
      dbgPrint("[debug] UART logging enabled on TX=");
      dbgPrint(cfg.debugUartTxPin);
      dbgPrint(" RX=");
      dbgPrintln(cfg.debugUartRxPin);
      return;
    }
  }

  Serial.begin(115200);
  delay(50);
  debugUsbActive = true;
  debugOut = &Serial;
  dbgPrintln("[debug] USB serial logging enabled");
}

neoPixelType neopixelTypeFromOrder(const String& orderRaw) {
  String order = orderRaw;
  order.toUpperCase();
  if (order == "RGB") return NEO_RGB + NEO_KHZ800;
  if (order == "RBG") return NEO_RBG + NEO_KHZ800;
  if (order == "GRB") return NEO_GRB + NEO_KHZ800;
  if (order == "GBR") return NEO_GBR + NEO_KHZ800;
  if (order == "BRG") return NEO_BRG + NEO_KHZ800;
  if (order == "BGR") return NEO_BGR + NEO_KHZ800;
  return NEO_GRB + NEO_KHZ800;
}

uint8_t componentByOrder(char channel, const RgbColor& c) {
  switch (channel) {
    case 'R': return c.r;
    case 'G': return c.g;
    case 'B': return c.b;
    default: return 0;
  }
}

void clearStatusLed() {
  if (cfg.ledMode == "neopixel") {
    if (statusPixel) {
      statusPixel->setPixelColor(0, statusPixel->Color(0, 0, 0));
      statusPixel->show();
    }
    return;
  }

  if (cfg.ledMode == "rgb") {
    if (cfg.ledPinR >= 0) digitalWrite(cfg.ledPinR, LOW);
    if (cfg.ledPinG >= 0) digitalWrite(cfg.ledPinG, LOW);
    if (cfg.ledPinB >= 0) digitalWrite(cfg.ledPinB, LOW);
  }
}

void setupStatusLed() {
  ledConfigured = false;
  ledBlinkOn = false;
  ledEventUntilMs = 0;
  ledEventType = LedEventType::none;

  if (statusPixel) {
    statusPixel->clear();
    statusPixel->show();
    delete statusPixel;
    statusPixel = nullptr;
  }

  if (cfg.ledBlinkMs < 100) cfg.ledBlinkMs = 100;
  if (cfg.ledBlinkMs > 5000) cfg.ledBlinkMs = 5000;

  if (cfg.ledMode == "neopixel") {
    if (cfg.ledPin < 0) {
      dbgPrintln("[led] neopixel mode selected but ledPin < 0");
      return;
    }
    statusPixel = new Adafruit_NeoPixel(1, (uint8_t)cfg.ledPin, neopixelTypeFromOrder(cfg.ledOrder));
    statusPixel->begin();
    statusPixel->clear();
    statusPixel->show();
    ledConfigured = true;
    dbgPrint("[led] neopixel on pin ");
    dbgPrint(cfg.ledPin);
    dbgPrint(", order=");
    dbgPrintln(cfg.ledOrder);
    return;
  }

  if (cfg.ledMode == "rgb") {
    if (cfg.ledPinR < 0 || cfg.ledPinG < 0 || cfg.ledPinB < 0) {
      dbgPrintln("[led] rgb mode selected but one or more RGB pins are invalid");
      return;
    }
    pinMode((uint8_t)cfg.ledPinR, OUTPUT);
    pinMode((uint8_t)cfg.ledPinG, OUTPUT);
    pinMode((uint8_t)cfg.ledPinB, OUTPUT);
    clearStatusLed();
    ledConfigured = true;
    dbgPrint("[led] rgb pins R/G/B = ");
    dbgPrint(cfg.ledPinR);
    dbgPrint("/");
    dbgPrint(cfg.ledPinG);
    dbgPrint("/");
    dbgPrintln(cfg.ledPinB);
    return;
  }

  dbgPrintln("[led] status LED disabled");
}

RgbColor baseStatusColor() {
  if (WiFi.status() != WL_CONNECTED) {
    return {255, 0, 0};      // red: fallback AP / no Wi-Fi
  }
  if (!mqtt.connected()) {
    return {255, 180, 0};    // yellow: Wi-Fi yes, MQTT no
  }
  return {0, 255, 0};        // green: Wi-Fi + MQTT
}

RgbColor eventStatusColor(LedEventType evt) {
  if (evt == LedEventType::rx) {
    return {180, 0, 255};    // purple: receiving over MQTT
  }
  if (evt == LedEventType::tx) {
    return {0, 255, 255};    // cyan: sending over MQTT
  }
  return baseStatusColor();
}

void setLedColor(const RgbColor& c) {
  if (!ledConfigured) return;

  if (cfg.ledMode == "neopixel") {
    if (!statusPixel) return;
    statusPixel->setPixelColor(0, statusPixel->Color(c.r, c.g, c.b));
    statusPixel->show();
    return;
  }

  if (cfg.ledMode == "rgb") {
    String order = cfg.ledOrder;
    order.toUpperCase();
    const char c0 = order.length() > 0 ? order[0] : 'R';
    const char c1 = order.length() > 1 ? order[1] : 'G';
    const char c2 = order.length() > 2 ? order[2] : 'B';
    const uint8_t vR = componentByOrder(c0, c);
    const uint8_t vG = componentByOrder(c1, c);
    const uint8_t vB = componentByOrder(c2, c);
    digitalWrite((uint8_t)cfg.ledPinR, vR > 0 ? HIGH : LOW);
    digitalWrite((uint8_t)cfg.ledPinG, vG > 0 ? HIGH : LOW);
    digitalWrite((uint8_t)cfg.ledPinB, vB > 0 ? HIGH : LOW);
  }
}

void markLedEvent(LedEventType eventType) {
  if (!ledConfigured) return;
  ledEventType = eventType;
  const unsigned long now = millis();
  const unsigned long holdMs = (unsigned long)cfg.ledBlinkMs * 2UL;
  ledEventUntilMs = now + (holdMs < 300 ? 300 : holdMs);
}

void updateStatusLed() {
  if (!ledConfigured) return;
  const unsigned long now = millis();
  const unsigned long halfBlink = (unsigned long)cfg.ledBlinkMs / 2UL;
  if (halfBlink == 0) return;

  if (now - ledLastToggleMs >= halfBlink) {
    ledLastToggleMs = now;
    ledBlinkOn = !ledBlinkOn;
  }

  LedEventType activeEvent = LedEventType::none;
  if (ledEventUntilMs > now) {
    activeEvent = ledEventType;
  }

  if (!ledBlinkOn) {
    setLedColor({0, 0, 0});
    return;
  }

  setLedColor(eventStatusColor(activeEvent));
}

void printRuntimeSettings(const char* reason) {
  dbgPrintln();
  dbgPrintln("================ Stikka ESP32 Settings ================");
  dbgPrint("Reason: ");
  dbgPrintln(reason);
  dbgPrint("Printer name: ");
  dbgPrintln(cfg.printerName);
  dbgPrint("Printer type: ");
  dbgPrintln(cfg.printerType);
  dbgPrint("ZPL target: ");
  dbgPrint(cfg.zplTargetHost);
  dbgPrint(":");
  dbgPrintln(cfg.zplTargetPort);
  dbgPrint("Label (mm): ");
  dbgPrint(cfg.labelWidth);
  dbgPrint("x");
  dbgPrint(cfg.labelLength);
  dbgPrint(" @ ");
  dbgPrint(cfg.dpi);
  dbgPrintln(" DPI");
  dbgPrint("Wi-Fi SSID: ");
  dbgPrintln(cfg.wifiSsid.isEmpty() ? String("<not configured>") : cfg.wifiSsid);
  dbgPrint("Wi-Fi password set: ");
  dbgPrintln(cfg.wifiPassword.isEmpty() ? "no" : "yes");
  dbgPrint("MQTT broker: ");
  if (cfg.mqttHost.isEmpty()) {
    dbgPrintln("<not configured>");
  } else {
    dbgPrint(cfg.mqttHost);
    dbgPrint(":");
    dbgPrintln(cfg.mqttPort);
  }
  dbgPrint("MQTT user: ");
  dbgPrintln(cfg.mqttUser.isEmpty() ? String("<none>") : cfg.mqttUser);
  dbgPrint("MQTT TLS: ");
  dbgPrintln(cfg.mqttUseTls ? "enabled" : "disabled");
  dbgPrint("MQTT TLS insecure: ");
  dbgPrintln(cfg.mqttTlsInsecure ? "enabled" : "disabled");
  dbgPrint("MQTT CA cert: ");
  dbgPrintln(cfg.mqttCaCert.isEmpty() ? "<none>" : "configured");
  dbgPrint("Command topic: ");
  dbgPrintln(commandTopic());
  dbgPrint("Status topic: ");
  dbgPrintln(statusTopic());
  dbgPrint("Debug output: ");
  dbgPrintln(cfg.debugOutput ? "enabled" : "disabled");
  dbgPrint("Debug mode: ");
  dbgPrintln(cfg.debugOutputMode);
  dbgPrint("Debug UART TX/RX: ");
  dbgPrint(cfg.debugUartTxPin);
  dbgPrint("/");
  dbgPrintln(cfg.debugUartRxPin);
  dbgPrint("LED mode: ");
  dbgPrintln(cfg.ledMode);
  dbgPrint("LED order: ");
  dbgPrintln(cfg.ledOrder);
  dbgPrint("LED blink ms: ");
  dbgPrintln(cfg.ledBlinkMs);
  dbgPrintln("========================================================");
  dbgPrintln();
}

void printNetworkState(const char* reason) {
  dbgPrintln();
  dbgPrintln("---------------- Network State ----------------");
  dbgPrint("Reason: ");
  dbgPrintln(reason);
  const int wifiState = WiFi.status();
  if (wifiState == WL_CONNECTED) {
    dbgPrint("Wi-Fi: connected to '");
    dbgPrint(WiFi.SSID());
    dbgPrintln("'");
    dbgPrint("IP: ");
    dbgPrintln(WiFi.localIP());
    dbgPrint("Gateway: ");
    dbgPrintln(WiFi.gatewayIP());
    dbgPrint("RSSI: ");
    dbgPrint(WiFi.RSSI());
    dbgPrintln(" dBm");
  } else {
    dbgPrint("Wi-Fi: disconnected (status=");
    dbgPrint(wifiState);
    dbgPrintln(")");
  }

  if (apModeActive) {
    dbgPrint("Fallback AP: active, SSID='");
    dbgPrint(fallbackApSsid());
    dbgPrintln("'");
    dbgPrint("AP IP: ");
    dbgPrintln(WiFi.softAPIP());
  } else {
    dbgPrintln("Fallback AP: inactive");
  }

  dbgPrint("MQTT: ");
  dbgPrintln(mqtt.connected() ? "connected" : "disconnected");
  dbgPrintln("-----------------------------------------------");
  dbgPrintln();
}

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
    dbgPrint("[wifi] fallback AP started: ");
    dbgPrint(ssid);
    dbgPrint(" (ip=");
    dbgPrint(WiFi.softAPIP());
    dbgPrintln(")");
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
  dbgPrintln("[wifi] fallback AP disabled");
}

String commandTopic() {
  return String("/") + cfg.printerName + "/command/";
}

String statusTopic() {
  return String("/") + cfg.printerName + "/status/";
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

String extractJsonStringField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\":\"";
  const int start = json.indexOf(marker);
  if (start < 0) return "";

  int i = start + marker.length();
  String out;
  // Reserve the whole remaining span up front: escape sequences only ever
  // shrink the decoded length, never grow it, so this is a safe upper
  // bound. Growing this incrementally via out += c in the loop below used
  // to silently truncate large payloads (String::operator+= swallows a
  // failed realloc with no error) once the heap got fragmented enough that
  // no single bigger contiguous block was available -- exactly the kind of
  // thing a 65535-byte MQTT buffer plus WiFi/TLS overhead can cause.
  out.reserve((size_t)(json.length() - i));
  while (i < (int)json.length()) {
    const char c = json[i++];
    if (c == '\\') {
      if (i >= (int)json.length()) break;
      const char esc = json[i++];
      switch (esc) {
        case 'n': out += '\n'; break;
        case 't': out += '\t'; break;
        case 'r': out += '\r'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case '"': out += '"'; break;
        case '\\': out += '\\'; break;
        case '/': out += '/'; break;
        default: out += esc; break; // \uXXXX not expected in ZPL/base64 payloads
      }
      continue;
    }
    if (c == '"') {
      return out;
    }
    out += c;
  }

  return "";
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
  cfg.mqttUseTls = prefs.getBool("mqttTls", true);
  cfg.mqttTlsInsecure = prefs.getBool("mqttInsec", true);
  cfg.mqttCaCert = prefs.getString("mqttCa", "");
  cfg.mqttUser = prefs.getString("mqttUser", "");
  cfg.mqttPassword = prefs.getString("mqttPwd", "");
  cfg.statusIntervalSec = prefs.getUShort("statInt", 30);
  cfg.printerName = prefs.getString("printer", "stikka-esp32");
  cfg.printerType = prefs.getString("ptype", "zpl");
  cfg.zplTargetHost = prefs.getString("zplHost", "");
  cfg.zplTargetPort = prefs.getUShort("zplPort", 9100);
  cfg.dpi = prefs.getInt("dpi", 203);
  cfg.labelWidth = prefs.getInt("labelW", 55);
  cfg.labelLength = prefs.getInt("labelL", 55);
  cfg.debugOutput = prefs.getBool("dbgOut", true);
  cfg.debugOutputMode = prefs.getString("dbgMode", "usb");
  cfg.debugUartTxPin = prefs.getInt("dbgTx", 17);
  cfg.debugUartRxPin = prefs.getInt("dbgRx", 16);
  cfg.ledMode = prefs.getString("ledMode", "none");
  cfg.ledPin = prefs.getInt("ledPin", -1);
  cfg.ledPinR = prefs.getInt("ledPinR", -1);
  cfg.ledPinG = prefs.getInt("ledPinG", -1);
  cfg.ledPinB = prefs.getInt("ledPinB", -1);
  cfg.ledOrder = prefs.getString("ledOrder", "GRB");
  cfg.ledBlinkMs = prefs.getUShort("ledBlink", 700);
  prefs.end();
}

void saveConfig() {
  prefs.begin("stikka", false);
  prefs.putString("wifiSsid", cfg.wifiSsid);
  prefs.putString("wifiPwd", cfg.wifiPassword);
  prefs.putString("mqttHost", cfg.mqttHost);
  prefs.putUShort("mqttPort", cfg.mqttPort);
  prefs.putBool("mqttTls", cfg.mqttUseTls);
  prefs.putBool("mqttInsec", cfg.mqttTlsInsecure);
  prefs.putString("mqttCa", cfg.mqttCaCert);
  prefs.putString("mqttUser", cfg.mqttUser);
  prefs.putString("mqttPwd", cfg.mqttPassword);
  prefs.putUShort("statInt", cfg.statusIntervalSec);
  prefs.putString("printer", cfg.printerName);
  prefs.putString("ptype", cfg.printerType);
  prefs.putString("zplHost", cfg.zplTargetHost);
  prefs.putUShort("zplPort", cfg.zplTargetPort);
  prefs.putInt("dpi", cfg.dpi);
  prefs.putInt("labelW", cfg.labelWidth);
  prefs.putInt("labelL", cfg.labelLength);
  prefs.putBool("dbgOut", cfg.debugOutput);
  prefs.putString("dbgMode", cfg.debugOutputMode);
  prefs.putInt("dbgTx", cfg.debugUartTxPin);
  prefs.putInt("dbgRx", cfg.debugUartRxPin);
  prefs.putString("ledMode", cfg.ledMode);
  prefs.putInt("ledPin", cfg.ledPin);
  prefs.putInt("ledPinR", cfg.ledPinR);
  prefs.putInt("ledPinG", cfg.ledPinG);
  prefs.putInt("ledPinB", cfg.ledPinB);
  prefs.putString("ledOrder", cfg.ledOrder);
  prefs.putUShort("ledBlink", cfg.ledBlinkMs);
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
  markLedEvent(LedEventType::tx);
  const String payload = buildStatusJson(phase, lastError);
  dbgPrint("[mqtt] publish status -> ");
  dbgPrintln(statusTopic());
  dbgPrint("[mqtt] payload bytes: ");
  dbgPrintln(payload.length());
  dbgPrint("[mqtt] payload: ");
  dbgPrintln(shortenForLog(payload));
  const bool ok = mqtt.publish(statusTopic().c_str(), payload.c_str(), true);
  if (!ok) {
    dbgPrint("[mqtt] publish status failed, state=");
    dbgPrintln(mqtt.state());
  }
}

bool sendZPLToTarget(const String& zpl, String& err) {
  const uint8_t* data = reinterpret_cast<const uint8_t*>(zpl.c_str());
  const size_t len = zpl.length();
  if (len == 0) {
    err = "empty zpl payload";
    return false;
  }
  return sendBytesToTarget(data, len, err);
}

bool sendBytesToTarget(const uint8_t* data, size_t len, String& err) {
  if (len == 0) {
    err = "empty payload";
    return false;
  }

  if (cfg.zplTargetHost.isEmpty()) {
    err = "zplTargetHost is empty";
    return false;
  }

  WiFiClient printerClient;
  if (!printerClient.connect(cfg.zplTargetHost.c_str(), cfg.zplTargetPort)) {
    err = "cannot connect to target printer";
    return false;
  }

  dbgPrint("[target] tcp connected -> ");
  dbgPrint(cfg.zplTargetHost);
  dbgPrint(":");
  dbgPrintln(cfg.zplTargetPort);
  dbgPrint("[target] sending bytes: ");
  dbgPrintln(len);

  size_t sent = 0;
  unsigned long startedAt = millis();
  unsigned long lastProgressAt = startedAt;
  const unsigned long idleTimeoutMs = 7000;
  const unsigned long totalTimeoutMs = 60000;
  const size_t chunkSize = 1024;

  while (sent < len) {
    const unsigned long now = millis();
    if (!printerClient.connected()) {
      dbgPrintln("[target] write loop stop: socket disconnected");
      break;
    }
    if (now - startedAt > totalTimeoutMs) {
      dbgPrintln("[target] write loop stop: total timeout");
      break;
    }
    if (now - lastProgressAt > idleTimeoutMs) {
      dbgPrintln("[target] write loop stop: idle timeout");
      break;
    }

    const size_t remaining = len - sent;
    const size_t toWrite = remaining > chunkSize ? chunkSize : remaining;
    dbgPrint("[target] write -> bytes ");
    dbgPrint(sent);
    dbgPrint("..");
    dbgPrint(sent + toWrite);
    dbgPrint(" of ");
    dbgPrintln(len);
    const size_t written = printerClient.write(data + sent, toWrite);
    dbgPrint("[target] wrote bytes: ");
    dbgPrintln(written);
    if (written == 0) {
      delay(2);
      continue;
    }
    sent += written;
    lastProgressAt = millis();
  }

  printerClient.flush();
  printerClient.stop();
  if (sent == 0) {
    err = "zero bytes sent to target";
    return false;
  }
  if (sent != len) {
    err = "partial send " + String(sent) + "/" + String(len) + " bytes";
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
  markLedEvent(LedEventType::tx);

  JsonDocument doc;
  doc["printer_name"] = cfg.printerName;
  doc["job_id"] = jobId;
  doc["status"] = status;
  doc["message"] = message;

  String payload;
  serializeJson(doc, payload);
  dbgPrint("[mqtt] publish job status -> ");
  dbgPrintln(statusTopic());
  dbgPrint("[mqtt] payload bytes: ");
  dbgPrintln(payload.length());
  dbgPrint("[mqtt] payload: ");
  dbgPrintln(shortenForLog(payload));
  const bool ok = mqtt.publish(statusTopic().c_str(), payload.c_str(), false);
  if (!ok) {
    dbgPrint("[mqtt] publish job status failed, state=");
    dbgPrintln(mqtt.state());
  }
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String incomingTopic(topic);
  if (incomingTopic != commandTopic()) return;
  markLedEvent(LedEventType::rx);

  String msg;
  if (!msg.reserve(length + 1)) {
    dbgPrint("[mqtt] out of memory reserving ");
    dbgPrint(length + 1);
    dbgPrintln(" bytes for incoming message");
    publishJobStatus("", "failed", "esp32 out of memory for incoming message");
    publishStatus("error", "out of memory");
    return;
  }
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  dbgPrint("[mqtt] recv <- ");
  dbgPrintln(incomingTopic);
  dbgPrint("[mqtt] payload bytes: ");
  dbgPrintln(length);
  dbgPrint("[mqtt] payload: ");
  dbgPrintln(shortenForLog(msg));

  // The "payload" field can be tens of KB (a full ZPL/image body). Filter it out of the
  // parse so ArduinoJson never has to duplicate it into the JsonDocument's memory pool --
  // it's pulled out separately below via extractJsonStringField(). Without this filter,
  // deserializeJson() ran out of heap on payloads well under the 65535-byte MQTT ceiling.
  JsonDocument filter;
  filter["job_id"] = true;
  filter["payload_type"] = true;
  filter["payload_encoding"] = true;
  filter["chunk_index"] = true;
  filter["chunks_total"] = true;

  JsonDocument doc;
  const auto err = deserializeJson(doc, msg, DeserializationOption::Filter(filter));
  if (err) {
    dbgPrint("[mqtt] JSON parse error: ");
    dbgPrintln(err.c_str());
    publishJobStatus("", "failed", err.c_str());
    return;
  }

  const char* jobId = doc["job_id"] | "";
  const char* payloadType = doc["payload_type"] | "";
  const char* payloadEncoding = doc["payload_encoding"] | "";
  // "payload" is filtered out of doc above, so it must come from the raw string.
  // Non-const so it can be std::move()'d below instead of deep-copied -- for large
  // (tens-of-KB) bodies, a second copy on top of msg/body was enough to blow the heap,
  // and Arduino String's operator= silently leaves the destination empty on malloc failure.
  String body = extractJsonStringField(msg, "payload");

  dbgPrint("[mqtt] parsed payload bytes=");
  dbgPrintln(body.length());

  dbgPrint("[mqtt] command type=");
  dbgPrint(payloadType);
  dbgPrint(", encoding=");
  dbgPrintln(payloadEncoding);

  publishStatus("printing", "");
  publishJobStatus(jobId, "accepted", "job accepted");

  if (String(payloadType) == "zpl") {
    dbgPrint("[zpl] command received, encoding=");
    dbgPrintln(payloadEncoding);
    String zplBody;
    bool zplIsBase64 = false;
    if (String(payloadEncoding) == "utf8_chunk" || String(payloadEncoding) == "base64_utf8_chunk") {
      const int chunkIndex = doc["chunk_index"] | -1;
      const int chunksTotal = doc["chunks_total"] | 0;
      if (chunkIndex < 0 || chunksTotal <= 0) {
        publishJobStatus(jobId, "failed", "invalid chunk metadata");
        publishStatus("error", "invalid chunk metadata");
        resetZplChunkState();
        return;
      }

      const String chunk = std::move(body);
      if (chunkIndex == 0 || zplChunkJobId != String(jobId)) {
        resetZplChunkState();
        zplChunkJobId = String(jobId);
        zplChunkExpected = (uint16_t)chunksTotal;
        const size_t neededBytes = (size_t)chunksTotal * (size_t)chunk.length();
        if (!zplChunkData.reserve(neededBytes)) {
          dbgPrint("[zpl] out of memory reserving ");
          dbgPrint((unsigned long)neededBytes);
          dbgPrintln(" bytes for chunk reassembly");
          publishJobStatus(jobId, "failed", "esp32 out of memory for zpl reassembly");
          publishStatus("error", "out of memory");
          resetZplChunkState();
          return;
        }
      }

      if (zplChunkExpected != (uint16_t)chunksTotal) {
        publishJobStatus(jobId, "failed", "chunk total mismatch");
        publishStatus("error", "chunk total mismatch");
        resetZplChunkState();
        return;
      }

      if ((int)zplChunkReceived != chunkIndex) {
        publishJobStatus(jobId, "failed", "chunk order mismatch");
        publishStatus("error", "chunk order mismatch");
        resetZplChunkState();
        return;
      }

      zplChunkData += chunk;
      zplChunkReceived++;

      dbgPrint("[mqtt] zpl chunk ");
      dbgPrint(chunkIndex + 1);
      dbgPrint("/");
      dbgPrintln(chunksTotal);

      if (zplChunkReceived < zplChunkExpected) {
        publishJobStatus(jobId, "accepted", "zpl chunk received");
        return;
      }

      zplBody = zplChunkData;
      zplIsBase64 = String(payloadEncoding) == "base64_utf8_chunk";
      dbgPrint("[zpl] all chunks received, bytes=");
      dbgPrintln(zplBody.length());
      resetZplChunkState();
    } else if (String(payloadEncoding) == "utf8" || String(payloadEncoding) == "base64_utf8") {
      zplBody = std::move(body);
      zplIsBase64 = String(payloadEncoding) == "base64_utf8";
    } else {
      publishJobStatus(jobId, "failed", "payload_encoding must be utf8/utf8_chunk/base64_utf8/base64_utf8_chunk for zpl");
      publishStatus("error", "payload_encoding must be utf8/utf8_chunk/base64_utf8/base64_utf8_chunk for zpl");
      return;
    }

    String sendErr;
    bool ok = false;
    if (zplIsBase64) {
      dbgPrint("[zpl] decoding base64 bytes=");
      dbgPrintln(zplBody.length());
      std::unique_ptr<uint8_t[]> bytes;
      size_t decodedLen = 0;
      String decodeErr;
      if (!decodeBase64Payload(zplBody, bytes, decodedLen, decodeErr)) {
        publishJobStatus(jobId, "failed", decodeErr.c_str());
        publishStatus("error", decodeErr.c_str());
        return;
      }
      dbgPrint("[zpl] sending decoded bytes=");
      dbgPrintln(decodedLen);
      dbgPrintln("[zpl] ---- ZPL BODY (head/tail) ----");
      dbgPrintHeadTailBytes(bytes.get(), decodedLen);
      dbgPrintln("[zpl] ---- ZPL BODY END ----");
      ok = sendBytesToTarget(bytes.get(), decodedLen, sendErr);
    } else {
      dbgPrint("[zpl] sending utf8 bytes=");
      dbgPrintln(zplBody.length());
      dbgPrintln("[zpl] ---- ZPL BODY (head/tail) ----");
      dbgPrintHeadTail(zplBody);
      dbgPrintln("[zpl] ---- ZPL BODY END ----");
      ok = sendZPLToTarget(zplBody, sendErr);
    }
    if (!ok) {
      dbgPrint("[zpl] send failed: ");
      dbgPrintln(sendErr);
      publishJobStatus(jobId, "failed", sendErr.c_str());
      publishStatus("error", sendErr.c_str());
      return;
    }

    publishJobStatus(jobId, "done", "zpl sent");
    publishStatus("ready", "");
    return;
  }

  if (String(payloadType) == "image") {
    dbgPrint("[image] command received, encoding=");
    dbgPrintln(payloadEncoding);
    String encoded;
    if (String(payloadEncoding) == "base64_chunk") {
      const int chunkIndex = doc["chunk_index"] | -1;
      const int chunksTotal = doc["chunks_total"] | 0;
      if (chunkIndex < 0 || chunksTotal <= 0) {
        publishJobStatus(jobId, "failed", "invalid chunk metadata");
        publishStatus("error", "invalid chunk metadata");
        resetImageChunkState();
        return;
      }

      const String chunk = std::move(body);
      if (chunkIndex == 0 || imageChunkJobId != String(jobId)) {
        resetImageChunkState();
        imageChunkJobId = String(jobId);
        imageChunkExpected = (uint16_t)chunksTotal;
        const size_t neededBytes = (size_t)chunksTotal * (size_t)chunk.length();
        if (!imageChunkData.reserve(neededBytes)) {
          dbgPrint("[image] out of memory reserving ");
          dbgPrint((unsigned long)neededBytes);
          dbgPrintln(" bytes for chunk reassembly");
          publishJobStatus(jobId, "failed", "esp32 out of memory for image reassembly");
          publishStatus("error", "out of memory");
          resetImageChunkState();
          return;
        }
      }

      if (imageChunkExpected != (uint16_t)chunksTotal) {
        publishJobStatus(jobId, "failed", "chunk total mismatch");
        publishStatus("error", "chunk total mismatch");
        resetImageChunkState();
        return;
      }

      if ((int)imageChunkReceived != chunkIndex) {
        publishJobStatus(jobId, "failed", "chunk order mismatch");
        publishStatus("error", "chunk order mismatch");
        resetImageChunkState();
        return;
      }

      imageChunkData += chunk;
      imageChunkReceived++;

      dbgPrint("[mqtt] image chunk ");
      dbgPrint(chunkIndex + 1);
      dbgPrint("/");
      dbgPrintln(chunksTotal);

      if (imageChunkReceived < imageChunkExpected) {
        publishJobStatus(jobId, "accepted", "image chunk received");
        return;
      }

      encoded = imageChunkData;
      dbgPrint("[image] all chunks received, base64 bytes=");
      dbgPrintln(encoded.length());
      resetImageChunkState();
    } else {
      encoded = std::move(body);
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
    }

    std::unique_ptr<uint8_t[]> bytes;
    size_t decodedLen = 0;
    String decodeErr;
    dbgPrint("[image] decoding base64 bytes=");
    dbgPrintln(encoded.length());
    if (!decodeBase64Payload(encoded, bytes, decodedLen, decodeErr)) {
      dbgPrint("[image] decode failed: ");
      dbgPrintln(decodeErr);
      publishJobStatus(jobId, "failed", decodeErr.c_str());
      publishStatus("error", decodeErr.c_str());
      return;
    }

    dbgPrint("[image] decoded bytes=");
    dbgPrintln(decodedLen);
    dbgPrintln("[image] sending decoded image to target");
    String sendErr;
    if (!sendBytesToTarget(bytes.get(), decodedLen, sendErr)) {
      dbgPrint("[image] send failed: ");
      dbgPrintln(sendErr);
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

  const String mqttHost = normalizeMqttHost(cfg.mqttHost);
  if (mqttHost.isEmpty()) return;

  dbgPrint("[mqtt] connecting to ");
  dbgPrint(mqttHost);
  dbgPrint(":");
  dbgPrint(cfg.mqttPort);
  dbgPrint(" tls=");
  dbgPrintln(cfg.mqttUseTls ? "on" : "off");

  if (cfg.mqttUseTls) {
    if (cfg.mqttTlsInsecure || cfg.mqttCaCert.isEmpty()) {
      mqttNetSecure.setInsecure();
      dbgPrintln("[mqtt] tls insecure mode enabled");
    } else {
      mqttNetSecure.setCACert(cfg.mqttCaCert.c_str());
      dbgPrintln("[mqtt] tls CA certificate configured");
    }
    mqttNetSecure.setHandshakeTimeout(12);
    mqtt.setClient(mqttNetSecure);
  } else {
    mqtt.setClient(mqttNet);
  }

  mqtt.setServer(mqttHost.c_str(), cfg.mqttPort);
  mqtt.setCallback(onMqttMessage);

  // PubSubClient::setBufferSize() reallocs a single contiguous block; on a
  // fragmented heap (WiFi + TLS already hold a lot of it) even this request
  // can fail. If it does, fall back to the largest size that does allocate
  // instead of silently keeping whatever (possibly tiny) buffer was already
  // in place -- any inbound packet bigger than the buffer is read off the
  // socket and then dropped without ever reaching the callback, which
  // otherwise looks just like a message vanishing. The floor here (10240)
  // is still comfortably above one 8000-byte frontend chunk plus its JSON/
  // MQTT wrapper overhead.
  static const uint16_t kBufferFallbacks[] = {
    MQTT_PACKET_BUFFER_SIZE, 14336, 12288, 10240,
  };
  bool bufferOk = false;
  for (uint16_t candidate : kBufferFallbacks) {
    if (mqtt.setBufferSize(candidate)) {
      bufferOk = true;
      break;
    }
  }
  dbgPrint("[mqtt] mqtt buffer size -> ");
  dbgPrint(mqtt.getBufferSize());
  dbgPrintln(bufferOk ? " (ok)" : " (all allocations failed)");

  const String clientId = cfg.printerName + "-bridge";
  bool connected;
  if (cfg.mqttUser.isEmpty()) {
    connected = mqtt.connect(clientId.c_str());
  } else {
    connected = mqtt.connect(clientId.c_str(), cfg.mqttUser.c_str(), cfg.mqttPassword.c_str());
  }

  if (!connected) {
    dbgPrint("[mqtt] connect failed, state=");
    dbgPrintln(mqtt.state());
    return;
  }

  dbgPrintln("[mqtt] connected");
  dbgPrint("[mqtt] packet buffer size: ");
  dbgPrintln(MQTT_PACKET_BUFFER_SIZE);

  if (mqtt.subscribe(commandTopic().c_str(), 1)) {
    dbgPrint("[mqtt] subscribed to ");
    dbgPrintln(commandTopic());
  } else {
    dbgPrint("[mqtt] subscribe failed for ");
    dbgPrintln(commandTopic());
  }
  publishStatus("ready", "");
}

String renderConfigPage() {
  String html;
  html.reserve(9000);
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
  html += "<label><input type='checkbox' name='mqttUseTls' ";
  if (cfg.mqttUseTls) html += "checked";
  html += "> Use TLS (HiveMQ Cloud: on, port 8883)</label>";
  html += "<label><input type='checkbox' name='mqttTlsInsecure' ";
  if (cfg.mqttTlsInsecure) html += "checked";
  html += "> TLS insecure mode (skip certificate validation)</label>";
  html += "<label>CA certificate PEM (optional)<textarea name='mqttCaCert' rows='6' style='width:100%;margin-top:.25rem;'>" + htmlEscape(cfg.mqttCaCert) + "</textarea></label>";
  html += "<label>User<input name='mqttUser' value='" + htmlEscape(cfg.mqttUser) + "'></label>";
  html += "<label>Password<input type='password' name='mqttPassword' value='" + htmlEscape(cfg.mqttPassword) + "'></label>";
  html += "<label>Status publish interval (seconds)<input name='statusIntervalSec' value='" + String(cfg.statusIntervalSec) + "'></label>";
  html += "<small>Host only (no ws:// or wss://). Example: your-cluster.s2.eu.hivemq.cloud</small>";
  html += "</div>";

  html += "<div class='box'><h3>Printer identity</h3>";
  html += "<label>Printer name<input name='printerName' value='" + htmlEscape(cfg.printerName) + "'></label>";
  html += "<label>Printer type (zpl / brother_ql)<input name='printerType' value='" + htmlEscape(cfg.printerType) + "'></label>";
  html += "<small>Status topic: /&lt;printername&gt;/status/ · command topic: /&lt;printername&gt;/command/</small>";
  html += "</div>";

  html += "<div class='box'><h3>ZPL target</h3>";
  html += "<label>Target host<input name='zplTargetHost' value='" + htmlEscape(cfg.zplTargetHost) + "'></label>";
  html += "<label>Target port<input name='zplTargetPort' value='" + String(cfg.zplTargetPort) + "'></label>";
  html += "<label>DPI<input name='dpi' value='" + String(cfg.dpi) + "'></label>";
  html += "<label>Label width mm<input name='labelWidth' value='" + String(cfg.labelWidth) + "'></label>";
  html += "<label>Label length mm<input name='labelLength' value='" + String(cfg.labelLength) + "'></label>";
  html += "</div>";

  html += "<div class='box'><h3>Debug + Status LED</h3>";
  html += "<label><input type='checkbox' name='debugOutput' ";
  if (cfg.debugOutput) html += "checked";
  html += "> Enable serial debug output</label>";
  html += "<label>Debug output mode (usb / uart)<input name='debugOutputMode' value='" + htmlEscape(cfg.debugOutputMode) + "'></label>";
  html += "<label>Debug UART TX pin<input name='debugUartTxPin' value='" + String(cfg.debugUartTxPin) + "'></label>";
  html += "<label>Debug UART RX pin<input name='debugUartRxPin' value='" + String(cfg.debugUartRxPin) + "'></label>";
  html += "<small>Use usb for logs over USB serial, or uart for logs on custom TX/RX pins (115200 8N1).</small>";
  html += "<label>LED mode (none / neopixel / rgb)<input name='ledMode' value='" + htmlEscape(cfg.ledMode) + "'></label>";
  html += "<label>NeoPixel data pin<input name='ledPin' value='" + String(cfg.ledPin) + "'></label>";
  html += "<label>RGB pin R<input name='ledPinR' value='" + String(cfg.ledPinR) + "'></label>";
  html += "<label>RGB pin G<input name='ledPinG' value='" + String(cfg.ledPinG) + "'></label>";
  html += "<label>RGB pin B<input name='ledPinB' value='" + String(cfg.ledPinB) + "'></label>";
  html += "<label>LED color order (RGB/GRB/... )<input name='ledOrder' value='" + htmlEscape(cfg.ledOrder) + "'></label>";
  html += "<label>LED blink speed (ms)<input name='ledBlinkMs' value='" + String(cfg.ledBlinkMs) + "'></label>";
  html += "<small>States: green=WiFi+MQTT, yellow=WiFi only, red=no WiFi/AP, purple=MQTT RX, cyan=MQTT TX.</small>";
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
  cfg.mqttHost = normalizeMqttHost(web.arg("mqttHost"));
  cfg.mqttPort = parsePort(web.arg("mqttPort"), 1883);
  cfg.mqttUseTls = web.hasArg("mqttUseTls");
  cfg.mqttTlsInsecure = web.hasArg("mqttTlsInsecure");
  cfg.mqttCaCert = web.arg("mqttCaCert");
  cfg.mqttUser = web.arg("mqttUser");
  cfg.mqttPassword = web.arg("mqttPassword");
  cfg.statusIntervalSec = (uint16_t)parsePort(web.arg("statusIntervalSec"), 30);
  if (cfg.statusIntervalSec < 1) cfg.statusIntervalSec = 1;
  if (cfg.statusIntervalSec > 3600) cfg.statusIntervalSec = 3600;
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

  cfg.debugOutput = web.hasArg("debugOutput");
  cfg.debugOutputMode = web.arg("debugOutputMode");
  cfg.debugOutputMode.toLowerCase();
  if (cfg.debugOutputMode != "usb" && cfg.debugOutputMode != "uart") {
    cfg.debugOutputMode = "usb";
  }
  cfg.debugUartTxPin = web.arg("debugUartTxPin").toInt();
  cfg.debugUartRxPin = web.arg("debugUartRxPin").toInt();
  cfg.ledMode = web.arg("ledMode");
  cfg.ledMode.toLowerCase();
  if (cfg.ledMode != "none" && cfg.ledMode != "neopixel" && cfg.ledMode != "rgb") {
    cfg.ledMode = "none";
  }
  cfg.ledPin = web.arg("ledPin").toInt();
  cfg.ledPinR = web.arg("ledPinR").toInt();
  cfg.ledPinG = web.arg("ledPinG").toInt();
  cfg.ledPinB = web.arg("ledPinB").toInt();
  cfg.ledOrder = web.arg("ledOrder");
  cfg.ledOrder.toUpperCase();
  cfg.ledBlinkMs = (uint16_t)parsePort(web.arg("ledBlinkMs"), 700);
  if (cfg.ledBlinkMs < 100) cfg.ledBlinkMs = 100;
  if (cfg.ledBlinkMs > 5000) cfg.ledBlinkMs = 5000;

  if (cfg.printerName.isEmpty()) cfg.printerName = "stikka-esp32";
  if (cfg.printerType.isEmpty()) cfg.printerType = "zpl";

  saveConfig();
  applyDebugOutputSetting(cfg.debugOutput);
  setupStatusLed();
  printRuntimeSettings("config saved from web UI");

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
  loadConfig();
  applyDebugOutputSetting(cfg.debugOutput);
  setupStatusLed();
  printRuntimeSettings("boot/reset");

  WiFi.mode(WIFI_AP_STA);
  connectWifi();

  setupWeb();
  printNetworkState("startup");
}

void loop() {
  if (dnsServerActive) {
    dnsServer.processNextRequest();
  }
  web.handleClient();
  connectWifi();
  connectMqtt();
  updateStatusLed();

  const int wifiNow = WiFi.status();
  if (wifiNow != lastWifiStatus) {
    lastWifiStatus = wifiNow;
    if (wifiNow == WL_CONNECTED) {
      printNetworkState("wifi connected");
    } else {
      printNetworkState("wifi disconnected");
    }
  }

  if (apModeActive != lastApModeState) {
    lastApModeState = apModeActive;
    printNetworkState(apModeActive ? "fallback AP enabled" : "fallback AP disabled");
  }

  if (mqtt.connected()) {
    mqtt.loop();
    const unsigned long now = millis();
    const unsigned long intervalMs = (unsigned long)cfg.statusIntervalSec * 1000UL;
    if (now - lastStatusMs > intervalMs) {
      publishStatus("ready", "");
      lastStatusMs = now;
    }
  }
}
