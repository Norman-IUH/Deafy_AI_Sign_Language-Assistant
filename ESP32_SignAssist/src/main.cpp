#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ESPmDNS.h>
#include <mbedtls/md.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <sys/time.h>
#include <driver/i2s.h>
#include <freertos/stream_buffer.h>
#include <SPIFFS.h>
#include <esp_partition.h>
#include <atomic>
#include "pcm_stereo.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif
#ifndef DISCOVERY_ENABLED
#define DISCOVERY_ENABLED 0
#endif

WiFiClient transport;
PubSubClient mqtt(transport);
String epoch, mode, speechId, speechEpoch;
String lastIds[32], lastReplies[32];
unsigned cacheSlot = 0;
unsigned long retryAt = 0;
unsigned long retryDelay = 2000, wifiRetryAt = 0, wifiRetryDelay = 15000;
unsigned long mqttConnectedAt = 0;
bool playing = false;
std::atomic<bool> cancelAudio{false};
struct AudioJob { char url[512]; };
struct AudioEvent { bool started; const char *error; };
QueueHandle_t audioJobs = nullptr, audioEvents = nullptr;
String brokerHost = MQTT_HOST, audioBase = AUDIO_BASE_URL;
uint16_t brokerPort = MQTT_PORT;
bool mdnsStarted = false;
IPAddress wifiAddress;

bool privateAddress(IPAddress ip) {
  return ip[0] == 10 || (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31) ||
    (ip[0] == 192 && ip[1] == 168);
}

bool verifyPi(IPAddress ip, uint16_t httpPort) {
  if (!privateAddress(ip) || !httpPort || !strlen(MQTT_PASSWORD)) return false;
  String origin = "http://" + ip.toString() + ":" + String(httpPort);
  char nonce[33];
  for (int i = 0; i < 4; ++i) snprintf(nonce + i * 8, 9, "%08lx", (unsigned long)esp_random());
  WiFiClient probeClient;
  HTTPClient probe;
  probe.setConnectTimeout(1000); probe.setTimeout(1500);
  bool ok = probe.begin(probeClient, origin + "/api/discovery?kind=mqtt&challenge=" + nonce) && probe.GET() == 200;
  StaticJsonDocument<768> data;
  if (ok) ok = probe.getSize() > 0 && probe.getSize() < 768 && !deserializeJson(data, probe.getString());
  probe.end();
  int port = data["mqtt_port"] | 0;
  if (!ok || String(data["service"] | "") != "DAKT-Nc" || String(data["origin"] | "") != origin || port < 1 || port > 65535) return false;
  String message = "deafy-discovery-v1\nmqtt\n" + String(nonce) + "\n" + origin + "\n" + String(port);
  unsigned char digest[32];
  if (mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
      (const unsigned char *)MQTT_PASSWORD, strlen(MQTT_PASSWORD),
      (const unsigned char *)message.c_str(), message.length(), digest)) return false;
  char expected[65];
  for (int i = 0; i < 32; ++i) snprintf(expected + 2 * i, 3, "%02x", digest[i]);
  String proof = data["proof"] | "";
  if (proof.length() != 64) return false;
  unsigned difference = 0;
  for (int i = 0; i < 64; ++i) difference |= proof[i] ^ expected[i];
  if (difference) return false;
  brokerHost = ip.toString(); brokerPort = port; audioBase = origin;
  mqtt.setServer(brokerHost.c_str(), brokerPort);
  Serial.printf("Pi discovered and verified: %s HTTP %u MQTT %u\n", brokerHost.c_str(), httpPort, brokerPort);
  return true;
}

