#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

inline size_t duplicateMono16(const uint8_t *mono, size_t bytes,
                              uint8_t *stereo, size_t capacity) {
  if (bytes % 2 || bytes > capacity / 2) return 0;
  for (size_t i = 0; i < bytes; i += 2) {
    memcpy(stereo + i * 2, mono + i, 2);
    memcpy(stereo + i * 2 + 2, mono + i, 2);
  }
  return bytes * 2;
}
