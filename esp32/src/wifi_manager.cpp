#include "wifi_manager.h"

#include <DNSServer.h>
#include <WiFi.h>

#include "config.h"
#include "logging.h"
#include "mqtt_bridge.h"

static DNSServer dnsServer;
static bool dnsServerActive = false;
static bool apModeActive = false;
static unsigned long lastWifiAttemptMs = 0;
static unsigned long wifiDisconnectedSinceMs = 0;
static int lastWifiStatus = -1;
static bool lastApModeState = false;

static const unsigned long WIFI_RETRY_EVERY_MS = 5000;
static const unsigned long WIFI_FALLBACK_AP_AFTER_MS = 20000;
static const char* AP_PASSWORD = "stikkaesp32";
static const uint16_t DNS_PORT = 53;

bool wifiIsConnected() {
  return WiFi.status() == WL_CONNECTED;
}

bool wifiApModeActive() {
  return apModeActive;
}

const char* wifiApPassword() {
  return AP_PASSWORD;
}

String wifiFallbackApSsid() {
  uint32_t mac = (uint32_t)ESP.getEfuseMac();
  String suffix = String(mac, HEX);
  suffix.toUpperCase();
  return String("Stikka-") + suffix;
}

static void ensureFallbackAp() {
  if (apModeActive) return;
  const String ssid = wifiFallbackApSsid();
  if (WiFi.softAP(ssid.c_str(), AP_PASSWORD)) {
    apModeActive = true;
    dnsServer.start(DNS_PORT, "*", WiFi.softAPIP());
    dnsServerActive = true;
    dbgPrint("[wifi] fallback AP started: ");
    dbgPrint(ssid);
    dbgPrint(" (ip=");
    dbgPrint(WiFi.softAPIP());
    dbgPrintln(")", LogLevel::LOG_WARN);
  }
}

void wifiDisableFallbackAp() {
  if (!apModeActive) return;
  if (dnsServerActive) {
    dnsServer.stop();
    dnsServerActive = false;
  }
  WiFi.softAPdisconnect(true);
  apModeActive = false;
  dbgPrintln("[wifi] fallback AP disabled", LogLevel::LOG_INFO);
}

static void connectWifi() {
  const unsigned long now = millis();

  if (cfg.wifiSsid.isEmpty()) {
    ensureFallbackAp();
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiDisconnectedSinceMs = 0;
    wifiDisableFallbackAp();
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

void wifiForceDisconnect() {
  WiFi.disconnect(true);
  wifiDisconnectedSinceMs = millis();
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
    dbgPrint(wifiFallbackApSsid());
    dbgPrintln("'");
    dbgPrint("AP IP: ");
    dbgPrintln(WiFi.softAPIP());
  } else {
    dbgPrintln("Fallback AP: inactive");
  }

  dbgPrint("MQTT: ");
  dbgPrintln(mqttIsConnected() ? "connected" : "disconnected");
  dbgPrintln("-----------------------------------------------");
  dbgPrintln();
}

void wifiManagerSetup() {
  WiFi.mode(WIFI_AP_STA);
  connectWifi();
}

void wifiManagerLoop() {
  if (dnsServerActive) {
    dnsServer.processNextRequest();
  }

  connectWifi();

  const int wifiNow = WiFi.status();
  if (wifiNow != lastWifiStatus) {
    lastWifiStatus = wifiNow;
    if (wifiNow == WL_CONNECTED) {
      // LOG_ERROR here isn't about severity -- it's the one level guaranteed
      // to show regardless of the configured log level (see flushPendingLogLine:
      // a line is dropped only if it's MORE verbose than cfg.logLevel, and
      // nothing is more severe than ERROR). The IP is how you find the device
      // to reconfigure it, so it needs to survive even the quietest setting.
      dbgPrint("[wifi] connected, ip=");
      dbgPrintln(WiFi.localIP(), LogLevel::LOG_ERROR);
      printNetworkState("wifi connected");
    } else {
      dbgPrintln("[wifi] disconnected", LogLevel::LOG_ERROR);
      printNetworkState("wifi disconnected");
    }
  }

  if (apModeActive != lastApModeState) {
    lastApModeState = apModeActive;
    printNetworkState(apModeActive ? "fallback AP enabled" : "fallback AP disabled");
  }
}