bool discoverPi() {
  if (!mdnsStarted) {
    mdnsStarted = MDNS.begin("signassist-" + String(uint32_t(ESP.getEfuseMac()), HEX));
    if (!mdnsStarted) return false;
  }
  int found = MDNS.queryService("deafy", "tcp");
  for (int i = 0; i < found && i < 8; ++i) {
    if (MDNS.txt(i, "app") == "DAKT-Nc" && verifyPi(MDNS.IP(i), MDNS.port(i))) return true;
  }
  return false;
}
time_t lastModeTime = 0;
uint64_t lastModeStamp = 0;
String lastModeEpoch;

void status(const String &kind, const String &id, const String &session,
            const String &state, const String &error = "", const String &device = "", bool value = false) {
  StaticJsonDocument<512> packet;
  packet["kind"] = kind; packet["request_id"] = id; packet["epoch"] = session;
  packet["mode"] = kind == "iot" ? "iot" : "ai";
  packet["status"] = state; packet["error"] = error;
  if (device.length()) { packet["device"] = device; packet["value"] = value; }
  String body; serializeJson(packet, body);
  mqtt.publish((String(MQTT_TOPIC) + "/status").c_str(), body.c_str(), false);
  if (state == "DONE" || state == "ERROR") {
    lastIds[cacheSlot] = session + ":" + id;
    lastReplies[cacheSlot] = body;
    cacheSlot = (cacheSlot + 1) % 32;
  }
}

void received(char *topic, byte *payload, unsigned int length) {
  if (length > 1536) return;
  StaticJsonDocument<2048> packet;
  if (deserializeJson(packet, payload, length)) return;
  const String route(topic), prefix = String(MQTT_TOPIC);
  if (route == prefix + "/mode") {
    String nextMode = packet["mode"] | "";
    String nextEpoch = packet["epoch"] | "";
    time_t issued = packet["issued_at"] | 0L;
    uint64_t stamp = packet["mode_stamp"] | uint64_t(0);
    bool fresh = stamp > lastModeStamp || (stamp == lastModeStamp && nextEpoch == lastModeEpoch);
    if ((nextMode == "iot" || nextMode == "ai") && nextEpoch.length() == 32 && issued >= 1700000000 && issued >= lastModeTime && fresh) {
      // The authenticated local broker carries Pi time, so IoT also works without Internet/NTP.
      struct timeval clock = {issued, 0}; settimeofday(&clock, nullptr); lastModeTime = issued;
      lastModeStamp = stamp; lastModeEpoch = nextEpoch;
      if (nextEpoch != epoch && playing) cancelAudio = true;
      epoch = nextEpoch; mode = nextMode;
    }
    return;
  }
  String kind = route == prefix + "/command" ? "iot" : route == prefix + "/speech" ? "speech" : "";
  if (!kind.length()) return;
  const String id = packet["request_id"] | "", session = packet["epoch"] | "";
  if (id.length() < 8 || id.length() > 80 || session != epoch || !epoch.length()) return;
  for (unsigned i = 0; i < 32; ++i) {
    if (lastIds[i] == session + ":" + id) {
      mqtt.publish((prefix + "/status").c_str(), lastReplies[i].c_str(), false); return;
    }
  }
  if (kind == "speech" && playing && id == speechId && session == speechEpoch) return;
  const time_t now = time(nullptr), issued = packet["issued_at"] | 0L, expires = packet["expires_at"] | 0L;
  if (now < 1700000000 || issued > now + 2 || expires < now || expires - issued > 10 || expires <= issued) {
    status(kind, id, session, "ERROR", "CLOCK_OR_EXPIRED"); return;
  }
  if ((kind == "iot" && mode != "iot") || (kind == "speech" && mode != "ai") || String(packet["mode"] | "") != mode) {
    status(kind, id, session, "ERROR", "WRONG_MODE"); return;
  }
  if (kind == "iot") {
    String device = packet["device"] | "";
    int pin = device == "light" ? LIGHT_PIN : device == "fan" ? FAN_PIN : -1;
    if (pin < 0 || !packet["value"].is<bool>()) { status(kind, id, session, "ERROR", "RELAY_NOT_CONFIGURED"); return; }
    bool value = packet["value"];
    status(kind, id, session, "ACK");
    digitalWrite(pin, value ? RELAY_ON : RELAY_OFF);
    bool actual = digitalRead(pin) == RELAY_ON;
    status(kind, id, session, actual == value ? "DONE" : "ERROR", actual == value ? "" : "GPIO_WRITE_FAILED", device, actual);
    return;
  }
  if (playing) {
    status(kind, id, session, "ERROR", "AUDIO_BUSY"); return;
  }
#if AUDIO_ENABLED
  String url = packet["audio_url"] | "";
  if (I2S_BCLK < 0 || I2S_LRC < 0 || I2S_DOUT < 0 || !audioBase.startsWith("http://") ||
      !url.startsWith(audioBase + "/api/pi/audio/")) {
    status(kind, id, session, "ERROR", "AUDIO_NOT_CONFIGURED"); return;
  }
  AudioJob job{};
  if (!audioJobs || url.length() >= sizeof(job.url)) {
    status(kind, id, session, "ERROR", "AUDIO_NOT_CONFIGURED"); return;
  }
  url.toCharArray(job.url, sizeof(job.url));
  cancelAudio = false;
  if (xQueueSend(audioJobs, &job, 0) != pdTRUE) {
    status(kind, id, session, "ERROR", "AUDIO_BUSY"); return;
  }
  speechId = id; speechEpoch = session; playing = true;
  status(kind, id, session, "ACK");
#else
  status(kind, id, session, "ERROR", "AUDIO_NOT_CONFIGURED");
#endif
}

