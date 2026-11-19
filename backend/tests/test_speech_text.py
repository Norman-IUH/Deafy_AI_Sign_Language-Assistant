import pytest
from speech_text import speech_text


@pytest.mark.parametrize('source,expected', [
    ('**Ứng dụng bản đồ:** Mở **Google Maps** để tìm quán ăn.', 'Ứng dụng bản đồ: Mở Google Maps để tìm quán ăn.'),
    ('## Xin chào\n\n- **Mẹ**\n- `Cha`', 'Xin chào\nMẹ\nCha'),
    ('3. [Đọc thêm](https://example.com)\n4. Tiếng Việt', '3. Đọc thêm\n4. Tiếng Việt'),
    ('3 * 4 = 12; 2 ** 3; C#; a_b; #1', '3 * 4 = 12; 2 ** 3; C#; a_b; #1'),
    ('Một ngày có 24 giờ.', 'Một ngày có 24 giờ.'),
    ('```text\nXin chào\n```', 'Xin chào'),
])
def test_markdown_for_speech(source, expected):
    assert speech_text(source) == expected


def test_direct_speech_preserves_user_markdown_characters(tmp_path,monkeypatch):
    import asyncio
    from server import create_app
    from test_pi_modes import FakeMQTT,sample_wav,reply
    monkeypatch.setattr('server.ROOT',tmp_path)
    monkeypatch.setenv('DAKT_AUDIO_BASE_URL','http://pi-test.local:8001')
    pi=create_app(tmp_path/'verbatim.db').state.pi
    pi.mqtt=FakeMQTT()
    utterances=[]
    monkeypatch.setattr(pi.tts,'synthesize_cloud',lambda text,*_:utterances.append(text) or sample_wav())
    async def run():
        text='C# và **ký hiệu**'
        pi.speak(dict(request_id='verbatim-0001',epoch=pi.epoch,text=text))
        await pi.task
        assert utterances==[text]
        for status in ('ACK','PLAYING','DONE'):pi.on_status(reply(pi,'speech',status))
        pi.speak(dict(request_id='verbatim-0002',epoch=pi.epoch,text=text))
        await pi.task
        assert utterances==[text]
    asyncio.run(run())
