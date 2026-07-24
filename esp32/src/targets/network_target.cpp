#include "network_target.h"

#include <WiFi.h>

#include "../config.h"
#include "../logging.h"

bool networkTargetSend(const uint8_t* data, size_t len, String& err) {
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
      dbgPrintln("[target] write loop stop: socket disconnected", LogLevel::LOG_WARN);
      break;
    }
    if (now - startedAt > totalTimeoutMs) {
      dbgPrintln("[target] write loop stop: total timeout", LogLevel::LOG_WARN);
      break;
    }
    if (now - lastProgressAt > idleTimeoutMs) {
      dbgPrintln("[target] write loop stop: idle timeout", LogLevel::LOG_WARN);
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

bool networkTargetSendString(const String& body, String& err) {
  const uint8_t* data = reinterpret_cast<const uint8_t*>(body.c_str());
  const size_t len = body.length();
  if (len == 0) {
    err = "empty zpl payload";
    return false;
  }
  return networkTargetSend(data, len, err);
}