#if AUDIO_ENABLED
bool readAudio(WiFiClient &stream, uint8_t *buffer, size_t length, unsigned long started) {
  auto lastByte = millis();
  while (length && !cancelAudio && millis() - started < 110000) {
    int available = stream.available();
    if (available > 0) {
      int count = stream.read(buffer, min(length, size_t(available)));
      if (count > 0) { buffer += count; length -= count; lastByte = millis(); continue; }
    }
    if (!stream.connected() || millis() - lastByte >= 3000) break;
    delay(2);
  }
  return length == 0 && !cancelAudio;
}

struct AudioDownload {
  AudioDownload(WiFiClient &input, StreamBufferHandle_t buffer, uint32_t length, unsigned long time)
    : stream(input), queue(buffer), remaining(length), started(time) {}
  WiFiClient &stream;
  StreamBufferHandle_t queue;
  uint32_t remaining;
  unsigned long started;
  std::atomic<bool> stop{false}, finished{false};
  uint32_t received = 0, longestRead = 0;
};

struct AudioWifiWake {
  const wifi_ps_type_t previous = WiFi.getSleep();
  const bool awake = previous == WIFI_PS_NONE || WiFi.setSleep(WIFI_PS_NONE);
  ~AudioWifiWake() {
    if (awake && previous != WIFI_PS_NONE) WiFi.setSleep(previous);
  }
};

void downloadAudio(void *argument) {
  auto &job = *static_cast<AudioDownload *>(argument);
  uint8_t bytes[1024];
  while (job.remaining && !job.stop && !cancelAudio) {
    const size_t count = min(size_t(job.remaining), sizeof(bytes));
    const auto before = millis();
    if (!readAudio(job.stream, bytes, count, job.started)) break;
    job.longestRead = max(job.longestRead, uint32_t(millis() - before));
    job.remaining -= count;
    job.received += count;
    size_t offset = 0;
    while (offset < count && !job.stop && !cancelAudio)
      offset += xStreamBufferSend(job.queue, bytes + offset, count - offset, pdMS_TO_TICKS(20));
  }
  job.finished = true;
  vTaskDelete(nullptr);
}

