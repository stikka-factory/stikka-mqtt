#include "ql_raster.h"

#ifdef PROTOCOL_QL

#include <PNGdec.h>

#include <math.h>
#include <new>

#include "../config.h"
#include "../logging.h"
#include "target.h"

// Brother QL raster protocol translator.
//
// Command byte sequence (order + values) is taken from the reference
// open-source implementation (github.com/pklaus/brother_ql,
// raster.py/conversion.py) rather than reconstructed from memory. What this
// firmware deliberately does NOT replicate from that reference, because it
// has no per-model/per-media database and can't be validated against real
// hardware from here:
//
//  - Brother's exact per-media-width offset table (label.py's `offset_r`):
//    this centers the image instead (or applies cfg.qlRightMarginDots as a
//    fixed right-edge offset, brother_ql-style, if you look up the real
//    value for your tape and set it).
//  - Reading the printer's status response (ESC i S) before printing --
//    this build only ever writes to the target, so a status query would
//    have nowhere to send its reply.
//  - Dithering (this thresholds at 50% gray, like the ZPL path's own
//    thresholdToMonoBytes()), red/black two-color printing, and 600dpi mode.
//  - Raster compression (PackBits) -- rows are always sent uncompressed,
//    which every QL model accepts regardless of whether it also supports
//    compression.
//
// cfg.qlPrintheadPx selects between the two known printhead widths: 720px
// (90 bytes/row -- QL-500/550/560/570/580N/650TD/700/710W/720NW/800/810W/
// 820NWB) and 1296px (162 bytes/row -- QL-1050/1060N/1100/1110NWB/1115NWB).

