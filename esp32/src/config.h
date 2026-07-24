#pragma once

#include <Arduino.h>

// Compile-time defaults, overridable per platformio.ini env via build_flags
// (e.g. -D DEFAULT_MQTT_HOST='"host"'). These only take effect on first boot
// / after an NVS erase -- loadConfig() prefers whatever's already saved in
// Preferences, since these are meant to seed a fresh device, not override one
// a user already configured through the web UI.
#ifndef DEFAULT_MQTT_HOST
#define DEFAULT_MQTT_HOST ""
#endif
#ifndef DEFAULT_MQTT_PORT
#define DEFAULT_MQTT_PORT 1883
#endif
#ifndef DEFAULT_MQTT_USE_TLS
#define DEFAULT_MQTT_USE_TLS true
#endif
#ifndef DEFAULT_MQTT_TLS_INSECURE
#define DEFAULT_MQTT_TLS_INSECURE true
#endif
#ifndef DEFAULT_MQTT_USER
#define DEFAULT_MQTT_USER ""
#endif
#ifndef DEFAULT_MQTT_PASSWORD
#define DEFAULT_MQTT_PASSWORD ""
#endif
#ifndef DEFAULT_LED_MODE
#define DEFAULT_LED_MODE "none"
#endif
#ifndef DEFAULT_LED_PIN
#define DEFAULT_LED_PIN -1
#endif
#ifndef DEFAULT_LED_ORDER
#define DEFAULT_LED_ORDER "GRB"
#endif

enum class LogLevel : uint8_t {
  LOG_ERROR = 0,
  LOG_WARN = 1,
  LOG_INFO = 2,
  LOG_DEBUG = 3,
};

const char* logLevelName(LogLevel level);
LogLevel logLevelFromString(const String& raw, LogLevel fallback);

struct AppConfig {
  String wifiSsid;
  String wifiPassword;
  String mqttHost = DEFAULT_MQTT_HOST;
  uint16_t mqttPort = DEFAULT_MQTT_PORT;
  bool mqttUseTls = DEFAULT_MQTT_USE_TLS;
  bool mqttTlsInsecure = DEFAULT_MQTT_TLS_INSECURE;
  String mqttCaCert;
  String mqttUser = DEFAULT_MQTT_USER;
  String mqttPassword = DEFAULT_MQTT_PASSWORD;
  uint16_t statusIntervalSec = 30;
  String printerName = "stikka-esp32";
  String printerType = "zpl";
  String zplTargetHost;
  uint16_t zplTargetPort = 9100;
  int dpi = 203;
  int labelWidth = 55;
  int labelLength = 55;
  bool zplCompressionSupported = false; // printer accepts ^GF :Z64:/:B64: data
  bool debugOutput = true;
  String debugOutputMode = "usb"; // usb | uart
  int debugUartTxPin = 17;
  int debugUartRxPin = 16;
  String ledMode = DEFAULT_LED_MODE;   // none | neopixel | rgb
  int ledPin = DEFAULT_LED_PIN;         // neopixel data pin
  int ledPinR = -1;              // discrete RGB R pin
  int ledPinG = -1;              // discrete RGB G pin
  int ledPinB = -1;              // discrete RGB B pin
  String ledOrder = DEFAULT_LED_ORDER; // NeoPixel byte order (RGB, GRB, ...)
  uint16_t ledBlinkMs = 700;     // full blink cycle in ms
  LogLevel logLevel = LogLevel::LOG_INFO; // verbosity for serial output + web Logs tab
};

extern AppConfig cfg;

void loadConfig();
void saveConfig();

// Dumps the full config + derived MQTT topics to the log at LOG_INFO,
// bracketed for readability -- called on boot and after a config save so the
// active settings are always visible in the Logs tab / serial output.
void printRuntimeSettings(const char* reason);