bool mountAudioCache() {
  static const bool mounted = []() {
    if (SPIFFS.begin(false)) return true;
    const auto *partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA,
                                                     ESP_PARTITION_SUBTYPE_DATA_SPIFFS, "spiffs");
    uint8_t page[512];
    if (!partition) return false;
    for (size_t offset = 0; offset < partition->size; offset += sizeof(page)) {
      if (esp_partition_read(partition, offset, page, sizeof(page)) != ESP_OK) return false;
      for (auto value : page) if (value != 0xff) return false;
    }
    return SPIFFS.begin(true);
  }();
  return mounted;
}

struct AudioCache {
  static constexpr const char *path = "/.deafy-pcm.tmp";
  uint8_t *memory = nullptr;
  File file;
  bool ownsFile = false;
  uint32_t received = 0, longestRead = 0;

  ~AudioCache() {
    file.close();
    if (ownsFile) SPIFFS.remove(path);
    free(memory);
  }

  const char *stage(WiFiClient &stream, uint32_t total, unsigned long started) {
    if (total <= 96 * 1024) memory = static_cast<uint8_t *>(malloc(total));
    if (!memory) {
      if (!mountAudioCache()) return "AUDIO_CACHE";
      if (SPIFFS.exists(path) && !SPIFFS.remove(path)) return "AUDIO_CACHE";
      if (SPIFFS.totalBytes() - SPIFFS.usedBytes() < total + 64 * 1024) return "AUDIO_CACHE";
      file = SPIFFS.open(path, FILE_WRITE);
      if (!file) return "AUDIO_CACHE";
      ownsFile = true;
    }
    uint8_t bytes[2048];
    while (received < total) {
      const size_t count = min(size_t(total - received), sizeof(bytes));
      const auto before = millis();
      if (!readAudio(stream, memory ? memory + received : bytes, count, started)) return "AUDIO_STREAM";
      longestRead = max(longestRead, uint32_t(millis() - before));
      if (!memory && file.write(bytes, count) != count) return "AUDIO_CACHE";
      received += count;
    }
    if (!memory) {
      file.close();
      file = SPIFFS.open(path, FILE_READ);
      if (!file || file.size() != total) return "AUDIO_CACHE";
    }
    return nullptr;
  }

  size_t read(uint8_t *bytes, size_t count, uint32_t offset) {
    if (!memory) return file.read(bytes, count);
    memcpy(bytes, memory + offset, count);
    return count;
  }
};