namespace {

PNG png;

// Streaming decode/resize/threshold state, shared between qlPrintPng() and
// the PNGdec draw callback (PNGdec's C callback signature carries no
// per-open user pointer we control, so this has to be file-scope).
struct QlState {
  int srcWidth = 0;
  int srcHeight = 0;
  int targetWidthPx = 0;   // active (content) width, before centering/margin padding
  int targetHeightPx = 0;  // total raster line count, matches the rnumber sent in the header
  int printheadPx = 720;
  int rowBytes = 90;       // printheadPx / 8
  int offsetPx = 0;        // bit offset of the active area from the left, pre-mirror
  int nextTargetRow = 0;
  bool failed = false;
  String err;
  uint16_t* lineBuf = nullptr; // one decoded source row, RGB565, srcWidth entries
};

QlState g;

int pngDrawCallback(PNGDRAW* pDraw) {
  if (g.failed || g.lineBuf == nullptr) return 0;
  png.getLineAsRGB565(pDraw, g.lineBuf, PNG_RGB565_LITTLE_ENDIAN, 0xffffffff);

  while (g.nextTargetRow < g.targetHeightPx) {
    const int neededSrcY = (int)((int64_t)g.nextTargetRow * g.srcHeight / g.targetHeightPx);
    if (neededSrcY != pDraw->y) break;

    uint8_t row[162] = {0}; // max rowBytes across both printhead widths
    for (int destX = 0; destX < g.targetWidthPx; destX++) {
      const int srcX = (int)((int64_t)destX * g.srcWidth / g.targetWidthPx);
      const uint16_t px = g.lineBuf[srcX];
      const uint8_t r5 = (px >> 11) & 0x1F;
      const uint8_t g6 = (px >> 5) & 0x3F;
      const uint8_t b5 = px & 0x1F;
      const uint8_t r8 = (uint8_t)((r5 * 255) / 31);
      const uint8_t g8 = (uint8_t)((g6 * 255) / 63);
      const uint8_t b8 = (uint8_t)((b5 * 255) / 31);
      const int gray = (299 * r8 + 587 * g8 + 114 * b8) / 1000;
      if (gray < 128) {
        // Raster lines are transmitted head-to-tail mirrored (Brother's own
        // reference implementation flips the image left-right before
        // packing bits -- see add_raster_data() in raster.py) -- write to
        // the mirrored bit position directly instead of building the row
        // normally and reversing it afterwards.
        const int bitPos = g.printheadPx - 1 - (g.offsetPx + destX);
        if (bitPos >= 0 && bitPos < g.printheadPx) {
          row[bitPos / 8] |= (uint8_t)(0x80 >> (bitPos % 8));
        }
      }
    }

    String writeErr;
    const uint8_t header[3] = {0x67, 0x00, (uint8_t)g.rowBytes};
    if (!targetStreamWrite(header, 3, writeErr) || !targetStreamWrite(row, (size_t)g.rowBytes, writeErr)) {
      g.failed = true;
      g.err = writeErr.isEmpty() ? "raster line write failed" : writeErr;
      return 0;
    }
    g.nextTargetRow++;
  }
  return 1;
}

bool sendQlHeader(String& err) {
  static const uint8_t switchRaster[4] = {0x1B, 0x69, 0x61, 0x01}; // ESC i a 1

  // Matches brother_ql's own sequence: switch-to-raster is sent both before
  // and after invalidate+initialize (the first call is a best-effort nudge
  // for whatever mode the printer happened to be left in).
  if (!targetStreamWrite(switchRaster, 4, err)) return false;

  {
    uint8_t zero[32] = {0};
    int remaining = cfg.qlInvalidateBytes;
    while (remaining > 0) {
      const int n = remaining > 32 ? 32 : remaining;
      if (!targetStreamWrite(zero, (size_t)n, err)) return false;
      remaining -= n;
    }
  }

  static const uint8_t init[2] = {0x1B, 0x40}; // ESC @
  if (!targetStreamWrite(init, 2, err)) return false;
  if (!targetStreamWrite(switchRaster, 4, err)) return false;

  {
    // Media & quality (ESC i z). mtype 0x0A = continuous/endless tape (no
    // fixed length calibrated on the printer), 0x0B = die-cut label.
    const bool continuous = cfg.labelLength <= 0;
    const uint8_t mtype = continuous ? 0x0A : 0x0B;
    const uint8_t mwidth = (uint8_t)(cfg.labelWidth & 0xFF);
    const uint8_t mlength = continuous ? 0x00 : (uint8_t)(cfg.labelLength & 0xFF);
    const uint32_t rnumber = (uint32_t)g.targetHeightPx;
    const uint8_t cmd[13] = {
        0x1B, 0x69, 0x7A, // ESC i z
        // valid_flags: 0x80 | mtype<<1 | mwidth<<2 | mlength<<3 | pquality<<6
        // -- all three media fields plus high print quality are always
        // supplied, so every one of those bits is set.
        (uint8_t)(0x80 | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 6)),
        mtype,
        mwidth,
        mlength,
        (uint8_t)(rnumber & 0xFF),
        (uint8_t)((rnumber >> 8) & 0xFF),
        (uint8_t)((rnumber >> 16) & 0xFF),
        (uint8_t)((rnumber >> 24) & 0xFF),
        0x00, // page 0 (single-page job)
        0x00,
    };
    if (!targetStreamWrite(cmd, sizeof(cmd), err)) return false;
  }

  if (cfg.qlAutoCut) {
    const uint8_t autocut[4] = {0x1B, 0x69, 0x4D, 0x40}; // ESC i M, autocut on (bit 6)
    if (!targetStreamWrite(autocut, 4, err)) return false;
    const uint8_t cutEvery[4] = {0x1B, 0x69, 0x41, 0x01}; // ESC i A, cut every 1 label
    if (!targetStreamWrite(cutEvery, 4, err)) return false;
  }

  {
    // Expanded mode (ESC i K): cut_at_end mirrors autocut; 600dpi and
    // two-color printing aren't implemented by this firmware, so both bits
    // stay off.
    const uint8_t flags = cfg.qlAutoCut ? (1 << 3) : 0x00;
    const uint8_t expanded[4] = {0x1B, 0x69, 0x4B, flags};
    if (!targetStreamWrite(expanded, 4, err)) return false;
  }

