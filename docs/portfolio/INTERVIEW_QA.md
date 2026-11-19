# Interview questions

**Why 30 × 126?** Thirty temporal samples; two hands × 21 landmarks × three coordinates. Slot order and window semantics must follow training.

**Why can Android disagree with Pi if logits match on the same tensor?** The camera, source mirroring, handedness mapping and real frame timing determine the tensor; runtime parity tests only the latter part of the pipeline.

**Is continuous mode translation?** It accumulates accepted labels into an editable draft. It does not learn sentence grammar or translate unrestricted sign language.

**Why MQTT and HTTP together?** MQTT carries small jobs and playback status. HTTP carries full WAV payloads. The firmware tracks writes and DMA drain, but listening is still required for audio quality.

**What happens offline?** Android inference and local draft are separate from Pi calls. Connected operations become unavailable; pairing verifies identity before sharing credentials.

**Does the model learn while running?** No. Samples require explicit consent, review, dataset export, offline training and validation before promotion.

**What would you validate next?** Both physical Android cameras, hand mapping, labeled real signs, reconnect, end-to-end latency and a larger sample for accuracy.
