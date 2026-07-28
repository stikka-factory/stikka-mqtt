#include <Arduino.h>

#include "config.h"
#include "logging.h"
#include "mqtt_bridge.h"
#include "status_led.h"
#include "targets/target.h"
#include "web_ui.h"
#include "wifi_manager.h"

void setup() {
  loadConfig();
  applyDebugOutputSetting(cfg.debugOutput);
  setupStatusLed();
  targetSetup();
  printRuntimeSettings("boot/reset");
  dbgPrintln("[boot] Stikka ESP32 bridge starting", LogLevel::LOG_INFO);

  wifiManagerSetup();
  webUiSetup();
  dbgPrintln("[boot] web UI ready", LogLevel::LOG_INFO);
  printNetworkState("startup");
}

void loop() {
  wifiManagerLoop();
  webUiLoop();
  mqttBridgeLoop();
  targetLoop();
  updateStatusLed(wifiIsConnected(), mqttIsConnected());
}
