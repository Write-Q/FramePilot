"""Real locally encoded video through mock provider, persistent result and HTTP Range."""
from tests.test_video_runtime import video, make_due
from tests.test_shot_media import media
from tests.test_video_files import make_video
from app.production.video_files import VideoFiles
from app.production.video_input import VideoPoll
from tests.test_production import confirmed_project


def test_decoded_candidate_http_range_selection_and_isolation(video, tmp_path, monkeypatch):
    client, runtime, adapter, project, board, request, url = video
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(tmp_path / 'videos'))
    runtime.files = VideoFiles()
    run = runtime.create(project, board['id'], request)
    runtime.run_once()
    make_due(runtime, run['id'])
    data = make_video()
    adapter.result = VideoPoll('succeeded', data, 'video/mp4')
    runtime.run_once()
    saved = runtime.list(project, board['id'])['runs'][0]
    assert saved['status'] == 'succeeded', saved
    response = client.get(saved['media_url'])
    assert response.status_code == 200 and response.content == data
    assert response.headers['content-type'] == 'video/mp4'
    part = client.get(saved['media_url'], headers={'Range': 'bytes=0-31'})
    assert part.status_code == 206 and part.content == data[:32]
    assert client.post(url + f'/video-runs/{run["id"]}/select', json={'expected_version': 1}).status_code == 200
    other = confirmed_project(client)
    assert client.get(saved['media_url'].replace('/projects/'+project, '/projects/'+other)).status_code == 404
    path = runtime.files.path(saved['output']['storage_key'])
    path.write_bytes(b'tampered')
    assert client.get(saved['media_url']).status_code == 404


def test_browser_actually_plays_and_selects_video(video, tmp_path, monkeypatch):
    import os, shutil, socket, subprocess, time
    from pathlib import Path
    from threading import Thread
    import uvicorn
    from app.main import create_app
    from tests.test_story import FakeModel
    client, runtime, adapter, project, board, request, _ = video
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(tmp_path / 'videos'))
    runtime.files = VideoFiles()
    run = runtime.create(project, board['id'], request)
    runtime.run_once(); make_due(runtime, run['id'])
    adapter.result = VideoPoll('succeeded', make_video(), 'video/mp4')
    runtime.run_once()
    node = shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('playwright')"], capture_output=True).returncode:
        import pytest
        pytest.skip('需要配置Node和Playwright才能验证实际浏览器播放')
    app = create_app(database_url=runtime.store.engine.url.render_as_string(hide_password=False), provider=FakeModel())
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='error'))
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True); thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(.05)
        result = subprocess.run([node, 'tests/video-real-playback.cjs'], cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ, VIDEO_TEST_URL=f'http://127.0.0.1:{port}/storyboard?project={project}'),
            capture_output=True, encoding='utf-8', errors='replace', timeout=45)
        assert result.returncode == 0, result.stdout + result.stderr
        assert runtime.list(project, board['id'])['runs'][0]['selected']
    finally:
        server.should_exit = True; thread.join(timeout=15); listener.close()
        assert not thread.is_alive()
