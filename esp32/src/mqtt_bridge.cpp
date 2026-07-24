#include "mqtt_bridge.h"

#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <mbedtls/base64.h>

#include <utility>

#include "config.h"
#include "logging.h"
#include "status_led.h"
#include "targets/network_target.h"

static WiFiClient mqttNet;
static WiFiClientSecure mqttNetSecure;
static PubSubClient mqtt(mqttNet);

static unsigned long lastMqttAttemptMs = 0;
static unsigned long lastStatusMs = 0;
static const int kNoMqttFailLogged = -1000; // outside PubSubClient's state() range (-4..5)
static int lastMqttFailState = kNoMqttFailLogged; // last mqtt.state() logged as an error, so retries every 5s during an outage don't flood the log ring buffer

// The frontend caps individual chunks at 8000 bytes specifically so this
// buffer (and everything downstream that copies a message-sized String --
// onMqttMessage's `msg`, extractJsonStringField's `out`) only ever needs to
// hold a few KB at a time instead of a full multi-KB image. Keeping this
// small also leaves far more free/contiguous heap for those copies -- a
// permanently-reserved 65535-byte buffer was crowding out the exact
// allocations needed to process what it received.
static const uint16_t MQTT_PACKET_BUFFER_SIZE = 16384;

static String imageChunkJobId;
static String imageChunkData;
static uint16_t imageChunkExpected = 0;
static uint16_t imageChunkReceived = 0;
static String zplChunkJobId;
static String zplChunkData;
static uint16_t zplChunkExpected = 0;
static uint16_t zplChunkReceived = 0;

static void resetImageChunkState() {
  imageChunkJobId = "";
  imageChunkData = "";
  imageChunkExpected = 0;
  imageChunkReceived = 0;
}

static void resetZplChunkState() {
  zplChunkJobId = "";
  zplChunkData = "";
  zplChunkExpected = 0;
  zplChunkReceived = 0;
}

String normalizeMqttHost(const String& raw) {
  String host = raw;
  host.trim();

  if (host.startsWith("mqtt://")) host = host.substring(7);
  if (host.startsWith("mqtts://")) host = host.substring(8);
  if (host.startsWith("ws://")) host = host.substring(5);
  if (host.startsWith("wss://")) host = host.substring(6);

  const int slash = host.indexOf('/');
  if (slash >= 0) host = host.substring(0, slash);
  return host;
}

String commandTopic() {
  return String("/") + cfg.printerName + "/command/";
}

String statusTopic() {
  return String("/") + cfg.printerName + "/status/";
}

bool mqttIsConnected() {
  return mqtt.connected();
}

static String extractJsonStringField(const String& json, const char* key) {
  const String marker = String("\"") + key + "\":\"";
  const int start = json.indexOf(marker);
  if (start < 0) return "";

  int i = start + marker.length();
  String out;
  // Reserve the whole remaining span up front: escape sequences only ever
  // shrink the decoded length, never grow it, so this is a safe upper
  // bound. Growing this incrementally via out += c in the loop below used
  // to silently truncate large payloads (String::operator+= swallows a
  // failed realloc with no error) once the heap got fragmented enough that
  // no single bigger contiguous block was available -- exactly the kind of
  // thing a 65535-byte MQTT buffer plus WiFi/TLS overhead can cause.
  out.reserve((size_t)(json.length() - i));
  while (i < (int)json.length()) {
    const char c = json[i++];
    if (c == '\\') {
      if (i >= (int)json.length()) break;
      const char esc = json[i++];
      switch (esc) {
        case 'n': out += '\n'; break;
        case 't': out += '\t'; break;
        case 'r': out += '\r'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case '"': out += '"'; break;
        case '\\': out += '\\'; break;
        case '/': out += '/'; break;
        default: out += esc; break; // \uXXXX not expected in ZPL/base64 payloads
      }
      continue;
    }
    if (c == '"') {
      return out;
    }
    out += c;
  }

  return "";
}

