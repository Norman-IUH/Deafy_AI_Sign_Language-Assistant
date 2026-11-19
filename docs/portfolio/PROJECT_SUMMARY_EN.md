# Deafy — AI Sign Language Communication Assistant

Deafy is a university course project for assisted communication on a Raspberry Pi 5 (4 GB). It converts a limited set of trained gestures into an editable Vietnamese draft, supports explicit AI requests, and provides speech through a networked ESP32-S3.

MediaPipe produces left/right hand landmarks. A GRU predicts labels from 30 × 126 feature windows. Pi connects FastAPI, SQLite, MQTT and I2S audio; Android uses local inference with ONNX Runtime Web and can use the Pi for connected services. Learning feedback goes into a review queue before any potential retraining.

Engineering work that can be discussed: matching model inputs and label indices, tracking mirrored camera input, guarding repeated gesture events, and distinguishing audio transfer completion from audible speech. The prior parity run agreed on top-1 and top-3 for 115/115 stored validation tensors; it does not measure real Android camera accuracy. See the [evidence table](../release/TEST_REPORT.md).

Before publishing, add only the modules you owned, your specific contribution, and evidence you can explain. Camera acceptance on physical Android remains pending.
