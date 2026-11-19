# Deafy v1.0 candidate validation · 2026-11-19

| Check | Result | Evidence / limits |
| --- | --- | --- |
| FastAPI and regression suite | PASS (automated) | 215 passed, 1 skipped. An initial run had 3 MediaPipe initialization failures with incompatible Protobuf 7; restored the existing Windows lock (4.25.9) and reran. Includes mocked assistant/provider responses, GPS, learning, speech, MQTT and reconnect paths. |
| Frontend JavaScript | PASS (automated) | 33 tests; Pi production frontend build succeeded. |
| Pi draft workflow | PASS (simulated UI) | Chromium 800×480: individual accepted events, duplicate event, intentional repeat, pause, finish, undo and fullscreen; zero API writes. |
| Android RC8 packaging | PASS (build) | SDK 36, versionCode 9, debug signature v2 valid, 53 bundled web assets verified, lint 0 errors / 19 warnings. Release signing not performed. |
| Android draft workflow | PASS (simulated UI) | Stable event fixture at 360, 390 and 412 px: continuous/manual, pause, undo, offline draft persistence and zero API/audio writes. Camera/MediaPipe replaced by the fixture in this check. |
| Android Model 2 runtime parity | PASS (stored tensors) | APK's ONNX WASM and JS GRU compared to PyTorch checkpoint. 115/115 stored validation tensors with identical top-1 and top-3 in both runtimes; 114/115 match stored labels. Coverage: 20 of 22 labels, with 125 manifest samples not present. Max ONNX logit difference 2.87 × 10⁻⁶. This is not live camera accuracy. |
| Deployment on physical Pi | PASS (prior session); current status BLOCKED | Verified modified continuous frontend and healthy backend on Pi previously. Pi did not resolve or have an active VNC link during this audit; launcher preflight reports hotspot inactive. |
| Android physical acceptance | BLOCKED | No Android device in ADB. Both cameras, handedness on actual input, real gestures, discovery, reconnect and FPS remain unverified for RC8. |
| MQTT/audio/search on physical hardware | PASS (earlier runs); current status BLOCKED | Earlier Pi runs recorded broker/ESP flow and user-confirmed playback; the user heard all 20 CIT regression utterances after the ESP audio fix and one final sentence once. Geoapify previously returned real category results, and one nearby result was heard on ESP. No hardware playback or fresh paid-provider calls in this audit. |
| Live FPS, USB unplug/replug, learning retraining | NOT VERIFIED | No physical capture or training run in this audit. Do not claim measured end-to-end accuracy, latency, or online learning. |

Model 2 checkpoint SHA-256:
`031d470cfd8d3c734c441da35b090cb91ddb197a84d9fb8391ce4ae16adc40f6`.

Before final release: run both cameras and at least five trained signs on physical Android, measure setup/recognition latency and FPS, test Android reconnect and Pi USB camera recovery, and confirm permissions to publish assets. When comparing audio, distinguish MQTT ACK/PLAYING/DONE and DMA counters from a heard utterance.