static bool decodeBase64Payload(const String& in, std::unique_ptr<uint8_t[]>& out, size_t& outLen, String& err) {
  size_t needed = 0;
  int rc = mbedtls_base64_decode(nullptr, 0, &needed,
                                 reinterpret_cast<const unsigned char*>(in.c_str()),
                                 in.length());
  if (rc != MBEDTLS_ERR_BASE64_BUFFER_TOO_SMALL && rc != 0) {
    err = "invalid base64 payload";
    return false;
  }

  out.reset(new uint8_t[needed]);
  rc = mbedtls_base64_decode(out.get(), needed, &outLen,
                             reinterpret_cast<const unsigned char*>(in.c_str()),
                             in.length());
  if (rc != 0) {
    err = "base64 decode failed";
    return false;
  }

  return true;
}

static String buildStatusJson(const char* phase, const char* lastError) {
  JsonDocument doc;
  doc["printer_name"] = cfg.printerName;
  doc["name"] = cfg.printerName;
  doc["online"] = true;
  doc["busy"] = String(phase) == "printing";
  doc["phase"] = phase;
  doc["type"] = cfg.printerType;
  doc["serial"] = String((uint32_t)ESP.getEfuseMac(), HEX);
  doc["dpi"] = cfg.dpi;
  doc["last_error"] = lastError;

  JsonObject label = doc["label"].to<JsonObject>();
  label["width"] = cfg.labelWidth;
  label["length"] = cfg.labelLength;
  label["isRound"] = false;
  label["verticalOffset"] = 0;
  label["cut"] = false;

  JsonObject capabilities = doc["capabilities"].to<JsonObject>();
  capabilities["type"] = cfg.printerType;
  capabilities["dpi"] = cfg.dpi;
  capabilities["zplCompression"] = cfg.zplCompressionSupported;
  JsonObject capLabel = capabilities["label"].to<JsonObject>();
  capLabel["width"] = cfg.labelWidth;
  capLabel["length"] = cfg.labelLength;
  capLabel["isRound"] = false;
  capLabel["verticalOffset"] = 0;
  capLabel["cut"] = false;

  String out;
  serializeJson(doc, out);
  return out;
}

void publishStatus(const char* phase, const char* lastError) {
  if (!mqtt.connected()) return;
  markLedEvent(LedEventType::tx);
  const String payload = buildStatusJson(phase, lastError);
  dbgPrint("[mqtt] publish status -> ");
  dbgPrintln(statusTopic());
  dbgPrint("[mqtt] payload bytes: ");
  dbgPrintln(payload.length());
  dbgPrint("[mqtt] payload: ");
  dbgPrintln(shortenForLog(payload));
  const bool ok = mqtt.publish(statusTopic().c_str(), payload.c_str(), true);
  if (!ok) {
    dbgPrint("[mqtt] publish status failed, state=");
    dbgPrintln(mqtt.state(), LogLevel::LOG_WARN);
  }
}

static void publishJobStatus(const char* jobId, const char* status, const char* message) {
  if (!mqtt.connected()) return;
  markLedEvent(LedEventType::tx);

  JsonDocument doc;
  doc["printer_name"] = cfg.printerName;
  doc["job_id"] = jobId;
  doc["status"] = status;
  doc["message"] = message;

  String payload;
  serializeJson(doc, payload);
  dbgPrint("[mqtt] publish job status -> ");
  dbgPrintln(statusTopic());
  dbgPrint("[mqtt] payload bytes: ");
  dbgPrintln(payload.length());
  dbgPrint("[mqtt] payload: ");
  dbgPrintln(shortenForLog(payload));
  const bool ok = mqtt.publish(statusTopic().c_str(), payload.c_str(), false);
  if (!ok) {
    dbgPrint("[mqtt] publish job status failed, state=");
    dbgPrintln(mqtt.state(), LogLevel::LOG_WARN);
  }
}

