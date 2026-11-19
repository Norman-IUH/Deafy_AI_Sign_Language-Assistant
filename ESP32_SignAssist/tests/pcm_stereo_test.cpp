#include "pcm_stereo.h"
#include <assert.h>

int main() {
  const uint8_t mono[] = {0x00, 0x80, 0xff, 0x7f, 0x01, 0x00, 0xff, 0xff};
  const uint8_t expected[] = {0x00, 0x80, 0x00, 0x80, 0xff, 0x7f, 0xff, 0x7f,
                              0x01, 0x00, 0x01, 0x00, 0xff, 0xff, 0xff, 0xff};
  uint8_t output[18] = {};
  output[0] = output[17] = 0x55;
  assert(duplicateMono16(mono, sizeof(mono), output + 1, 16) == 16);
  assert(memcmp(output + 1, expected, sizeof(expected)) == 0);
  assert(output[0] == 0x55 && output[17] == 0x55);
  assert(duplicateMono16(mono, 3, output + 1, 16) == 0);
  assert(duplicateMono16(mono, sizeof(mono), output + 1, 15) == 0);
  assert(duplicateMono16(mono, 0, output + 1, 16) == 0);
  assert(memcmp(output + 1, expected, sizeof(expected)) == 0);
}
