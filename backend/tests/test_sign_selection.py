from time import monotonic
import pytest
from server import create_app


def test_confirmed_sign_waits_for_selection_and_rejects_stale_choices(tmp_path, monkeypatch):
    monkeypatch.setattr('server.ROOT', tmp_path)
    pi = create_app(tmp_path / 'signs.sqlite3').state.pi
    pi.set_mode('ai', pi.epoch, 'mode-for-select')
    pi.accept_after = 0
    pi.sign({'id': 'sign-001', 'label': 'xin_chao', 'text': 'Xin chào', 'captured_at': monotonic()})
    assert not pi.buffers['ai']['text'] and pi.suggestion['text'] == 'Xin chào'
    pi.sign({'id': 'sign-002', 'label': 'xin_chao', 'text': 'Xin chào', 'captured_at': monotonic()})
    assert pi.suggestion['id'] == 'sign-002'
    payload = dict(request_id='select-request-01', epoch=pi.epoch, candidate_id='sign-002', expected_revision=0, label='xin_chao')
    pi.select_sign(payload)
    pi.select_sign(payload)
    assert pi.buffers['ai']['text'] == 'Xin chào' and pi.suggestion is None
    assert pi.ai['request_id'] is None and not pi.pending
    with pytest.raises(Exception) as exc:
        pi.select_sign(dict(payload, request_id='select-stale'))
    assert exc.value.status_code == 409
    with pytest.raises(Exception) as exc:
        pi.select_sign(dict(payload, request_id='select-unknown', candidate_id=None, expected_revision=1, label='invented_label'))
    assert exc.value.status_code == 422
    with pytest.raises(Exception) as exc:
        pi.set_mode('iot', pi.epoch, 'mode-to-iot')
    assert exc.value.status_code == 410


def test_only_latest_stable_caption_appends_exact_text_and_expires(tmp_path, monkeypatch):
    pi = create_app(tmp_path / 'captions.sqlite3').state.pi
    pi.set_mode('ai', pi.epoch, 'mode-for-caption')
    pi.accept_after = 0
    now = 30
    monkeypatch.setattr('pi_modes.monotonic', lambda: now)

    def emit(event, label, text, confirmed=True):
        pi.sign(dict(id=event, label=label, text=text, captured_at=now, confirmed=confirmed))

    def select(event, label, request):
        pi.select_sign(dict(request_id=request, epoch=pi.epoch, candidate_id=event,
                            expected_revision=pi.buffers['ai']['revision'], label=label, operation='append_caption'))

    emit('guess', 'xin_chao', 'Xin chào', False)
    assert not pi.current_caption()
    emit('one', 'xin_chao', 'Xin chào')
    select('one', 'xin_chao', 'select-one')
    assert pi.buffers['ai']['text'] == 'Xin chào'
    with pytest.raises(Exception) as repeat:
        select('one', 'xin_chao', 'select-one-again')
    assert repeat.value.status_code == 409
    pi.write_buffer('ai', 'Xin chào bạn   ')
    emit('two', 'an_com', 'Ăn cơm')
    select('two', 'an_com', 'select-two')
    emit('three', 'tam_biet', 'Tạm biệt')
    select('three', 'tam_biet', 'select-three')
    assert pi.buffers['ai']['text'] == 'Xin chào bạn Ăn cơm Tạm biệt'
    emit('expired', 'tam_biet', 'Tạm biệt')
    now = 40
    with pytest.raises(Exception) as stale:
        select('expired', 'tam_biet', 'select-expired')
    assert stale.value.status_code == 409
    assert not pi.current_caption() and not pi.pending and pi.ai['request_id'] is None
    with pi.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM recognition_corrections').fetchone()[0] == 0
