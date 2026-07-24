#pragma once

#include <Arduino.h>

// "network" transport method: relays bytes to a plain TCP printer target
// (cfg.zplTargetHost:cfg.zplTargetPort). Protocol-agnostic passthrough --
// this firmware doesn't parse ZPL or image data, it just forwards whatever
// bytes the job handler decoded, so the same function serves both the "zpl"
// and "image" payload types. A future transport method (e.g. USB) would
// live alongside this as its own targets/*_target.h/.cpp pair implementing
// the same send-bytes contract, selected per PlatformIO env.
bool networkTargetSend(const uint8_t* data, size_t len, String& err);
bool networkTargetSendString(const String& body, String& err);
