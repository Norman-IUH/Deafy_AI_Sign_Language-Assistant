"""Reproducible Windows benchmark; no Pi, training or confidence-based model mixing."""
import argparse
from collections import Counter
import csv
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'Deafy_AI_share_ver0'))
from model_test_profiles import PROFILES, checkpoint_path, model_schemas
from model_benchmark_data import load_captures
from model_benchmark_metrics import metrics, standalone_candidate


def rss_mb():
    if os.name != 'nt':
        return None
    class Memory(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(n, ctypes.c_size_t) for n in ('peak', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    value = Memory(); value.cb = ctypes.sizeof(value)
    return value.working/1024**2 if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(value), value.cb) else None


def replay(model, mapping, sample):
    import numpy as np
    import torch
    from step6_inference_pipeline import TimeWindow, DecisionGate
    window, gate = TimeWindow(required='right', duration=3, length=30), DecisionGate(.7, 3, 2)
    inverse = {i: label for label, i in mapping.items()}
    events, delays, last = [], [], float('-inf')
    for timestamp, features, mask in zip(sample['timestamps'], sample['features'], sample['masks']):
        if window.add(float(timestamp), features, mask):
            gate.reset()
            continue
        if window.coverage < 3 or timestamp-last < .2:
            continue
        sequence = window.sample()
        if sequence is None:
            continue
        began = perf_counter()
        logits = model(torch.from_numpy(np.asarray(sequence, dtype=np.float32)))
        delays.append((perf_counter()-began)*1000)
        if logits.shape != (1, len(mapping)) or not torch.isfinite(logits).all():
            raise ValueError('Invalid model logits')
        probability = logits.softmax(1)[0]
        label, confidence = inverse[int(probability.argmax())], float(probability.max())
        _, emitted = gate.update(label, confidence, float(timestamp))
        if emitted:
            events.append({'label': label, 'confidence': confidence, 'seconds': float(timestamp)})
        last = timestamp
    row = sample['metadata']
    return {'id': row['id'], 'subject': row['subject'], 'condition': row['condition'], 'kind': row['kind'],
            'expected': row['label'], 'predicted': events[0]['label'] if events else None,
            'first_confirmed_seconds': events[0]['seconds'] if events else None,
            'events': events, 'duration_seconds': float(sample['timestamps'][-1]-sample['timestamps'][0]),
            'inference_ms': delays, 'capture_fps': row['capture_fps']}


def benchmark(capture_root, split, output, freeze=False):
    import torch
    from step5_train import load_checkpoint
    from step6_inference_pipeline import validate_preprocessing
    from scripts.compare_model_checkpoints import compare
    torch.set_num_threads(1)
    started_wall, started_cpu = perf_counter(), process_time()
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    schemas = model_schemas()
    common = sorted(set(schemas['old']['classes']) & set(schemas['new']['classes']))
    extra = sorted(set(schemas['old']['classes']) - set(schemas['new']['classes']))
    captured = load_captures(capture_root, split)
    validation = load_captures(capture_root, 'validation')
    locked = Path(capture_root)/'frozen-test.json'
    frozen = False
    if freeze:
        if split != 'test' or not captured:
            raise ValueError('Cần tập test webcam đã thu trước khi đóng băng.')
        rows = [{'path': s['path'], 'sha256': s['metadata']['sha256']} for s in captured]
        locked.parent.mkdir(parents=True, exist_ok=True)
        with locked.open('x', encoding='utf-8') as stream:
            json.dump({'created_at': datetime.now(timezone.utc).isoformat(), 'samples': rows}, stream, indent=2)
    if split == 'test' and locked.is_file():
        wanted = json.loads(locked.read_text(encoding='utf-8'))['samples']
        actual = {s['path']: s for s in captured}
        if any(r['path'] not in actual or actual[r['path']]['metadata']['sha256'] != r['sha256'] for r in wanted):
            raise ValueError('Tập test đã đóng băng bị thiếu hoặc thay đổi; không tự chọn tập khác.')
        captured = [actual[r['path']] for r in wanted]
        frozen = True
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'split': split, 'test_frozen': frozen,
              'shared_labels': common, 'old_only_labels': extra, 'models': {},
              'hybrid': {'status': 'NOT_ELIGIBLE', 'metrics': None,
                         'reason': 'Chưa có validation/test độc lập đủ mỗi lớp và calibration. Không chọn theo confidence, không trộn logits/softmax hoặc bật hybrid trong UI.'},
              'gate': {'threshold': .7, 'stable_count': 3, 'cooldown_seconds': 2, 'window_seconds': 3, 'frames': 30},
              'pi': 'NOT TOUCHED / NOT VERIFIED', 'captures_used': [s['path'] for s in captured]}
    if captured:
        for name in PROFILES:
            model, checkpoint = load_checkpoint(checkpoint_path(name)); validate_preprocessing(checkpoint)
            with torch.inference_mode():
                for _ in range(8): model(torch.zeros(1,30,126))
                wall, cpu = perf_counter(), process_time()
                rows = [replay(model, checkpoint['class_to_idx'], s) for s in captured]
                elapsed, used_cpu = perf_counter()-wall, process_time()-cpu
            report['models'][name] = {'sha256': PROFILES[name]['sha256'], 'common': metrics(rows, common),
                'additional_coverage': metrics(rows, extra) if name == 'old' else {'status': 'UNSUPPORTED', 'labels': extra},
                'per_subject': {subject: metrics([r for r in rows if r['subject']==subject],common) for subject in sorted({r['subject'] for r in rows})},
                'per_condition': {condition: metrics([r for r in rows if r['condition']==condition],common) for condition in sorted({r['condition'] for r in rows})},
                'runtime': {'cpu_percent_one_core': used_cpu/elapsed*100 if elapsed else None, 'process_working_set_mb': rss_mb(),
                            'replay_frames_per_second': sum(len(s['timestamps']) for s in captured)/elapsed if elapsed else None,
                            'scope': 'Windows Python process + Torch + current model; replay excludes camera/MediaPipe, not Pi FPS'}, 'predictions': rows}
            del model, checkpoint
        report['dataset'] = {'source': 'new_webcam_landmark_streams', 'count': len(captured),
                             'counts': dict(Counter(s['metadata']['label'] or s['metadata']['kind'] for s in captured)),
                             'subjects': sorted({s['metadata']['subject'] for s in captured}),
                             'conditions': sorted({s['metadata']['condition'] for s in captured}),
                             'truth': 'user declared; no video or independent verification'}
    elif split == 'test':
        diagnostic = compare(ROOT/'data/data/raw', output/'legacy_diagnostic.json')
        for name, model in diagnostic['models'].items():
            rows = [r for r in model['predictions'] if r['strict_holdout']]
            report['models'][name] = {'sha256': model['sha256'], 'common': metrics(rows, common),
                                      'additional_coverage': {'status': 'NO_DATA'} if name=='old' else {'status': 'UNSUPPORTED', 'labels':extra},
                                      'runtime': {'status':'CLASSIFICATION_ONLY: no camera/gate/CPU baseline'}, 'predictions':rows}
        report['dataset'] = {'source': 'legacy_strict_holdout_by_sha256', 'count': diagnostic['strict_holdout']['count'],
                             'counts': diagnostic['strict_holdout']['class_counts'],
                             'limitation': 'Only one available class, known signer P02. Excluded BOTH train and validation. No negative/stream frames; false positive, duplication, camera FPS and gesture-to-confirmation unavailable.'}
    else:
        for name in PROFILES:
            report['models'][name] = {'sha256':PROFILES[name]['sha256'], 'common':metrics([],common),
                                      'additional_coverage':{'status':'NO_DATA'}, 'runtime':{'status':'NO_DATA'}, 'predictions':[]}
        report['dataset'] = {'source':'no_captured_validation','count':0,'counts':{},'limitation':'Chưa thu validation; không tái sử dụng final test làm validation.'}
    counts = report['dataset']['counts']
    validation_counts = Counter(s['metadata']['label'] or s['metadata']['kind'] for s in validation)
    report['coverage'] = {'minimum_target_per_label': 20, 'desired_per_label': 30,
                          'missing_test_counts': {label:max(0,20-counts.get(label,0)) for label in common},
                          'missing_validation_counts': {label:max(0,20-validation_counts[label]) for label in common},
                          'negative_kinds_missing': {kind:max(0,20-counts.get(kind,0)) for kind in ('no_gesture','random_motion','unknown_sign')}}
    report['recommendation'] = 'INSUFFICIENT_EVIDENCE: model 2 là ứng viên theo phản hồi mới nhất; chưa đủ test độc lập đa nhãn/người để chọn thắng hoặc ghép hybrid. Không triển khai Pi.'
    if captured:
        known_subjects = set().union(*(set(s['training_subjects']) for s in schemas.values()))
        declared_new = set(report['dataset']['subjects']) - known_subjects
        validation_subjects = {s['metadata']['subject'] for s in validation}
        report['dataset']['declared_subjects_not_in_training_ids'] = sorted(declared_new)
        report['dataset']['declared_heldout_subjects'] = sorted(declared_new - validation_subjects)
        report['dataset']['subjects_also_in_validation'] = sorted(set(report['dataset']['subjects']) & validation_subjects)
        enough = frozen and split == 'test' and all(n == 0 for n in report['coverage']['missing_test_counts'].values()) \
            and all(n == 0 for n in report['coverage']['negative_kinds_missing'].values()) \
            and len(report['dataset']['subjects']) >= 2 and len(report['dataset']['conditions']) >= 2 and bool(declared_new - validation_subjects)
        if enough:
            a,b=[report['models'][name]['common'] for name in ('old','new')]
            candidate = standalone_candidate(a,b)
            if candidate:
                report['recommendation'] = f'Ứng viên {candidate}: macro F1 hơn ít nhất 0.02, FPR không tăng, P95 không quá 1.2 lần. Chỉ đề xuất kiểm thử Pi sau phê duyệt; không coi định danh tự khai báo là chứng minh người độc lập.'
            else:
                report['recommendation'] = 'Chưa có phương án đơn lẻ thắng rõ theo chính sách F1/FPR/latency; giữ thử model 2 theo phản hồi người dùng và không bật hybrid.'
    elapsed = perf_counter()-started_wall
    report['process_resources'] = {'cpu_percent_one_core': (process_time()-started_cpu)/elapsed*100 if elapsed else None,
                                   'process_working_set_mb': rss_mb(), 'scope':'entire Windows benchmark process including imports/metadata; not Pi and not isolated model-only RAM'}
    report['selection_policy'] = {'minimum_per_class':20,'minimum_negative_per_kind':20,'minimum_declared_subjects':2,'minimum_conditions':2,
                                  'macro_f1_absolute_gain':.02,'maximum_latency_ratio':1.2,'false_positive_increase_allowed':0,
                                  'note':'Predetermined descriptive rule, not a statistical significance test; hybrid not fitted on final test.'}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    axes = sorted(set().union(*(set(s['classes']) for s in schemas.values()))) + ['__miss__']
    for name in ('old','new'):
        matrix = Counter((r['expected'],r['predicted'] or '__miss__') for r in report['models'][name]['predictions'] if r['expected'] is not None)
        with (output/f'confusion_{name}.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(['expected / predicted',*axes])
            for label in axes[:-1]:
                support=sum(n for (expected,_),n in matrix.items() if expected==label)
                writer.writerow([label,*[matrix[label,p] if support else '' for p in axes]])
    with (output/'per_class.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream); writer.writerow(['label','support','precision_old','recall_old','f1_old','precision_new','recall_new','f1_new','decision'])
        for label in common:
            a,b=[report['models'][name]['common']['per_class'][label] for name in ('old','new')]
            decision = 'INSUFFICIENT_VALIDATION'
            if split == 'validation' and a['support'] >= 20:
                decision = 'tie_descriptive' if abs(a['f1']-b['f1']) < .02 else 'old_descriptive' if a['f1'] > b['f1'] else 'new_descriptive'
            writer.writerow([label,a['support'],a['precision'],a['recall'],a['f1'],b['precision'],b['recall'],b['f1'],decision])
    lines=['# Benchmark Model 1 / Model 2 / Hybrid', '', report['recommendation'], '',f"Nguồn: {report['dataset']['source']} · {report['dataset']['count']} mẫu · split {split} · frozen={frozen}", '',
           '| Model | Số mẫu dương chung | Accuracy | Macro F1 đủ 22 lớp | FPR mẫu âm | Inference mean / P95 ms |', '|---|---:|---:|---:|---:|---|']
    fmt=lambda v:'NOT VERIFIED' if v is None else f'{v:.4f}'
    for name in ('old','new'):
        m=report['models'][name]['common']; t=m['inference_latency_ms']
        lines.append(f"| {name} | {m['positive_count']} | {fmt(m['accuracy'])} | {fmt(m['macro_f1_all_classes'])} | {fmt(m['false_positive_rate'])} | {fmt(t['mean'])} / {fmt(t['p95'])} |")
    lines+=['| Hybrid | — | NOT ELIGIBLE | NOT ELIGIBLE | NOT ELIGIBLE | NOT MEASURED |','', 'Không suy từ softmax ra xác suất đúng. Không gọi accuracy một nhãn là accuracy 22 nhãn. Thời gian xác nhận tính từ cue thu mẫu, không phải onset động tác được gán nhãn video.', '',
            'Per-class/Confusion/CPU/RAM/coverage: xem report.json và per_class.csv. Mẫu thiếu được ghi null/NOT VERIFIED, không bịa 0 hoặc 100%. Không dùng final test để điều chỉnh threshold/hybrid.', '',
            'Thu 20–30 mẫu mỗi nhãn từ nhiều người/ánh sáng/nền và 20–30 mẫu mỗi loại âm. Tách người/session cho validation và final test. Chỉ freeze test khi đã thu xong; sau freeze giữ nguyên tập mẫu.']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-dir',type=Path,default=ROOT/'.tools/model-test/benchmark-data')
    parser.add_argument('--split',choices=['test','validation'],default='test')
    parser.add_argument('--output',type=Path,default=ROOT/'.tools/model-benchmark/latest')
    parser.add_argument('--freeze-test',action='store_true')
    args=parser.parse_args()
    try:
        result=benchmark(args.capture_dir,args.split,args.output,args.freeze_test)
    except (ValueError,OSError,KeyError) as issue:
        print('BENCHMARK BLOCKED: '+str(issue),file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({'samples':result['dataset'],'recommendation':result['recommendation'],'report':str(args.output/'report.md')},ensure_ascii=False))