static void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String incomingTopic(topic);
  if (incomingTopic != commandTopic()) return;
  markLedEvent(LedEventType::rx);

  String msg;
  if (!msg.reserve(length + 1)) {
    dbgPrint("[mqtt] out of memory reserving ");
    dbgPrint(length + 1);
    dbgPrintln(" bytes for incoming message", LogLevel::LOG_ERROR);
    publishJobStatus("", "failed", "esp32 out of memory for incoming message");
    publishStatus("error", "out of memory");
    return;
  }
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  dbgPrint("[mqtt] recv <- ");
  dbgPrintln(incomingTopic);
  dbgPrint("[mqtt] payload bytes: ");
  dbgPrintln(length);
  dbgPrint("[mqtt] payload: ");
  dbgPrintln(shortenForLog(msg));

  // The "payload" field can be tens of KB (a full ZPL/image body). Filter it out of the
  // parse so ArduinoJson never has to duplicate it into the JsonDocument's memory pool --
  // it's pulled out separately below via extractJsonStringField(). Without this filter,
  // deserializeJson() ran out of heap on payloads well under the 65535-byte MQTT ceiling.
  JsonDocument filter;
  filter["job_id"] = true;
  filter["payload_type"] = true;
  filter["payload_encoding"] = true;
  filter["chunk_index"] = true;
  filter["chunks_total"] = true;

  JsonDocument doc;
  const auto err = deserializeJson(doc, msg, DeserializationOption::Filter(filter));
  if (err) {
    dbgPrint("[mqtt] JSON parse error: ");
    dbgPrintln(err.c_str(), LogLevel::LOG_ERROR);
    publishJobStatus("", "failed", err.c_str());
    return;
  }

  const char* jobId = doc["job_id"] | "";
  const char* payloadType = doc["payload_type"] | "";
  const char* payloadEncoding = doc["payload_encoding"] | "";
  // "payload" is filtered out of doc above, so it must come from the raw string.
  // Non-const so it can be std::move()'d below instead of deep-copied -- for large
  // (tens-of-KB) bodies, a second copy on top of msg/body was enough to blow the heap,
  // and Arduino String's operator= silently leaves the destination empty on malloc failure.
  String body = extractJsonStringField(msg, "payload");

  dbgPrint("[mqtt] parsed payload bytes=");
  dbgPrintln(body.length());

  dbgPrint("[mqtt] command type=");
  dbgPrint(payloadType);
  dbgPrint(", encoding=");
  dbgPrintln(payloadEncoding);

  publishStatus("printing", "");
  publishJobStatus(jobId, "accepted", "job accepted");

  if (String(payloadType) == "zpl") {
    dbgPrint("[zpl] command received, encoding=");
    dbgPrintln(payloadEncoding);
    String zplBody;
    bool zplIsBase64 = false;
    if (String(payloadEncoding) == "utf8_chunk" || String(payloadEncoding) == "base64_utf8_chunk") {
      const int chunkIndex = doc["chunk_index"] | -1;
      const int chunksTotal = doc["chunks_total"] | 0;
      if (chunkIndex < 0 || chunksTotal <= 0) {
        dbgPrintln("[zpl] invalid chunk metadata", LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "invalid chunk metadata");
        publishStatus("error", "invalid chunk metadata");
        resetZplChunkState();
        return;
      }

      const String chunk = std::move(body);
      if (chunkIndex == 0 || zplChunkJobId != String(jobId)) {
        dbgPrintln("[zpl] job start jobId=" + String(jobId) + " chunks=" + String(chunksTotal), LogLevel::LOG_INFO);
        resetZplChunkState();
        zplChunkJobId = String(jobId);
        zplChunkExpected = (uint16_t)chunksTotal;
        const size_t neededBytes = (size_t)chunksTotal * (size_t)chunk.length();
        if (!zplChunkData.reserve(neededBytes)) {
          dbgPrint("[zpl] out of memory reserving ");
          dbgPrint((unsigned long)neededBytes);
          dbgPrintln(" bytes for chunk reassembly", LogLevel::LOG_ERROR);
          publishJobStatus(jobId, "failed", "esp32 out of memory for zpl reassembly");
          publishStatus("error", "out of memory");
          resetZplChunkState();
          return;
        }
      }

      if (zplChunkExpected != (uint16_t)chunksTotal) {
        dbgPrintln("[zpl] chunk total mismatch", LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "chunk total mismatch");
        publishStatus("error", "chunk total mismatch");
        resetZplChunkState();
        return;
      }

      if ((int)zplChunkReceived != chunkIndex) {
        dbgPrintln("[zpl] chunk order mismatch", LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "chunk order mismatch");
        publishStatus("error", "chunk order mismatch");
        resetZplChunkState();
        return;
      }

      zplChunkData += chunk;
      zplChunkReceived++;

      dbgPrint("[mqtt] zpl chunk ");
      dbgPrint(chunkIndex + 1);
      dbgPrint("/");
      dbgPrintln(chunksTotal);

      if (zplChunkReceived < zplChunkExpected) {
        publishJobStatus(jobId, "accepted", "zpl chunk received");
        return;
      }

      // std::move avoids a second same-size allocation -- a plain copy here
      // needs zplChunkData's buffer AND a same-size zplBody buffer alive at
      // once, which can silently fail (Arduino String::operator= leaves the
      // destination empty on a failed malloc, no error surfaced) once a
      // large reassembled body plus the MQTT/TLS buffers have used up most
      // of the heap.
      zplBody = std::move(zplChunkData);
      zplIsBase64 = String(payloadEncoding) == "base64_utf8_chunk";
      dbgPrint("[zpl] all chunks received, bytes=");
      dbgPrintln(zplBody.length());
      resetZplChunkState();
    } else if (String(payloadEncoding) == "utf8" || String(payloadEncoding) == "base64_utf8") {
      dbgPrintln("[zpl] job start jobId=" + String(jobId) + " (single message)", LogLevel::LOG_INFO);
      zplBody = std::move(body);
      zplIsBase64 = String(payloadEncoding) == "base64_utf8";
    } else {
      dbgPrintln("[zpl] unsupported payload_encoding: " + String(payloadEncoding), LogLevel::LOG_ERROR);
      publishJobStatus(jobId, "failed", "payload_encoding must be utf8/utf8_chunk/base64_utf8/base64_utf8_chunk for zpl");
      publishStatus("error", "payload_encoding must be utf8/utf8_chunk/base64_utf8/base64_utf8_chunk for zpl");
      return;
    }

    String sendErr;
    bool ok = false;
    if (zplIsBase64) {
      dbgPrint("[zpl] decoding base64 bytes=");
      dbgPrintln(zplBody.length());
      std::unique_ptr<uint8_t[]> bytes;
      size_t decodedLen = 0;
      String decodeErr;
      if (!decodeBase64Payload(zplBody, bytes, decodedLen, decodeErr)) {
        dbgPrintln("[zpl] decode failed: " + decodeErr, LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", decodeErr.c_str());
        publishStatus("error", decodeErr.c_str());
        return;
      }
      dbgPrint("[zpl] sending decoded bytes=");
      dbgPrintln(decodedLen);
      dbgPrintln("[zpl] ---- ZPL BODY (head/tail) ----");
      dbgPrintHeadTailBytes(bytes.get(), decodedLen);
      dbgPrintln("[zpl] ---- ZPL BODY END ----");
      ok = networkTargetSend(bytes.get(), decodedLen, sendErr);
    } else {
      dbgPrint("[zpl] sending utf8 bytes=");
      dbgPrintln(zplBody.length());
      dbgPrintln("[zpl] ---- ZPL BODY (head/tail) ----");
      dbgPrintHeadTail(zplBody);
      dbgPrintln("[zpl] ---- ZPL BODY END ----");
      ok = networkTargetSendString(zplBody, sendErr);
    }
    if (!ok) {
      dbgPrint("[zpl] send failed: ");
      dbgPrintln(sendErr, LogLevel::LOG_ERROR);
      publishJobStatus(jobId, "failed", sendErr.c_str());
      publishStatus("error", sendErr.c_str());
      return;
    }

    dbgPrintln("[zpl] job sent to target successfully", LogLevel::LOG_INFO);
    publishJobStatus(jobId, "done", "zpl sent");
    publishStatus("ready", "");
    return;
  }

  if (String(payloadType) == "image") {
    dbgPrint("[image] command received, encoding=");
    dbgPrintln(payloadEncoding);
    String encoded;
    if (String(payloadEncoding) == "base64_chunk") {
      const int chunkIndex = doc["chunk_index"] | -1;
      const int chunksTotal = doc["chunks_total"] | 0;
      if (chunkIndex < 0 || chunksTotal <= 0) {
        dbgPrintln("[image] invalid chunk metadata", LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "invalid chunk metadata");
        publishStatus("error", "invalid chunk metadata");
        resetImageChunkState();
        return;
      }

      const String chunk = std::move(body);
      if (chunkIndex == 0 || imageChunkJobId != String(jobId)) {
        dbgPrintln("[image] job start jobId=" + String(jobId) + " chunks=" + String(chunksTotal), LogLevel::LOG_INFO);
        resetImageChunkState();
        imageChunkJobId = String(jobId);
        imageChunkExpected = (uint16_t)chunksTotal;
        const size_t neededBytes = (size_t)chunksTotal * (size_t)chunk.length();
        if (!imageChunkData.reserve(neededBytes)) {
          dbgPrint("[image] out of memory reserving ");
          dbgPrint((unsigned long)neededBytes);
          dbgPrintln(" bytes for chunk reassembly", LogLevel::LOG_ERROR);
          publishJobStatus(jobId, "failed", "esp32 out of memory for image reassembly");
          publishStatus("error", "out of memory");
          resetImageChunkState();
          return;
        }
      }

      if (imageChunkExpected != (uint16_t)chunksTotal) {
        dbgPrintln("[image] chunk total mismatch", LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "chunk total mismatch");
        publishStatus("error", "chunk total mismatch");
        resetImageChunkState();
        return;
      }

      if ((int)imageChunkReceived != chunkIndex) {
        dbgPrintln("[image] chunk order mismatch", LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "chunk order mismatch");
        publishStatus("error", "chunk order mismatch");
        resetImageChunkState();
        return;
      }

      imageChunkData += chunk;
      imageChunkReceived++;

      dbgPrint("[mqtt] image chunk ");
      dbgPrint(chunkIndex + 1);
      dbgPrint("/");
      dbgPrintln(chunksTotal);

      if (imageChunkReceived < imageChunkExpected) {
        publishJobStatus(jobId, "accepted", "image chunk received");
        return;
      }

      // std::move avoids a second same-size allocation -- see the matching
      // zplBody move above for why a plain copy here can silently empty out
      // under heap pressure.
      encoded = std::move(imageChunkData);
      dbgPrint("[image] all chunks received, base64 bytes=");
      dbgPrintln(encoded.length());
      resetImageChunkState();
    } else {
      dbgPrintln("[image] job start jobId=" + String(jobId) + " (single message)", LogLevel::LOG_INFO);
      encoded = std::move(body);
      if (String(payloadEncoding) == "data_url") {
        const int comma = encoded.indexOf(',');
        if (comma < 0) {
          dbgPrintln("[image] invalid data_url payload", LogLevel::LOG_ERROR);
          publishJobStatus(jobId, "failed", "invalid data_url payload");
          publishStatus("error", "invalid data_url payload");
          return;
        }
        encoded = encoded.substring(comma + 1);
      } else if (String(payloadEncoding) != "base64_png") {
        dbgPrintln("[image] unsupported payload_encoding: " + String(payloadEncoding), LogLevel::LOG_ERROR);
        publishJobStatus(jobId, "failed", "unsupported image payload_encoding");
        publishStatus("error", "unsupported image payload_encoding");
        return;
      }
    }

    std::unique_ptr<uint8_t[]> bytes;
    size_t decodedLen = 0;
    String decodeErr;
    dbgPrint("[image] decoding base64 bytes=");
    dbgPrintln(encoded.length());
    if (!decodeBase64Payload(encoded, bytes, decodedLen, decodeErr)) {
      dbgPrint("[image] decode failed: ");
      dbgPrintln(decodeErr, LogLevel::LOG_ERROR);
      publishJobStatus(jobId, "failed", decodeErr.c_str());
      publishStatus("error", decodeErr.c_str());
      return;
    }

    dbgPrint("[image] decoded bytes=");
    dbgPrintln(decodedLen);
    dbgPrintln("[image] sending decoded image to target");
    String sendErr;
    if (!networkTargetSend(bytes.get(), decodedLen, sendErr)) {
      dbgPrint("[image] send failed: ");
      dbgPrintln(sendErr, LogLevel::LOG_ERROR);
      publishJobStatus(jobId, "failed", sendErr.c_str());
      publishStatus("error", sendErr.c_str());
      return;
    }

    dbgPrintln("[image] job sent to target successfully", LogLevel::LOG_INFO);
    publishJobStatus(jobId, "done", "image bytes sent");
    publishStatus("ready", "");
    return;
  }

  dbgPrintln("[mqtt] unsupported payload_type: " + String(payloadType), LogLevel::LOG_ERROR);
  publishJobStatus(jobId, "failed", "unsupported payload_type");
  publishStatus("error", "unsupported payload_type");
}

