#pragma once

#include <Arduino.h>

// WiFi.mode(WIFI_AP_STA) + first connect attempt. Call once from setup().
void wifiManagerSetup();

// DNS captive-portal servicing, station reconnect/retry, fallback-AP
// enter/exit, and state-change diagnostics. Call once per loop() iteration.
void wifiManagerLoop();

bool wifiIsConnected();
bool wifiApModeActive();
String wifiFallbackApSsid();
const char* wifiApPassword();

// Torn down explicitly (rather than left to the next wifiManagerLoop()
// retry) when the web UI saves new Wi-Fi/MQTT settings, so the old
// connection doesn't linger with stale credentials.
void wifiDisableFallbackAp();
void wifiForceDisconnect();

void printNetworkState(const char* reason);
