"""Step 6 webcam inference; displays labels and simulated commands only."""
import argparse
from pathlib import Path
import sys
import time

import cv2
import mediapipe as mp
import numpy as np
import torch

from step2_collect_data import extract_features
from step6_inference_pipeline import DecisionGate, MOCK_MESSAGES, TimeWindow, predict, validate_preprocessing
from step5_train import load_checkpoint

WINDOW = 'VSL GRU | MOCK commands | Q/Esc quit | R reset'


def mock_display(label, accepted, emitted):
    if emitted:
        return MOCK_MESSAGES.get(label, 'LABEL: ' + label)
    if accepted:
        return 'NONE (stable; cooldown/latch suppresses new event)'
    return 'NONE'


def check_model(path):
    model, checkpoint = load_checkpoint(path, device='cpu')
    validate_preprocessing(checkpoint)
    mapping = checkpoint['class_to_idx']
    # Synthetic smoke only: no predicted label/command published for this input.
    predict(model, np.zeros((1, 30, 126), np.float32), mapping)
    print(f'Checkpoint: {Path(path).resolve()}')
    print(f'Classes: {mapping} | Best epoch: {checkpoint["best_epoch"]}')
    print('Input: (1,30,126), duration: 3.0 seconds, mirrored: True, Left then Right')
    print(f'Training validation accuracy: {checkpoint.get("best_val_accuracy", float("nan")):.1%}')
    return model, checkpoint


def run_camera(args, model, checkpoint):
    if not hasattr(mp, 'solutions'):
        raise RuntimeError('Install requirements.txt in the project .venv')
    window = TimeWindow(required=args.required_hands)
    gate = DecisionGate(args.threshold, args.stable_count, args.cooldown)
    api = {'auto': cv2.CAP_ANY, 'dshow': cv2.CAP_DSHOW, 'msmf': cv2.CAP_MSMF}[args.backend]
    cap = cv2.VideoCapture(args.camera, api)
    top, command, status = 'NONE', 'NONE', 'Waiting for required hand'
    previous, last_prediction, fps = time.perf_counter(), float('-inf'), 0.0
    failures = 0
    try:
        if not cap.isOpened():
            raise RuntimeError('Cannot open camera. Close other apps/check permissions or --camera 1.')
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        with mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2,
                                     model_complexity=1, min_detection_confidence=0.5,
                                     min_tracking_confidence=0.5) as hands:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    window.clear()
                    gate.reset()
                    top, command = 'NONE', 'NONE'
                    blank = np.zeros((480, 640, 3), np.uint8)
                    cv2.putText(blank, 'Camera read failed - predictions cleared', (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 255), 1)
                    cv2.imshow(WINDOW, blank)
                    if failures >= 10:
                        raise RuntimeError('Camera failed 10 consecutive reads; stopped.')
                    if cv2.waitKey(50) & 0xFF in (27, ord('q')):
                        break
                    continue
                failures = 0
                captured = time.perf_counter()
                fps = .9 * fps + .1 / max(captured - previous, 1e-9)
                previous = captured
                frame = cv2.flip(frame, 1)  # Same mirror convention as Step 2.
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                result = hands.process(rgb)
                features, mask = extract_features(result)  # Shape: (126,), mask (2,).
                reset_reason = window.add(captured, features, mask)
                if reset_reason:
                    gate.reset()
                    top, command, status = 'NONE', 'NONE', reset_reason
                elif window.coverage < window.duration:
                    status = f'Collecting window: {window.coverage:.1f}/3.0 seconds'
                elif captured - last_prediction >= args.interval:
                    data = window.sample()  # Shape: (1,30,126), 30 time samples over 2s.
                    if data is not None:
                        label, score = predict(model, data, checkpoint['class_to_idx'])
                        top = f'{label} {score:.1%} (UNCONFIRMED model score)'
                        accepted, emitted = gate.update(label, score, captured)
                        command = mock_display(label, accepted, emitted)
                        status = f'Gate: {gate.count}/{args.stable_count}, threshold {args.threshold:.0%}'
                        if emitted:
                            print(f'[MOCK ONLY] {label} score={score:.3f} -> {command}', flush=True)
                        last_prediction = captured
                for hand in result.multi_hand_landmarks or []:
                    mp.solutions.drawing_utils.draw_landmarks(frame, hand, mp.solutions.hands.HAND_CONNECTIONS)
                lines = [f'FPS: {fps:.1f} | required: {args.required_hands} | L:{int(mask[0])} R:{int(mask[1])}',
                         status, 'Top: ' + top, 'MOCK display: ' + command,
                         'R: clear window | Q/Esc: quit | No real device connection']
                for i, line in enumerate(lines):
                    cv2.putText(frame, line, (10, 25 + 27 * i), cv2.FONT_HERSHEY_SIMPLEX,
                                .45, (0, 255, 0), 1, cv2.LINE_AA)
                cv2.imshow(WINDOW, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord('q')) or cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
                if key == ord('r'):
                    window.clear()
                    gate.reset()
                    top, command, status = 'NONE', 'NONE', 'Manual reset; collect a new 2-second window'
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--backend', choices=('auto', 'dshow', 'msmf'), default='auto')
    parser.add_argument('--required-hands', choices=('right', 'left', 'both', 'either'), default='right')
    parser.add_argument('--threshold', type=float, default=.7)
    parser.add_argument('--stable-count', type=int, default=3)
    parser.add_argument('--cooldown', type=float, default=2.0)
    parser.add_argument('--interval', type=float, default=.2)
    args = parser.parse_args()
    try:
        DecisionGate(args.threshold, args.stable_count, args.cooldown)
        if not np.isfinite(args.interval) or not .05 <= args.interval <= .5:
            raise ValueError('interval must be between 0.05 and 0.5 seconds')
        torch.set_num_threads(1)
        model, checkpoint = check_model(args.checkpoint)
        if args.check_only:
            print('PASS: checkpoint metadata and forward verified; camera not opened.')
            return 0
        print('Experimental model, no idle/unknown class. Scores are not calibrated confidence.')
        print('Only screen/console simulation. Q/Esc quit, R reset. Keep gesture within 2 seconds.')
        run_camera(args, model, checkpoint)
    except KeyboardInterrupt:
        print('\nStopped; camera released.')
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, cv2.error) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
