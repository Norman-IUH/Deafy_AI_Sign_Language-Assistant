#pragma once
// Copy to secrets.h (ignored). Confirm board, wiring and relay active level first.
#define WIFI_SSID ""
#define WIFI_PASSWORD ""
#define MQTT_HOST ""
#define MQTT_PORT 1883
// Enable after the Pi advertises _deafy._tcp; manual host fields remain a fallback.
#define DISCOVERY_ENABLED 0
#define MQTT_USER ""
#define MQTT_PASSWORD ""
#define MQTT_TOPIC "signassist/esp32"
#define LIGHT_PIN -1
#define FAN_PIN -1
#define RELAY_ON HIGH
#define RELAY_OFF LOW
// Optional I2S DAC/amplifier. Leave disabled until the actual hardware is known.
#ifndef AUDIO_ENABLED
#define AUDIO_ENABLED 0
#endif
#define I2S_BCLK -1
#define I2S_LRC -1
#define I2S_DOUT -1
#define AUDIO_BASE_URL ""
