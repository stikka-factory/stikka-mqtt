#include "web_ui.h"

#include <WebServer.h>
#include <WiFi.h>

#include "config.h"
#include "logging.h"
#include "mqtt_bridge.h"
#include "status_led.h"
#include "targets/network_target.h"
#include "wifi_manager.h"

static WebServer web(80);

static String htmlEscape(const String& in) {
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

static uint16_t parsePort(const String& value, uint16_t fallback) {
  const long p = value.toInt();
  if (p <= 0 || p > 65535) return fallback;
  return (uint16_t)p;
}

static String renderConfigPage() {
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
  html += "nav{margin-bottom:1rem;} nav a{margin-right:1rem;font-weight:600;text-decoration:none;color:#333;}";
  html += "</style></head><body>";
  html += "<nav><a href='/'>Config</a><a href='/logs'>Logs</a></nav>";
  html += "<h1>Stikka ESP32 Bridge</h1>";
  html += "<p class='sub'>Configure Wi-Fi, MQTT and ZPL target for this printer bridge.</p>";

  html += "<div class='box'><strong>Runtime status</strong><br>";
  html += "Wi-Fi: ";
  html += wifiIsConnected() ? "connected" : "disconnected";
  if (wifiIsConnected()) {
    html += " (" + WiFi.localIP().toString() + ")";
  }
  html += "<br>MQTT: ";
  html += mqttIsConnected() ? "connected" : "disconnected";
  html += "<br>Fallback AP: ";
  if (wifiApModeActive()) {
    html += "active (SSID: <code>" + wifiFallbackApSsid() + "</code>, password: <code>" + String(wifiApPassword()) + "</code>)";
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
  html += "<small>0 = endless label (continuous roll, no fixed length).</small>";
  html += "<label><input type='checkbox' name='zplCompressionSupported' ";
  if (cfg.zplCompressionSupported) html += "checked";
  html += "> Printer supports compressed graphics (:Z64:/:B64:)</label>";
  html += "<small>Not every ZPL printer implements this. Only enable if you've confirmed image labels print correctly with it on -- if unsure, leave off.</small>";
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

static String renderLogsPage() {
  String html;
  html.reserve(4000);
  html += "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>";
  html += "<title>Stikka ESP32 - Logs</title><style>";
  html += "body{font-family:Arial,sans-serif;max-width:960px;margin:1rem auto;padding:0 1rem;}";
  html += "h1{margin-bottom:.25rem;} nav{margin-bottom:1rem;} nav a{margin-right:1rem;font-weight:600;text-decoration:none;color:#333;}";
  html += "select,button{padding:.4rem .6rem;} .toolbar{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem;}";
  html += "#log{border:1px solid #ddd;border-radius:8px;background:#111;color:#ddd;font-family:Consolas,Menlo,monospace;";
  html += "font-size:.85rem;padding:.75rem;height:60vh;overflow-y:auto;white-space:pre-wrap;word-break:break-word;}";
  html += ".lvl-ERROR{color:#ff6b6b;} .lvl-WARN{color:#ffd166;} .lvl-INFO{color:#8ecae6;} .lvl-DEBUG{color:#999;}";
  html += "</style></head><body>";
  html += "<nav><a href='/'>Config</a><a href='/logs'>Logs</a></nav>";
  html += "<h1>Device Logs</h1>";

  html += "<div class='toolbar'>";
  html += "<form method='POST' action='/logs/level' style='display:inline;'>";
  html += "<label>Log level ";
  html += "<select name='level' onchange='this.form.submit()'>";
  static const char* kLevels[] = {"ERROR", "WARN", "INFO", "DEBUG"};
  for (const char* lvl : kLevels) {
    html += "<option value='" + String(lvl) + "'";
    if (String(logLevelName(cfg.logLevel)) == lvl) html += " selected";
    html += ">" + String(lvl) + "</option>";
  }
  html += "</select></label></form>";
  html += "<label><input type='checkbox' id='autoscroll' checked> Auto-scroll</label>";
  html += "<label><input type='checkbox' id='autorefresh' checked> Auto-refresh</label>";
  html += "<form method='POST' action='/logs/clear' style='display:inline;'><button type='submit'>Clear</button></form>";
  html += "</div>";

  html += "<div id='log'></div>";

  html += "<script>";
  html += "let sinceSeq=0;const logEl=document.getElementById('log');";
  html += "function fmtMs(ms){const s=Math.floor(ms/1000);return '['+String(Math.floor(s/3600)).padStart(2,'0')+':'+String(Math.floor((s%3600)/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')+']';}";
  html += "async function poll(){";
  html += "try{const res=await fetch('/logs.json?since='+sinceSeq);const data=await res.json();";
  html += "for(const e of data.entries){sinceSeq=Math.max(sinceSeq,e.seq);";
  html += "const line=document.createElement('div');line.className='lvl-'+e.level;";
  html += "line.textContent=fmtMs(e.ms)+' '+e.level+' '+e.msg;logEl.appendChild(line);}";
  html += "if(data.entries.length && document.getElementById('autoscroll').checked){logEl.scrollTop=logEl.scrollHeight;}";
  html += "}catch(e){}";
  html += "setTimeout(poll, document.getElementById('autorefresh').checked?1500:4000);";
  html += "}";
  html += "poll();";
  html += "</script>";

  html += "</body></html>";
  return html;
}

static void handleRoot() {
  web.send(200, "text/html", renderConfigPage());
}

static void handleCaptivePortal() {
  web.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  web.sendHeader("Pragma", "no-cache");
  web.sendHeader("Expires", "-1");
  handleRoot();
}

static void handleCaptivePortalRedirect() {
  if (wifiApModeActive()) {
    web.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/", true);
    web.send(302, "text/plain", "");
    return;
  }
  web.send(404, "text/plain", "not found");
}

static void handleSave() {
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
  // 0 is a valid, deliberate value here: it means "endless label" (continuous
  // roll, no fixed length) throughout the frontend (zpl-image.ts, mqtt-api.ts,
  // editor.ts, ui.ts). Only negative input is nonsense and falls back to the default.
  if (cfg.labelLength < 0) cfg.labelLength = 55;
  cfg.zplCompressionSupported = web.hasArg("zplCompressionSupported");

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
  dbgPrintln("[config] settings saved via web UI, reconnecting wifi/mqtt", LogLevel::LOG_INFO);
  printRuntimeSettings("config saved from web UI");

  // Send the response before tearing down the network. The browser's request
  // often arrived over the ESP32's own fallback AP -- if wifiDisableFallbackAp()
  // (WiFi.softAPdisconnect) runs first, that AP link drops before the HTTP
  // response is ever written to the socket, and the browser hangs forever
  // waiting for a reply that can no longer arrive. The delay after send()
  // gives the WiFi stack a moment to actually get the response bytes over the
  // air before the interface goes down.
  web.send(200, "text/plain", "saved; reconnecting wifi and mqtt");
  web.client().flush();
  delay(250);

  wifiForceDisconnect();
  wifiDisableFallbackAp();
}

static void handleTest() {
  String err;
  const String zpl = "^XA^CF0,30^FO40,40^FDStikka ESP32 test^FS^XZ";
  const bool ok = networkTargetSendString(zpl, err);
  if (!ok) {
    dbgPrintln("[test] test print failed: " + err, LogLevel::LOG_ERROR);
    web.send(500, "text/plain", "test failed: " + err);
    return;
  }
  dbgPrintln("[test] test label sent", LogLevel::LOG_INFO);
  web.send(200, "text/plain", "test label sent");
}

static void handleLogsPage() {
  web.send(200, "text/html", renderLogsPage());
}

static void handleLogsJson() {
  uint32_t since = 0;
  if (web.hasArg("since")) since = (uint32_t)strtoul(web.arg("since").c_str(), nullptr, 10);
  web.send(200, "application/json", logEntriesToJson(since));
}

static void handleLogsSetLevel() {
  cfg.logLevel = logLevelFromString(web.arg("level"), cfg.logLevel);
  saveConfig();
  dbgPrintln(String("[config] log level set to ") + logLevelName(cfg.logLevel), LogLevel::LOG_INFO);
  web.sendHeader("Location", "/logs", true);
  web.send(302, "text/plain", "");
}

static void handleLogsClear() {
  logBufferClear();
  web.sendHeader("Location", "/logs", true);
  web.send(302, "text/plain", "");
}

void webUiSetup() {
  web.on("/", HTTP_GET, handleRoot);
  web.on("/generate_204", HTTP_GET, handleCaptivePortalRedirect);
  web.on("/gen_204", HTTP_GET, handleCaptivePortalRedirect);
  web.on("/hotspot-detect.html", HTTP_GET, handleCaptivePortal);
  web.on("/connecttest.txt", HTTP_GET, handleCaptivePortal);
  web.on("/ncsi.txt", HTTP_GET, handleCaptivePortal);
  web.on("/fwlink", HTTP_GET, handleCaptivePortalRedirect);
  web.on("/save", HTTP_POST, handleSave);
  web.on("/logs", HTTP_GET, handleLogsPage);
  web.on("/logs.json", HTTP_GET, handleLogsJson);
  web.on("/logs/level", HTTP_POST, handleLogsSetLevel);
  web.on("/logs/clear", HTTP_POST, handleLogsClear);
  web.on("/test", HTTP_POST, handleTest);
  web.onNotFound(handleCaptivePortalRedirect);
  web.begin();
}

void webUiLoop() {
  web.handleClient();
}
