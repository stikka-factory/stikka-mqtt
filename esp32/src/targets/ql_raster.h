#pragma once

#include <Arduino.h>

#ifdef PROTOCOL_QL
// Decodes a PNG (raw file bytes, already base64-decoded by mqtt_bridge.cpp)
// and prints it on a Brother QL-family label printer: resizes it to the
// configured label geometry at the QL family's native 300dpi, thresholds it
// to 1-bit, centers it (or offsets it per cfg.qlRightMarginDots) within the
// configured printhead width, and streams it out as raster protocol
// commands via the compiled-in target's streaming write contract
// (targets/target.h -- this build pairs PROTOCOL_QL with TARGET_USB).
//
// See ql_raster.cpp's header comment for exactly what this does and doesn't
// replicate from Brother's raster protocol.
bool qlPrintPng(const uint8_t* pngData, size_t pngLen, String& err);
#endif
