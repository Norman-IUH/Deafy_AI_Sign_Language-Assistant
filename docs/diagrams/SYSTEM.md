# Deafy engineering diagrams

### System architecture

```mermaid
flowchart LR
  Cam[USB camera and microphone] --> P[Pi 5 4 GB · FastAPI]
  P <--> UI[Pi touchscreen UI]
  P <--> D[(SQLite)]
  A[Android] <-->|LAN API and WebSocket| P
  I[iPhone HTTPS web] -->|GPS with consent| P
  P --> S[Assistant and places/weather providers]
  P <-->|MQTT and HTTP audio| E[ESP32-S3]
  L[Windows CIT Voice Studio] <-->|Pinned reverse SSH tunnel| P
```

### Verified wiring

```mermaid
flowchart LR
  Pi[Pi 5] -->|USB| Cam[USB WebCamera]
  Pi -->|Display and touch| UI[7-inch display]
  Pi -->|Existing USB data and power| ESP[ESP32-S3]
  ESP -->|GPIO5 BCLK · GPIO6 WS · GPIO7 DIN · GND| Amp[MAX98357A]
  Amp -->|SPK+ and SPK−| Speaker[4 Ω speaker]
```

VIN, MAX9814 and exact display connectors require inspection before documenting them as verified. This drawing does not direct rewiring.

### Gesture and draft pipeline

```mermaid
flowchart LR
  Cam[Camera] --> MP[MediaPipe · 21 XYZ points per hand]
  MP --> F[Left and right slots · 30 × 126]
  F --> GRU[Model 2 · 22 labels]
  GRU --> Gate[Confidence, stability and rearm]
  Gate --> V[Vietnamese subtitle]
  V -->|Tap or append stable event| Draft[Editable local draft]
  Draft -->|Explicit action| Action[Ask AI or play speech]
```

### Pi ↔ ESP32-S3

```mermaid
sequenceDiagram
  participant P as Raspberry Pi
  participant E as ESP32-S3
  P->>E: Publish audio job over MQTT
  E-->>P: ACK
  E->>P: GET local WAV
  P-->>E: Complete PCM WAV
  E-->>P: PLAYING
  E-->>P: DONE after output drain, or ERROR
```

### TTS and playback

```mermaid
flowchart LR
  Text[Selected text] --> T[CIT, Gemini or configured offline TTS]
  T --> WAV[Validate and normalize PCM16 WAV]
  WAV --> HTTP[Local HTTP transfer]
  HTTP --> I2S[Validate length · handle writes · drain DMA]
  I2S --> Amp[MAX98357A] --> S[Speaker]
```

### Learning and controlled retraining

```mermaid
flowchart LR
  A[Collect a labeled 30 × 126 sample] --> Q[Review queue]
  Q -->|Approve| E[Export dataset]
  Q -->|Reject| R[Excluded]
  E --> T[Train offline]
  T --> V[Validate candidate]
  V -->|Explicit promotion| D[Deploy with rollback]
```

### Android and Pi

```mermaid
flowchart LR
  A[Android Camera] --> M[Local inference]
  M --> Draft[Local Vietnamese subtitle and draft]
  N[Android discovery] --> H[Verify paired Pi identity]
  H --> P[Pi FastAPI · AI / TTS / history / GPS]
  Draft -->|User submits if connected| P
```
