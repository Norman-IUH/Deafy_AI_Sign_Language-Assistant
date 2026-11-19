"""Bước 1: kiểm tra MediaPipe Hands độc lập; không ghi ảnh/video."""

import argparse
import sys
import time

import cv2
import mediapipe as mp

WINDOW = "MediaPipe Hands - Q / Esc to quit"


def index_tips(results):
    """Chỉ lấy tọa độ hiện tại; không giữ tọa độ cũ khi mất dấu tay."""
    tips = []
    handedness = results.multi_handedness or []
    for i, hand in enumerate(results.multi_hand_landmarks or []):
        label = handedness[i].classification[0].label if i < len(handedness) else "Unknown"
        tip = hand.landmark[8]  # INDEX_FINGER_TIP; mỗi bàn tay có 21 điểm XYZ.
        tips.append((label, tip.x, tip.y, tip.z))
    return tips


def run(camera=0, backend="auto"):
    if not hasattr(mp, "solutions"):
        raise RuntimeError("Can mediapipe==0.10.21: chay pip install -r requirements.txt trong .venv.")
    api = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}[backend]
    cap = cv2.VideoCapture(camera, api)
    try:
        if not cap.isOpened():
            raise RuntimeError("Khong mo duoc webcam. Kiem tra quyen Camera, dong Zoom/Teams, hoac thu --camera 1.")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        with mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as hands:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            previous = time.perf_counter()
            last_log = previous - 1.0
            fps = 0.0
            failures = 0
            print("Webcam ready. Q / Esc de thoat. Log moi giay; z tuong doi voi co tay, khong phai met.")
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    print(f"[WARN] Khong doc duoc frame ({failures}/10).")
                    if failures >= 10:
                        raise RuntimeError("Mat luong webcam sau 10 lan doc lien tiep.")
                    if cv2.waitKey(50) & 0xFF in (27, ord("q")):
                        break
                    continue
                failures = 0
                # Lật TRƯỚC suy luận: phù hợp quy ước Left/Right của MediaPipe.
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                started = time.perf_counter()
                results = hands.process(rgb)
                inference_ms = (time.perf_counter() - started) * 1000
                tips = index_tips(results)
                for hand in results.multi_hand_landmarks or []:
                    mp.solutions.drawing_utils.draw_landmarks(
                        frame, hand, mp.solutions.hands.HAND_CONNECTIONS
                    )
                now = time.perf_counter()
                current_fps = 1.0 / max(now - previous, 1e-9)
                fps = current_fps if fps == 0 else 0.9 * fps + 0.1 * current_fps
                previous = now
                lines = [
                    f"FPS: {fps:.1f} | inference: {inference_ms:.1f} ms",
                    f"Hands: {len(tips)}/2 | Q / Esc: quit",
                ]
                if not tips:
                    lines.append("No hands detected - waiting...")
                for label, x, y, z in tips:
                    lines.append(f"{label} index: x={x:.3f} y={y:.3f} z={z:+.3f}")
                for i, line in enumerate(lines):
                    cv2.putText(frame, line, (10, 25 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (0, 255, 0), 2, cv2.LINE_AA)
                if now - last_log >= 1.0:
                    print(" | ".join(lines), flush=True)
                    last_log = now
                cv2.imshow(WINDOW, frame)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0, help="Chi so webcam (mac dinh: 0)")
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf"), default="auto")
    args = parser.parse_args()
    try:
        run(args.camera, args.backend)
    except KeyboardInterrupt:
        print("\nDa dung webcam.")
    except (RuntimeError, cv2.error) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
