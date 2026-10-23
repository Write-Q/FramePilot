"""Actual HTTP save/queue, local FFmpeg render and Range download acceptance."""
import av
import io

from tests.test_editing import editing, content, wav_bytes
from tests.test_video_runtime import video
from tests.test_shot_media import media


def test_http_real_export_with_audio_subtitles_and_acceptance(editing, monkeypatch):
    client, service, _, project, board, run, url = editing
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(service.files.root))
    monkeypatch.setenv('FRAMEPILOT_AUDIO_ROOT', str(service.audio_root))
    base = url + '/editing'
    state = client.get(base).json()
    assert state['selected_clips'][0]['media_url']
    audio = client.post(base + '/audio', content=wav_bytes(), headers={'Content-Type': 'audio/wav'})
    assert audio.status_code == 201, audio.text
    assert client.get(base + '/audio').json()[0]['id'] == audio.json()['id']
    timeline = content(run['id'])
    timeline['subtitles'] = [{'start_ms': 0, 'end_ms': 700, 'text': '本地成片测试'}]
    timeline['audio_tracks'] = [{'asset_id': audio.json()['id'], 'offset_ms': 0, 'gain': .5, 'loop': False}]
    saved = client.post(base + '/timeline', json={'expected_version': 0, 'source_version': 1, 'content': timeline})
    assert saved.status_code == 201, saved.text
    req = {'expected_version': 1, 'idempotency_key': 'real-render-test-001'}
    task = client.post(base + '/exports', json=req)
    assert task.status_code == 201, task.text
    assert service.run_once()
    row = client.get(base + '/exports').json()[0]
    assert row['status'] == 'succeeded', row
    response = client.get(row['media_url'])
    assert response.status_code == 200
    with av.open(io.BytesIO(response.content)) as result:
        assert result.streams.video[0].width == 1280
        assert result.streams.audio[0].codec_context.name == 'aac'
        assert len(list(result.decode(video=0))) >= 18
    partial = client.get(row['media_url'], headers={'Range': 'bytes=0-31'})
    assert partial.status_code == 206 and partial.content == response.content[:32]
    download = client.get(row['download_url'])
    assert 'attachment' in download.headers['content-disposition']
    accepted = client.post(base + '/exports/' + row['id'] + '/accept', json={'comment': '检查成片'})
    assert accepted.status_code == 200 and accepted.json()['accepted']
    assert client.post(base + '/exports', json=req).json()['id'] == row['id']
