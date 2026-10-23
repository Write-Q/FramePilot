"""Real browser editing, default FFmpeg render, playback, download and acceptance.

Only synthetic local media and FakeModel are used. The database_url fixture creates
and drops its own random PostgreSQL database; this is not model-quality evidence.
"""
import io
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
from threading import Thread
import time
import wave

import av
import pytest
import uvicorn

from app.main import create_app
from tests.test_editing import editing
from tests.test_shot_media import media
from tests.test_story import FakeModel
from tests.test_video_runtime import video


def _tone():
    output = io.BytesIO()
    with wave.open(output, 'wb') as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(b''.join(struct.pack('<h', round(8000 * math.sin(2 * math.pi * 440 * i / 8000)))
                                   for i in range(8000)))
    return output.getvalue()


def test_browser_edits_renders_plays_downloads_and_accepts(editing, tmp_path, monkeypatch):
    node = os.getenv('FRAMEPILOT_NODE') or shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('playwright')"], capture_output=True).returncode:
        pytest.skip('需要配置 Node/Playwright 才能验证真实后期浏览器流程')
    _, service, _, project, board, source_run, _ = editing
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(service.files.root))
    monkeypatch.setenv('FRAMEPILOT_AUDIO_ROOT', str(service.audio_root))
    audio = tmp_path / 'local-tone.wav'
    audio.write_bytes(_tone())
    queued_signal = tmp_path / 'browser-queued.json'
    rendered_signal = tmp_path / 'worker-rendered.json'
    download = tmp_path / 'browser-download.mp4'
    app = create_app(database_url=service.store.engine.url.render_as_string(hide_password=False), provider=FakeModel())
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='error'))
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    process = None
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, '浏览器测试 HTTP 服务未启动'
            time.sleep(.05)
        process = subprocess.Popen([node, 'tests/editing-real-playback.cjs'],
            cwd=Path(__file__).resolve().parents[1], env=dict(os.environ,
                EDITING_TEST_URL=f'http://127.0.0.1:{port}/editing?project={project}&board={board["id"]}',
                EDITING_TEST_AUDIO=str(audio), EDITING_TEST_QUEUED=str(queued_signal),
                EDITING_TEST_RENDERED=str(rendered_signal), EDITING_TEST_DOWNLOAD=str(download)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='replace')
        deadline = time.monotonic() + 45
        while not queued_signal.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        if not queued_signal.exists():
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            pytest.fail('浏览器没有完成 UI 保存和排队：' + stdout + stderr)
        # Harness signal is written only after the browser has seen the queued UI.
        # It does not replace an application route or inject a renderer.
        queued = json.loads(queued_signal.read_text(encoding='utf-8'))
        rows = service.exports(project, board['id'])
        assert len(rows) == 1 and rows[0]['id'] == queued['id'] and rows[0]['status'] == 'queued'
        assert not rows[0]['accepted']
        assert service.run_once()  # Production default renderer, real FFmpeg subprocess.
        row = service.exports(project, board['id'])[0]
        rendered_signal.write_text(json.dumps({'status': row['status']}), encoding='utf-8')
        assert row['status'] == 'succeeded', row
        stdout, stderr = process.communicate(timeout=45)
        assert process.returncode == 0, stdout + stderr
        evidence = json.loads(stdout.strip().splitlines()[-1])
        assert evidence['advanced_time'] > .15
        assert evidence['download_bytes'] == row['output']['size_bytes']
        assert evidence['timeline_saves'] == 1 and evidence['export_requests'] == 1
        assert evidence['acceptance_requests'] == 1 and evidence['range_status'] == 206
        state = service.list(project, board['id'])
        timeline = state['timeline']
        assert timeline['version'] == 1 and len(state['versions']) == 1
        assert timeline['content']['clips'] == [
            {'run_id': source_run['id'], 'start_ms': 100, 'end_ms': 900, 'gain': .5}]
        assert timeline['content']['subtitles'] == [
            {'start_ms': 0, 'end_ms': 500, 'text': '本地浏览器成片验收'}]
        assert len(state['audio']) == 1
        assert timeline['content']['audio_tracks'] == [
            {'asset_id': state['audio'][0]['id'], 'offset_ms': 0, 'gain': .4, 'loop': True}]
        assert state['exports'][0]['accepted']
        assert state['exports'][0]['acceptance']['comment'] == '本地合成素材浏览器验收；不代表真实模型质量评测。'
        exported = service.media(project, board['id'], row['id'])[0].read_bytes()
        assert download.read_bytes() == exported
        with av.open(io.BytesIO(exported)) as result:
            assert result.streams.video[0].codec_context.name == 'h264'
            assert result.streams.audio[0].codec_context.name == 'aac'
            frames = list(result.decode(video=0))
            assert len(frames) >= 18
            # Source fixture is flat gray: contrast during the caption and none
            # afterwards demonstrates that the actual renderer burned it in.
            def caption_extrema(frame):
                image = frame.to_image().convert('L')
                return image.crop((0, image.height * 2 // 3, image.width, image.height)).getextrema()
            low, high = caption_extrema(frames[4])
            plain_low, plain_high = caption_extrema(frames[-1])
            assert high - low > 100 and plain_high - plain_low < 10
        with av.open(io.BytesIO(exported)) as result:
            pcm = av.AudioResampler(format='s16', layout='mono', rate=8000)
            assert any(abs(sample[0]) > 100
                       for frame in result.decode(audio=0)
                       for converted in pcm.resample(frame)
                       for sample in struct.iter_unpack('<h', bytes(converted.planes[0])[:converted.samples * 2]))
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), '浏览器测试 HTTP 服务未退出'