const char *playAudio(const char *url) {
  const auto started = millis();
  // A sleeping station can leave multiple audio chunks queued at the hotspot.
  AudioWifiWake wifi;
  Serial.printf("Audio wifi_ps_before=%d awake=%d\n", int(wifi.previous), wifi.awake);
  WiFiClient audioClient;
  HTTPClient http;
  http.setConnectTimeout(3000); http.setTimeout(3000);
  http.useHTTP10(true);
  if (cancelAudio || !http.begin(audioClient, url)) return "AUDIO_HTTP";
  int httpCode = http.GET();
  if ((httpCode < 0 || httpCode >= 500) && !cancelAudio) {
    Serial.printf("Audio HTTP retry code=%d\n", httpCode);
    http.end();
    delay(120);
    if (cancelAudio || !http.begin(audioClient, url)) return "AUDIO_HTTP";
    httpCode = http.GET();
  }
  if (httpCode != 200) {
    Serial.printf("Audio HTTP failed code=%d\n", httpCode);
    return "AUDIO_HTTP";
  }
  uint8_t header[44] = {};
  WiFiClient *stream = http.getStreamPtr();
  if (!stream || http.getSize() <= 44 || http.getSize() > 8000000) return "AUDIO_WAV";
  if (!readAudio(*stream, header, sizeof(header), started)) return "AUDIO_STREAM";
  auto u16 = [&](int p) { return uint16_t(header[p]) | (uint16_t(header[p+1]) << 8); };
  auto u32 = [&](int p) { return uint32_t(header[p]) | (uint32_t(header[p+1]) << 8) | (uint32_t(header[p+2]) << 16) | (uint32_t(header[p+3]) << 24); };
  bool valid = memcmp(header,"RIFF",4) == 0 && memcmp(header+8,"WAVEfmt ",8) == 0 &&
    u32(16) == 16 && u16(20) == 1 && u16(22) == 1 && u16(34) == 16 &&
    memcmp(header+36,"data",4) == 0 && u32(24) >= 8000 && u32(24) <= 48000 &&
    u32(40) == uint32_t(http.getSize() - 44) && u32(40) % 2 == 0;
  if (!valid) return "AUDIO_WAV";
  const uint32_t total = u32(40), rate = u32(24);
  // Stage whole clips that fit; very long clips keep the bounded, monitored streaming path.
  const bool staged = total <= 1024 * 1024;
  AudioCache cache;
  const char *error = nullptr;
  // Cover the measured ~0.4 s delivery delay with 0.75 s of PCM, independent of sample rate.
  const size_t preroll = min(size_t(total), size_t(rate * 3 / 4) * 2);
  const auto ring = staged ? nullptr : xStreamBufferCreate(preroll + 2048, 1);
  AudioDownload download{*stream, ring, total, started};
  if (staged) {
    error = cache.stage(*stream, total, started);
    http.end();
    if (error) return cancelAudio ? "AUDIO_CANCELLED" : error;
  } else {
    if (!ring) return "AUDIO_MEMORY";
    if (xTaskCreate(downloadAudio, "audio-http", 4096, &download, 1, nullptr) != pdPASS) {
      vStreamBufferDelete(ring);
      return "AUDIO_MEMORY";
    }
    while (!cancelAudio && !download.finished && xStreamBufferBytesAvailable(ring) < preroll) delay(2);
    if (xStreamBufferBytesAvailable(ring) < preroll) error = "AUDIO_STREAM";
  }
  static uint8_t buffer[2048], stereo[4096];
  constexpr int dmaCount = 12, dmaFrames = 256;
    i2s_config_t config = {};
    config.mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_TX);
    config.sample_rate = u32(24); config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
    config.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT;
    config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
    config.dma_buf_count = dmaCount; config.dma_buf_len = dmaFrames; config.tx_desc_auto_clear = true;
    i2s_pin_config_t pins = {};
    pins.mck_io_num = I2S_PIN_NO_CHANGE;
    pins.bck_io_num = I2S_BCLK; pins.ws_io_num = I2S_LRC; pins.data_out_num = I2S_DOUT;
    pins.data_in_num = I2S_PIN_NO_CHANGE;
  QueueHandle_t dmaEvents = nullptr;
  const bool installed = !error && !cancelAudio &&
    i2s_driver_install(I2S_NUM_0, &config, 64, &dmaEvents) == ESP_OK;
  if ((!installed && !error) || (installed && i2s_set_pin(I2S_NUM_0, &pins) != ESP_OK)) error = "AUDIO_I2S";
  bool announced = false;
  uint32_t submitted = 0, underruns = 0, partialWrites = 0, drained = 0;
  auto checkDma = [&]() {
    i2s_event_t event;
    while (xQueueReceive(dmaEvents, &event, 0) == pdTRUE) {
      if (event.type == I2S_EVENT_DMA_ERROR) error = "AUDIO_I2S";
      if (event.type == I2S_EVENT_TX_Q_OVF && announced) {
        ++underruns;
        error = "AUDIO_UNDERRUN";
      }
    }
  };
  while (!error && submitted < total && !cancelAudio && millis() - started < 110000) {
    const size_t count = min(size_t(total - submitted), sizeof(buffer));
    size_t received = staged ? cache.read(buffer, count, submitted) : 0;
    if (staged && received != count) error = "AUDIO_CACHE";
    while (!staged && received < count && !cancelAudio && !error && millis() - started < 110000) {
      received += xStreamBufferReceive(ring, buffer + received, count - received, pdMS_TO_TICKS(15));
      checkDma();
      if (download.finished && received < count && xStreamBufferBytesAvailable(ring) == 0)
        error = "AUDIO_STREAM";
    }
    if (received != count || error || cancelAudio) break;
    size_t outputBytes = duplicateMono16(buffer, count, stereo, sizeof(stereo));
    for (size_t offset = 0; offset < outputBytes && !error && !cancelAudio;) {
      size_t written = 0;
      if (i2s_write(I2S_NUM_0, stereo + offset, outputBytes - offset, &written, pdMS_TO_TICKS(250)) != ESP_OK
          || !written || written % 4 || written > outputBytes - offset) {
        error = "AUDIO_I2S"; break;
      }
      if (written < outputBytes - offset) ++partialWrites;
      offset += written;
      submitted += written / 2;
      checkDma();
    }
    if (!outputBytes || error || cancelAudio) break;
    if (!announced) {
      AudioEvent event{true, nullptr};
      xQueueSend(audioEvents, &event, portMAX_DELAY);
      announced = true;
    }
  }
  if (!error && submitted == total && !cancelAudio) {
    // A full DMA cycle after the last write guarantees that its descriptor reached TX EOF.
    const auto drainStarted = millis();
    const auto drainBudget = 150 + 2 * dmaCount * dmaFrames * 1000UL / rate;
    while (!cancelAudio && !error && drained < dmaCount && millis() - drainStarted < drainBudget) {
      i2s_event_t event;
      if (xQueueReceive(dmaEvents, &event, pdMS_TO_TICKS(20)) == pdTRUE) {
        if (event.type == I2S_EVENT_TX_DONE) ++drained;
        if (event.type == I2S_EVENT_DMA_ERROR) error = "AUDIO_I2S";
      }
    }
    if (drained != dmaCount && !error) error = "AUDIO_DRAIN";
  }
  if (installed) i2s_driver_uninstall(I2S_NUM_0);
  if (ring) {
    download.stop = true;
    while (!download.finished) delay(2);
    vStreamBufferDelete(ring);
  }
  const auto received = staged ? cache.received : download.received;
  Serial.printf("Audio rate=%lu expected_frames=%lu received_frames=%lu queued_frames=%lu underruns=%lu partial_writes=%lu drain_eof=%lu max_read_ms=%lu staged=%d\n",
                (unsigned long)rate, (unsigned long)(total / 2), (unsigned long)(received / 2),
                (unsigned long)(submitted / 2), (unsigned long)underruns, (unsigned long)partialWrites,
                (unsigned long)drained, (unsigned long)(staged ? cache.longestRead : download.longestRead), staged);
  return cancelAudio ? "AUDIO_CANCELLED" : error ? error :
    submitted != total || received != total ? "AUDIO_STREAM" : nullptr;
}

