# Deafy — AI Sign Language Communication Assistant

Deafy is a university engineering project combining sign recognition, accessible communication, location services and speech playback on Raspberry Pi 5 (4 GB) and Android.

**University course project · Raspberry Pi 5 (4 GB) · v1.0 release candidate.** See [release status](docs/release/RELEASE_NOTES.md) and [validation evidence](docs/release/TEST_REPORT.md).

## Problem and objectives

Signing and speaking participants may lack a shared input method. Deafy turns a limited vocabulary of camera-observed signs into editable text, lets the user ask an assistant or request speech, and supports a small touch display and an Android client. It classifies individual trained gestures and concatenates accepted labels; it is not an open-vocabulary sign-language translator.

## Features and implementation

| Area | What runs |
| --- | --- |
| Pi station | USB camera and microphone, live landmarks and Vietnamese subtitles, manual sign selection or continuous draft assembly, 7-inch touchscreen UI |
| Android | Capacitor Android app with local camera, MediaPipe, ONNX Runtime Web and JavaScript GRU fallback; LAN pairing for Pi services |
| Assistant | FastAPI routing for Q&A, rewriting by request, Open-Meteo weather, nearby places from Geoapify Places and named-address geocoding |
| Audio | MQTT and LAN WAV transfer to ESP32-S3, then I2S to MAX98357A and a speaker |
| Learning | Explicitly submitted landmark samples, review and dataset export; retraining is offline and a new checkpoint requires separate validation and promotion |

See [editable system and wiring diagrams](docs/diagrams/SYSTEM.md). The current demo hardware is a Pi 5 4 GB, 7-inch display, USB webcam/microphone, ESP32-S3, MAX98357A and speaker; a Windows laptop with a GPU is optional for CIT. The stack uses Python, PyTorch, MediaPipe, FastAPI, SQLite, React/Vite, Capacitor, Mosquitto, PlatformIO and Arduino ESP32.

## Architecture

One FastAPI process on Pi owns camera inference, SQLite, microphone recognition, MQTT, assistant routing and speech coordination. Android has its own camera, MediaPipe Hands and exported Model 2. ONNX Runtime Web is preferred; the same GRU weights are available through a JavaScript fallback. iPhone uses the existing HTTPS web to share GPS. Safari inference is archived research.

CIT Voice Studio on Windows synthesizes Ngọc Huyền on GPU through a pinned SSH tunnel. Pi delivers PCM16 WAV over local HTTP to ESP32-S3 and MAX98357A. The ESP reports ACK, PLAYING, DONE or ERROR. Gemini Aoede/Kore and explicitly selected offline speech remain available.

Model 2 is a two-layer unidirectional GRU, hidden size 64, with 22 labels. Input is float32 30 × 126, left hand then right hand. Checkpoint SHA-256 is 031d470cfd8d3c734c441da35b090cb91ddb197a84d9fb8391ce4ae16adc40f6.

The pipeline detects 21 XYZ landmarks per hand, puts them in the training order, and samples a 3-second window. Missing hands fill their slot with zeros; the active profile requires a valid right-hand stream to collect the window. Stability and rearming rules suppress repeated events from a held sign. Continuous assembly appends accepted events to the local draft without sending a question or initiating audio.

## Run on Raspberry Pi

Use Raspberry Pi OS 64-bit, Python 3.12, Node.js 22 and Mosquitto. Keep private configuration in backend/.env.local using backend/pi.env.example as a template.

    python3 -m venv backend/.venv-pi
    backend/.venv-pi/bin/pip install -r backend/requirements-pi.txt -r backend/requirements-dev.txt
    npm --prefix RaspberryPi_7inch ci
    bash scripts/install-deafy-launcher.sh
    bash start_deafy.sh

Open http://localhost:5173 on Pi. The desktop launcher uses the same entry point. Add --kiosk for kiosk mode. Stop with bash stop_deafy.sh.

