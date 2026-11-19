"""Bước 2: thu landmarks theo nhãn; SPACE quay, S lưu, R bỏ, Q thoát."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
import uuid

import cv2
import mediapipe as mp
import numpy as np

WINDOW = "VSL collection | SPACE record | S save | R discard | Q quit"


def extract_features(results):
    """Shape (126,): Left[21,3] rồi Right[21,3]; tay vắng = 0 + mask riêng."""
    xyz = np.zeros((2, 21, 3), dtype=np.float32)
    present = np.zeros(2, dtype=bool)
    ambiguous = set()
    for hand, side in zip(results.multi_hand_landmarks or [], results.multi_handedness or []):
        info = side.classification[0]
        if info.label not in ("Left", "Right") or info.score < 0.7:
            continue
        slot = 0 if info.label == "Left" else 1
        if present[slot] or slot in ambiguous:
            # Hai detection cùng nhãn: không đoán thứ tự theo danh sách.
            ambiguous.add(slot)
            present[slot] = False
            xyz[slot] = 0
            continue
        values = np.array([(p.x, p.y, p.z) for p in hand.landmark], dtype=np.float32)
        if values.shape == (21, 3) and np.isfinite(values).all():
            xyz[slot] = values
            present[slot] = True
    return xyz.reshape(126), present


def required_visible(mask, required):
    if required == "both":
        return bool(mask.all())
    if required == "either":
        return bool(mask.any())
    return bool(mask[0 if required == "left" else 1])


def resample(times, frames, masks, duration, length, max_gap=0.2):
    """Lấy frame gần nhất trên lưới đều; không bịa chuyển động bằng nội suy."""
    t = np.asarray(times, dtype=np.float64)
    if len(t) < 2 or not np.all(np.diff(t) > 0):
        raise ValueError("Qua it frame hoac timestamp khong tang.")
    if t[0] > max_gap or duration - t[-1] > max_gap or np.max(np.diff(t)) > max_gap:
        raise ValueError("Camera qua cham/bi ngat: khoang trong > 0.2 giay. Quay lai.")
    grid = np.linspace(0, duration, length, endpoint=False)
    indices = np.abs(t[:, None] - grid[None, :]).argmin(axis=0)
    # Shape: (1 sequence, sequence_length, 21 * 3 * 2).
    data = np.asarray(frames, dtype=np.float32)[indices][None, ...]
    sampled_masks = np.asarray(masks, dtype=bool)[indices]
    return data, sampled_masks, grid, indices


def save_sample(directory, data, metadata):
    if data.ndim != 3 or data.shape[0] != 1 or data.shape[2] != 126 or not np.isfinite(data).all():
        raise ValueError("Shape hoac gia tri mau khong hop le.")
    directory.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex
    array_path = directory / (name + ".npy")
    meta_path = directory / (name + ".json")
    try:
        with array_path.open("xb") as stream:
            np.save(stream, data.astype(np.float32), allow_pickle=False)
        with meta_path.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2)
    except Exception:
        # Chỉ xóa cặp file mới tạo của mẫu này khi lưu thất bại.
        array_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        raise
    return array_path


def run(args):
    if not hasattr(mp, "solutions"):
        raise RuntimeError("Hay cai requirements.txt trong .venv cua du an.")
    directory = args.output.resolve() / args.label
    session_id = uuid.uuid4().hex
    api = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}[args.backend]
    cap = cv2.VideoCapture(args.camera, api)
    state, message = "READY", "SPACE: start countdown"
    times, frames, masks = [], [], []
    pending = None
    saved = 0
    failures = 0
    previous = time.perf_counter()
    fps = 0.0
    try:
        if not cap.isOpened():
            raise RuntimeError("Khong mo duoc webcam. Dong app khac, kiem tra quyen Camera/--camera.")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        with mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2,
                                     model_complexity=1, min_detection_confidence=0.5,
                                     min_tracking_confidence=0.5) as hands:
            while True:
                ok, image = cap.read()
                if not ok or image is None:
                    failures += 1
                    if state in ("COUNTDOWN", "RECORDING"):
                        state, message = "READY", "Sample cancelled: camera read failed. SPACE: retry"
                        frames, times, masks = [], [], []
                    if failures >= 10:
                        raise RuntimeError("Khong doc duoc 10 frame lien tiep; da dung an toan.")
                    if cv2.waitKey(50) & 0xFF in (27, ord("q")):
                        break
                    continue
                failures = 0
                # Giữ cùng quy ước ảnh selfie như Bước 1.
                image = cv2.flip(image, 1)
                captured = time.perf_counter()
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                result = hands.process(rgb)
                features, mask = extract_features(result)
                fps = 0.9 * fps + 0.1 / max(captured - previous, 1e-9)
                previous = captured
                for hand in result.multi_hand_landmarks or []:
                    mp.solutions.drawing_utils.draw_landmarks(image, hand, mp.solutions.hands.HAND_CONNECTIONS)

                if state == "COUNTDOWN":
                    remaining = deadline - captured
                    message = f"Prepare... {max(0, remaining):.1f}s"
                    if remaining <= 0:
                        state, started = "RECORDING", captured
                        times, frames, masks = [], [], []
                if state == "RECORDING":
                    elapsed = captured - started
                    if not required_visible(mask, args.required_hands):
                        state, message = "READY", "REJECTED: required hand missing/uncertain. SPACE: retry"
                        times, frames, masks = [], [], []
                    else:
                        times.append(elapsed)
                        frames.append(features)
                        masks.append(mask)
                        message = f"RECORDING {min(elapsed, args.duration):.1f}/{args.duration:.1f}s"
                        if elapsed >= args.duration:
                            try:
                                data, sampled_masks, grid, indices = resample(
                                    times, frames, masks, args.duration, args.sequence_length)
                                metadata = {
                                    "schema_version": 1, "label": args.label,
                                    "signer": args.signer, "session_id": session_id,
                                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "shape": list(data.shape), "dtype": "float32",
                                    "feature_order": "Left(landmark0.xyz..20.xyz),Right(landmark0.xyz..20.xyz)",
                                    "mirrored_before_inference": True,
                                    "coordinates": "normalized image x,y; wrist-relative z (not meters)",
                                    "required_hands": args.required_hands,
                                    "min_handedness_score": 0.7,
                                    "duration_seconds": args.duration,
                                    "sequence_length": args.sequence_length,
                                    "sampling": "nearest frame on uniform grid; no interpolation",
                                    "grid_seconds": grid.tolist(),
                                    "source_timestamps_seconds": times,
                                    "source_indices": indices.tolist(),
                                    "present_mask_left_right": sampled_masks.tolist(),
                                    "source_present_mask_left_right": np.asarray(masks).tolist(),
                                    "mediapipe_version": mp.__version__,
                                    "opencv_version": cv2.__version__,
                                }
                                pending = (data, metadata)
                                state, message = "REVIEW", "Finished. Correct gesture? S: save | R: discard"
                            except ValueError as exc:
                                state, message = "READY", str(exc)
                lines = [f"Label: {args.label} | {state} | Saved this run: {saved}",
                         f"Required: {args.required_hands} | L: {int(mask[0])} R: {int(mask[1])} | FPS: {fps:.1f}",
                         message, "SPACE: record | S: save | R: discard | Q/Esc: quit"]
                for i, line in enumerate(lines):
                    cv2.putText(image, line, (10, 25 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX,
                                0.46, (0, 255, 255) if state == "RECORDING" else (0, 255, 0), 1, cv2.LINE_AA)
                cv2.imshow(WINDOW, image)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if key == ord("r"):
                    pending = None
                    times, frames, masks = [], [], []
                    state, message = "READY", "Discarded unsaved sample. SPACE: retry"
                elif key == ord("s") and state == "REVIEW":
                    path = save_sample(directory, *pending)
                    saved += 1
                    print(f"Saved {path} | shape={pending[0].shape}", flush=True)
                    pending = None
                    state, message = "READY", "Saved. SPACE: next sample"
                elif key == ord(" ") and state == "READY":
                    if required_visible(mask, args.required_hands):
                        state, deadline = "COUNTDOWN", time.perf_counter() + args.countdown
                    else:
                        message = "Show required hand(s) clearly before SPACE."
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print(f"Da luu {saved} mau trong lan chay nay. Mau chua bam S khong duoc luu.")


def main():
    parser = argparse.ArgumentParser(description="Step 2: collect hand landmarks. SPACE record, S save, R discard, Q quit.")
    parser.add_argument("--label", required=True, help="Nhan khong dau: Bat_Den, Tat_Den...")
    parser.add_argument("--signer", default="P01", help="Ma nguoi thuc hien; khong can ho ten")
    parser.add_argument("--required-hands", choices=("both", "left", "right", "either"), default="both")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "data" / "raw")
    parser.add_argument("--sequence-length", type=int, default=30)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--countdown", type=float, default=3.0)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), default="auto")
    args = parser.parse_args()
    for name in ("label", "signer"):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", getattr(args, name)):
            parser.error(f"--{name}: dung chu cai ASCII, so, dau _; bat dau bang chu cai (toi da 64 ky tu).")
    if args.sequence_length < 2 or not np.isfinite(args.duration) or args.duration <= 0:
        parser.error("sequence-length >= 2 va duration > 0 huu han.")
    if not np.isfinite(args.countdown) or args.countdown < 0:
        parser.error("countdown >= 0 huu han.")
    try:
        run(args)
    except KeyboardInterrupt:
        print("Da dung.")
    except (RuntimeError, OSError, ValueError, cv2.error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