static void connectMqtt() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (cfg.mqttHost.isEmpty()) return;
  if (mqtt.connected()) return;

  const unsigned long now = millis();
  if (now - lastMqttAttemptMs < 5000) return;
  lastMqttAttemptMs = now;

  const String mqttHost = normalizeMqttHost(cfg.mqttHost);
  if (mqttHost.isEmpty()) return;

  dbgPrint("[mqtt] connecting to ");
  dbgPrint(mqttHost);
  dbgPrint(":");
  dbgPrint(cfg.mqttPort);
  dbgPrint(" tls=");
  dbgPrintln(cfg.mqttUseTls ? "on" : "off", LogLevel::LOG_INFO);

  if (cfg.mqttUseTls) {
    if (cfg.mqttTlsInsecure || cfg.mqttCaCert.isEmpty()) {
      mqttNetSecure.setInsecure();
      dbgPrintln("[mqtt] tls insecure mode enabled", LogLevel::LOG_WARN);
    } else {
      mqttNetSecure.setCACert(cfg.mqttCaCert.c_str());
      dbgPrintln("[mqtt] tls CA certificate configured", LogLevel::LOG_INFO);
    }
    mqttNetSecure.setHandshakeTimeout(12);
    mqtt.setClient(mqttNetSecure);
  } else {
    mqtt.setClient(mqttNet);
  }

  mqtt.setServer(mqttHost.c_str(), cfg.mqttPort);
  mqtt.setCallback(onMqttMessage);

  // PubSubClient::setBufferSize() reallocs a single contiguous block; on a
  // fragmented heap (WiFi + TLS already hold a lot of it) even this request
  // can fail. If it does, fall back to the largest size that does allocate
  // instead of silently keeping whatever (possibly tiny) buffer was already
  // in place -- any inbound packet bigger than the buffer is read off the
  // socket and then dropped without ever reaching the callback, which
  // otherwise looks just like a message vanishing. The floor here (10240)
  // is still comfortably above one 8000-byte frontend chunk plus its JSON/
  // MQTT wrapper overhead.
  static const uint16_t kBufferFallbacks[] = {
    MQTT_PACKET_BUFFER_SIZE, 14336, 12288, 10240,
  };
  bool bufferOk = false;
  for (uint16_t candidate : kBufferFallbacks) {
    if (mqtt.setBufferSize(candidate)) {
      bufferOk = true;
      break;
    }
  }
  dbgPrint("[mqtt] mqtt buffer size -> ");
  dbgPrint(mqtt.getBufferSize());
  dbgPrintln(bufferOk ? " (ok)" : " (all allocations failed)", bufferOk ? LogLevel::LOG_DEBUG : LogLevel::LOG_WARN);

  const String clientId = cfg.printerName + "-bridge";
  bool connected;
  if (cfg.mqttUser.isEmpty()) {
    connected = mqtt.connect(clientId.c_str());
  } else {
    connected = mqtt.connect(clientId.c_str(), cfg.mqttUser.c_str(), cfg.mqttPassword.c_str());
  }

  if (!connected) {
    const int state = mqtt.state();
    // Retried every 5s by the caller -- only log a given failure state once,
    // otherwise a sustained broker outage floods the ring buffer with
    // identical ERROR lines and evicts everything else within minutes.
    if (state != lastMqttFailState) {
      dbgPrint("[mqtt] connect failed, state=");
      dbgPrintln(state, LogLevel::LOG_ERROR);
      lastMqttFailState = state;
    }
    return;
  }

  lastMqttFailState = kNoMqttFailLogged;
  dbgPrintln("[mqtt] connected", LogLevel::LOG_INFO);
  dbgPrint("[mqtt] packet buffer size: ");
  dbgPrintln(MQTT_PACKET_BUFFER_SIZE);

  if (mqtt.subscribe(commandTopic().c_str(), 1)) {
    dbgPrint("[mqtt] subscribed to ");
    dbgPrintln(commandTopic(), LogLevel::LOG_INFO);
  } else {
    dbgPrint("[mqtt] subscribe failed for ");
    dbgPrintln(commandTopic(), LogLevel::LOG_ERROR);
  }
  publishStatus("ready", "");
}

void mqttBridgeLoop() {
  connectMqtt();
  if (!mqtt.connected()) return;

  mqtt.loop();
  const unsigned long now = millis();
  const unsigned long intervalMs = (unsigned long)cfg.statusIntervalSec * 1000UL;
  if (now - lastStatusMs > intervalMs) {
    publishStatus("ready", "");
    lastStatusMs = now;
  }
}