The portfolio source archive excludes checkpoints, exported weights, private configuration, training records and separately distributed runtime assets. Supply the permitted, verified checkpoint at `DAKT_GRU_CHECKPOINT`. Never copy Windows virtual environments onto Pi.

## Android

Open Android_App/android in Android Studio using JDK21 and SDK36. Install the acceptance APK, enter the Pi token and select Tìm thiết bị Deafy. NSD discovers candidates; an HMAC challenge verifies the paired Pi before credentials are sent. Android Keystore encrypts the pairing token.

To build from a clean source archive, first export the approved checkpoint with `scripts/export-mobile-model.py` (pass the trusted hash with `--expected-sha256`) and supply the licensed MediaPipe `hand_landmarker.task` in `Android_App/public/mobile/tasks/`. The build stages the remaining runtime assets from installed packages.

    npm --prefix Android_App ci
    npm --prefix Android_App run android:sync
    cd Android_App/android
    ./gradlew assembleDebug lintDebug

The acceptance APK is debug-signed. Installing the main application ID can upgrade an older installation if signatures match; save important drafts first. A production signing key belongs to the owner and is not created or replaced here.

Use **Cài đặt → Thông tin AI** to check model provenance and runtime. **Giao tiếp → Chẩn đoán AI** shows camera, hand detection and Model 2 timings. See [parity results](docs/release/TEST_REPORT.md) and [the Android setup guide](docs/setup/android.md).

If a known right hand appears as left, use **Tay phải bị báo trái?** on the affected camera. **Chẩn đoán AI → Đổi hướng ảnh nguồn** toggles source orientation for comparison.

## GPS and speech

iPhone opens https://deafy.local:8443/ and shares GPS in Settings. Nearby searches require GPS younger than 15 minutes with accuracy within 500 m.

On Windows enable the hotspot, open CIT Voice Studio with its GPU model and run START_DEAFY_DEMO.bat. Keep the terminal open. The launcher locates Pi, verifies its pinned ED25519 host key, opens the reverse tunnel and checks CIT from Pi. Supply the verified host-key file separately when deploying another machine.

Geoapify Places provides nearby categories; Geocoding resolves named addresses. Use a Free project within quota. Provider keys stay on the backend. Never publish .env.local, secrets.h, databases, private keys or deployment backups.

## Repository guide

- [Pi setup](docs/setup/pi.md) and [Android build](docs/setup/android.md)
- [Assistant and places](docs/guides/assistant-and-places.md), [CIT voice](docs/setup/cit-voice.md), and [iPhone GPS](docs/setup/iphone-gps.md)
- [Gesture feedback](docs/model/gesture-feedback.md) and [Model 2 benchmarks](docs/model/benchmark.md)
- `tools/preview/` contains desktop preview tools; `tools/qa/` contains browser fixtures. Use the root launchers to start the demo.

## Validation and documentation

    backend/.venv-pi/bin/python -m pytest backend/tests -q
    node --test Android_App/src/mobile/pipeline.test.mjs shared/transport.test.mjs
    npm --prefix RaspberryPi_7inch run build
    npm --prefix Android_App run build

See [test results](docs/release/TEST_REPORT.md), [installation and rollback](docs/release/RELEASE_NOTES.md), and the [3–5 minute demo shot list](docs/demo/README.md). The public demo video and product photos are pending; reference mockups are not product evidence.

Physical Android camera/inference and NSD acceptance remains required. Confidence is a model score, not measured accuracy. User samples require review before training. Relays are disabled in the active demo profile. Short signs without a clear boundary and mirrored webcam sources can be difficult; improvement requires labeled physical-device recordings and separate window/handedness evaluation.

## Contributors and responsibilities

This is a course project. A technology list describes the system, not an individual contribution. The team should confirm names, ownership and publication permission before a public release. See the [CV worksheet](docs/portfolio/CV_BULLETS.md) for statements to use only after confirming responsibility.

See [credits and release rights](docs/release/THIRD_PARTY.md). Review checkpoint, dataset and voice permissions before distribution. There is no publication license granted by this handover.
