#include "target.h"

#ifdef TARGET_USB

#include "../config.h"
#include "../logging.h"

// "usb" transport method: reuses the board's USB/programming port
// (Serial/UART0, the same wire exposed through its onboard USB-serial
// chip) to send print data straight to a printer/host on the other end of
// the cable. This firmware build forces debugOutputMode away from "usb"
// (see platformio.ini's DEFAULT_DEBUG_OUTPUT_MODE and logging.cpp) so debug
// log text never gets interleaved into the print byte stream on this same
// wire.
static bool usbStarted = false;

const char* targetMethodName() { return "usb"; }

void targetSetup() {
  Serial.begin(cfg.printerUsbBaud);
  delay(50);
  usbStarted = true;
  dbgPrint("[target] usb target Serial baud=");
  dbgPrintln(cfg.printerUsbBaud, LogLevel::LOG_INFO);
}

bool targetStreamBegin(String& err) {
  if (!usbStarted) {
    err = "usb target Serial not started";
    return false;
  }
  return true;
}

bool targetStreamWrite(const uint8_t* data, size_t len, String& err) {
  return writeStreamWithTimeout(Serial, data, len, 256, err);
}

void targetStreamEnd() {
  Serial.flush();
}

bool targetSend(const uint8_t* data, size_t len, String& err) {
  if (len == 0) {
    err = "empty payload";
    return false;
  }
  if (!targetStreamBegin(err)) return false;
  const bool ok = targetStreamWrite(data, len, err);
  targetStreamEnd();
  return ok;
}

bool targetSendString(const String& body, String& err) {
  if (body.length() == 0) {
    err = "empty zpl payload";
    return false;
  }
  return targetSend(reinterpret_cast<const uint8_t*>(body.c_str()), body.length(), err);
}

#endif // TARGET_USB
