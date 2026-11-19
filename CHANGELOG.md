# Changelog

## Deafy release candidate — 2026-11-19

- Pi and Android RC8 can append each stable sign to an editable draft in continuous mode; single-sign mode remains the default.
- Added opt-in capture controls and undo for a recent automatic append. No submission or playback is triggered by recognition.
- Added portfolio documentation, editable diagrams, release evidence and the source review archive.

## Android 1.0.0-rc7 — 2026-11-18

- Isolated inference from the camera sampling loop and limited inference to one in-flight request.
- Preserved the sample window through short tracking misses, and reported resets while retaining the 200 ms input gap limit.
- Switched to verified JavaScript GRU weights if ONNX fails during inference.

## Android 1.0.0-rc6 — 2026-11-18

- Exposed camera calibration beside the preview and added a reversible source orientation control in diagnostics.
- Reported the raw hand classification, accepted tensor slots, sequence progress, timing gaps and inference state.
- Discarded the active sample window and obsolete predictions when source orientation changes.

## Android 1.0.0-rc4 — 2026-11-18

- Added per-camera right-hand calibration for already mirrored sources.
- Applied the correction before MediaPipe and projected landmarks using the resulting detector and preview orientations.
- Exposed detector handedness and both tensor slots in the diagnostic report.

## Android 1.0.0-rc3 — 2026-11-18

- Matched the Pi’s 3-second nearest-frame sampler and retained the 200 ms gap limit.
- Added checkpoint and artifact hash checks and exposed Android and Pi model identity in Settings.
- Added local, explicitly labeled tensor export for diagnosing camera-domain errors without a Pi connection.

## Android 1.0.0-rc2 — 2026-11-18

- Aligned hand overlays with the visible Android camera frame, including front-camera mirroring and aspect-ratio changes.
- Separated MediaPipe detection, sample collection, inference and subtitle states. Added on-device diagnostics and joint IDs for acceptance testing.
- Compacted camera controls and kept local drafting and phone speech available when the Pi disconnects.
- Retained authenticated Pi discovery and added clearer pairing, network and reconnect feedback.

## 1.0.0-rc1 — 2026-11-18

Stabilization candidate pending physical Android acceptance and owner confirmation.

- Preserved the iPhone GPS web and archived Safari inference experiments.
- Consolidated Android identity and added find/reconnect controls.
- Added Android Keystore encryption of pairing tokens.
- Kept independent drafts and explicit Vietsub selection.
- Fixed unbounded automatic growth of the legacy Pi sentence.
- Preserved explicit assistant tasks.
- Added named-address geocoding alongside nearby searches.
- Separated display/speech and shortened place/weather speech.
- Added bounded WAV caching for replay.
- Kept pinned SSH tunnel discovery and checked ESP audio firmware.

No v1.0.0 tag, commit, push or public repository publication has occurred.