  {
    const uint16_t feed = (uint16_t)cfg.qlFeedMarginDots;
    const uint8_t margins[5] = {0x1B, 0x69, 0x64, (uint8_t)(feed & 0xFF), (uint8_t)((feed >> 8) & 0xFF)};
    if (!targetStreamWrite(margins, 5, err)) return false;
  }

  // No compression command -- rows are always sent uncompressed (see file
  // header comment), which is accepted by every QL model regardless of
  // whether it also supports the optional PackBits compression mode.
  return true;
}

bool sendQlFooter(String& err) {
  const uint8_t print[1] = {0x1A}; // last page, EOF
  return targetStreamWrite(print, 1, err);
}

} // namespace

bool qlPrintPng(const uint8_t* pngData, size_t pngLen, String& err) {
  g = QlState();
  g.printheadPx = (cfg.qlPrintheadPx == 1296) ? 1296 : 720;
  g.rowBytes = g.printheadPx / 8;

  const int openRc = png.openRAM(const_cast<uint8_t*>(pngData), (int)pngLen, pngDrawCallback);
  if (openRc != PNG_SUCCESS) {
    err = "png decode failed to open (rc=" + String(openRc) + ")";
    return false;
  }

  g.srcWidth = png.getWidth();
  g.srcHeight = png.getHeight();
  if (g.srcWidth <= 0 || g.srcHeight <= 0) {
    png.close();
    err = "png has invalid dimensions";
    return false;
  }

  // Target geometry at the QL family's native 300dpi -- reuses the same
  // labelWidth/labelLength (mm) fields the zpl/ZPL path uses, rather than a
  // parallel set of "ql label size" config fields.
  const int nativeDpi = 300;
  g.targetWidthPx = max(1, (int)roundf((cfg.labelWidth / 25.4f) * nativeDpi));
  if (g.targetWidthPx > g.printheadPx) g.targetWidthPx = g.printheadPx;
  g.targetHeightPx = cfg.labelLength > 0
      ? max(1, (int)roundf((cfg.labelLength / 25.4f) * nativeDpi))
      : max(1, (int)roundf(((float)g.srcHeight / (float)g.srcWidth) * g.targetWidthPx));

  g.offsetPx = cfg.qlRightMarginDots > 0
      ? max(0, g.printheadPx - g.targetWidthPx - cfg.qlRightMarginDots)
      : (g.printheadPx - g.targetWidthPx) / 2;

  g.lineBuf = new (std::nothrow) uint16_t[g.srcWidth];
  if (g.lineBuf == nullptr) {
    png.close();
    err = "out of memory for png line buffer";
    return false;
  }

  dbgPrint("[ql] src=");
  dbgPrint(g.srcWidth);
  dbgPrint("x");
  dbgPrint(g.srcHeight);
  dbgPrint(" target=");
  dbgPrint(g.targetWidthPx);
  dbgPrint("x");
  dbgPrint(g.targetHeightPx);
  dbgPrint(" printheadPx=");
  dbgPrintln(g.printheadPx, LogLevel::LOG_INFO);

  String streamErr;
  if (!targetStreamBegin(streamErr)) {
    delete[] g.lineBuf;
    g.lineBuf = nullptr;
    png.close();
    err = streamErr;
    return false;
  }

  bool ok = sendQlHeader(streamErr);
  if (!ok) err = streamErr;

  if (ok) {
    const int decodeRc = png.decode(nullptr, 0);
    if (decodeRc != PNG_SUCCESS || g.failed) {
      ok = false;
      err = g.failed ? g.err : ("png decode error (rc=" + String(decodeRc) + ")");
    } else if (g.nextTargetRow != g.targetHeightPx) {
      ok = false;
      err = "raster line count mismatch: sent " + String(g.nextTargetRow) + " of " + String(g.targetHeightPx);
    }
  }

  if (ok) {
    ok = sendQlFooter(streamErr);
    if (!ok) err = streamErr;
  }

  targetStreamEnd();
  png.close();
  delete[] g.lineBuf;
  g.lineBuf = nullptr;
  return ok;
}

#endif // PROTOCOL_QL
