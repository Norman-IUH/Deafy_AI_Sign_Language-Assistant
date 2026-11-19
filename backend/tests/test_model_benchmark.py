import json
from pathlib import Path

import numpy as np
import pytest
import torch

from model_benchmark_data import save_capture, load_captures, checked_arrays
from model_benchmark_metrics import metrics
from model_test_profiles import model_schemas


def sample_metadata(identifier='sample1', split='test', session='S01'):
    return dict(id=identifier, subject='P03', session=session, split=split, condition='normal', kind='gesture',
                label='An_Com', created_at='unit-test', preprocessing=model_schemas()['new']['preprocessing'])


def arrays(value=1):
    return np.full((100,126),value,np.float32), np.tile([False,True],(100,1)), np.arange(100,dtype=float)/10


def test_capture_checksums_no_overwrite_and_split_leakage(tmp_path):
    row,path=save_capture(tmp_path,sample_metadata(),*arrays())
    assert load_captures(tmp_path,'test')[0]['metadata']['sha256']==row['sha256']
    with pytest.raises(FileExistsError):save_capture(tmp_path,sample_metadata(),*arrays())
    save_capture(tmp_path,sample_metadata('copy','validation','S02'),*arrays())
    with pytest.raises(ValueError,match='duplicated'):load_captures(tmp_path,'test')


def test_capture_session_leakage_and_bad_input(tmp_path):
    save_capture(tmp_path,sample_metadata(),*arrays())
    save_capture(tmp_path,sample_metadata('different','validation'),*arrays(2))
    with pytest.raises(ValueError,match='session'):load_captures(tmp_path,'test')
    with pytest.raises(ValueError):save_capture(tmp_path,{**sample_metadata(),'subject':'../outside'},*arrays())
    with pytest.raises(ValueError):checked_arrays(np.full((100,126),np.nan),arrays()[1],arrays()[2])
    with pytest.raises(ValueError):checked_arrays(*[a[:10] for a in arrays()])


def test_metrics_missing_classes_not_fabricated_and_negative_rates():
    rows=[dict(expected='A',predicted='A',events=None,latency_ms=1),dict(expected='A',predicted=None,events=None,latency_ms=3)]
    result=metrics(rows,['A','B'])
    assert result['accuracy']==.5 and result['per_class']['B']['f1'] is None
    assert result['macro_f1_all_classes'] is None and result['false_positive_rate'] is None
    assert result['no_confirmation_rate'] is None
    rows=[dict(expected=None,predicted='A',kind='random_motion',events=[dict(label='A')],duration_seconds=10,inference_ms=[1])]
    result=metrics(rows,['A','B'])
    assert result['false_positive_rate']==1 and result['false_events_per_minute']==6
    assert result['negative_kinds']['no_gesture']['false_positive_rate'] is None


def test_selection_requires_f1_gain_without_worse_false_positive_or_latency():
    from model_benchmark_metrics import standalone_candidate
    def result(f1,fp=.1,p95=10):return dict(macro_f1_all_classes=f1,false_positive_rate=fp,inference_latency_ms={'p95':p95})
    assert standalone_candidate(result(.8),result(.85))=='new'
    assert standalone_candidate(result(.85),result(.8))=='old'
    assert standalone_candidate(result(.8),result(.85,.2)) is None
    assert standalone_candidate(result(.8),result(.85,p95=30)) is None
    assert standalone_candidate(result(.8),result(.85,p95=None)) is None
    assert standalone_candidate(result(None),result(.85)) is None


def test_replay_uses_same_gate_masks_and_timing():
    from benchmark_models import replay
    class Constant(torch.nn.Module):
        def forward(self,x):return torch.tensor([[4.,0.]])
    f,m,t=arrays()
    sample=dict(features=f,masks=m,timestamps=t,metadata=dict(id='unit',subject='unit',condition='normal',kind='gesture',label='A',capture_fps=10))
    with torch.inference_mode():
        result=replay(Constant(),{'A':0,'B':1},sample)
        assert result['predicted']=='A' and len(result['events'])==1
        assert 3 <= result['first_confirmed_seconds'] <= 4
        result=replay(Constant(),{'A':0,'B':1},{**sample,'masks':np.zeros_like(m)})
        assert not result['events'] and not result['inference_ms']


def test_frozen_test_manifest_does_not_silently_expand_or_change(tmp_path):
    from benchmark_models import benchmark
    root=tmp_path/'data';out=tmp_path/'reports'
    save_capture(root,sample_metadata(),*arrays())
    result=benchmark(root,'test',out,freeze=True)
    assert result['test_frozen'] and result['dataset']['count']==1
    assert result['hybrid']['metrics'] is None and result['models']['new']['common']['macro_f1_all_classes'] is None
    save_capture(root,sample_metadata('later',session='S03'),*arrays(2))
    result=benchmark(root,'test',out)
    assert result['dataset']['count']==1
    manifest=json.loads((root/'frozen-test.json').read_text())
    path=root/manifest['samples'][0]['path']
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='checksum'):benchmark(root,'test',out)