void audioWorker(void *) {
  AudioJob job;
  for (;;) {
    xQueueReceive(audioJobs, &job, portMAX_DELAY);
    const char *error = playAudio(job.url);
    Serial.printf("Audio result=%s heap=%u min_heap=%u stack_min=%u\n",
                  error ? error : "DONE", ESP.getFreeHeap(), ESP.getMinFreeHeap(),
                  unsigned(uxTaskGetStackHighWaterMark(nullptr)));
    AudioEvent event{false, error};
    xQueueSend(audioEvents, &event, portMAX_DELAY);
  }
}
#endif

void setup() {
  Serial.begin(115200);
  Serial.printf("Boot reset_reason=%d heap=%u\n", int(esp_reset_reason()), ESP.getFreeHeap());
#if AUDIO_ENABLED
  audioJobs = xQueueCreate(1, sizeof(AudioJob));
  audioEvents = xQueueCreate(2, sizeof(AudioEvent));
  if (!audioJobs || !audioEvents || xTaskCreate(audioWorker, "audio", 8192, nullptr, 1, nullptr) != pdPASS) {
    if (audioJobs) vQueueDelete(audioJobs);
    if (audioEvents) vQueueDelete(audioEvents);
    audioJobs = nullptr; audioEvents = nullptr;
    Serial.println("Audio worker unavailable");
  }
#endif
  // GPIOs remain untouched until explicitly configured for the real wiring.
  for (int pin : {LIGHT_PIN, FAN_PIN}) if (pin >= 0) { digitalWrite(pin, RELAY_OFF); pinMode(pin, OUTPUT); }
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  mqtt.setServer(MQTT_HOST, MQTT_PORT); mqtt.setCallback(received); mqtt.setBufferSize(2048);
  mqtt.setSocketTimeout(3); mqtt.setKeepAlive(20);
  wifiRetryAt = millis() + wifiRetryDelay;
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiAddress != IPAddress()) {
      mqtt.disconnect(); wifiAddress = IPAddress(); epoch = ""; mode = "";
      if (playing) cancelAudio = true;
      if (mdnsStarted) { MDNS.end(); mdnsStarted = false; }
    }
    if (int32_t(millis() - wifiRetryAt) >= 0) {
      WiFi.reconnect();
      wifiRetryAt = millis() + wifiRetryDelay;
      wifiRetryDelay = min(wifiRetryDelay * 2, 60000UL);
    }
  } else if (wifiAddress != WiFi.localIP()) {
    wifiAddress = WiFi.localIP(); mqtt.disconnect();
    epoch = ""; mode = "";
    if (playing) cancelAudio = true;
    wifiRetryDelay = 15000; wifiRetryAt = millis() + wifiRetryDelay;
    retryDelay = 2000; retryAt = millis();
    if (mdnsStarted) { MDNS.end(); mdnsStarted = false; }
    Serial.printf("WiFi connected: %s\n", wifiAddress.toString().c_str());
  }
  if (mqtt.connected() && WiFi.status() == WL_CONNECTED) {
    mqtt.loop();
    if (mqtt.connected() && millis() - mqttConnectedAt >= 30000) retryDelay = 2000;
  }
  if (!mqtt.connected() && playing) cancelAudio = true;
  AudioEvent event;
  while (audioEvents && xQueueReceive(audioEvents, &event, 0) == pdTRUE) {
    if (mqtt.connected() && speechEpoch == epoch && !cancelAudio) {
      status("speech", speechId, speechEpoch, event.started ? "PLAYING" : event.error ? "ERROR" : "DONE",
             event.error ? event.error : "");
    }
    if (!event.started) playing = false;
  }
  if (WiFi.status() == WL_CONNECTED && !mqtt.connected() && int32_t(millis() - retryAt) >= 0) {
    epoch = ""; mode = "";
#if DISCOVERY_ENABLED
    if (!discoverPi()) {
      retryAt = millis() + retryDelay;
      retryDelay = min(retryDelay * 2, 30000UL);
      Serial.println("Pi discovery pending; credentials were not sent.");
      return;
    }
#endif
    String clientId = "signassist-" + String(uint32_t(ESP.getEfuseMac()), HEX);
    if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD)) {
      mqttConnectedAt = millis();
      bool subscribed = true;
      for (const char *suffix : {"/mode", "/command", "/speech"}) {
        if (!mqtt.subscribe((String(MQTT_TOPIC) + suffix).c_str(), 1)) subscribed = false;
      }
      if (subscribed && mqtt.publish((String(MQTT_TOPIC) + "/status").c_str(), "{\"kind\":\"hello\"}", false)) {
        Serial.println("MQTT connected to verified Pi");
      } else {
        Serial.println("MQTT subscription or hello send failed");
        mqtt.disconnect();
      }
    } else {
      Serial.printf("MQTT connect failed: state=%d\n", mqtt.state());
    }
    retryAt = millis() + retryDelay;
    retryDelay = min(retryDelay * 2, 30000UL);
  }
  delay(2);
}
