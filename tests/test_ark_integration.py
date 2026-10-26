"""Real isolated PostgreSQL and media decoding; provider HTTP is simulated."""
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Event, Thread
import time

import httpx
import pytest
import uvicorn

from app.production.ark import ArkImageAdapter, ArkVideoAdapter
from app.production.media_contracts import CreateMediaRun
from app.production.video_runtime import VideoRuntime, VideoRequest
from tests.test_ark_adapters import config, picture
from tests.test_shot_media import media
from tests.test_video_files import make_video
from tests.test_video_runtime import make_due


@pytest.fixture
def ark(media, tmp_path, monkeypatch):
    monkeypatch.setenv('TEST_ARK_KEY', 'test-not-real-key')
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(tmp_path / 'video'))
    client, images, project, board, _, url = media
    seen = []
    state = {'submit': 'ok', 'poll': 'succeeded'}
    output = make_video(frames=40)
    def handle(request):
        seen.append(request)
        if request.url.path.endswith('/images/generations'):
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(picture()).decode()}]})
        if request.method == 'POST':
            if state['submit'] == 'timeout':
                raise httpx.ReadTimeout('do-not-expose')
            return httpx.Response(200, json={'id': 'cgt-test-original'})
        if request.url.path.endswith('/cgt-test-original'):
            if state['poll'] == 'transient':
                return httpx.Response(503, json={})
            return httpx.Response(200, json={'id': 'cgt-test-original', 'status': state['poll'],
                'content': {'video_url': 'https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/test?signature=private'}})
        return httpx.Response(200, content=output)
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        monkeypatch.setattr(ArkImageAdapter, '__init__', lambda self, **kwargs: setattr(self, 'client', http))
        monkeypatch.setattr(ArkVideoAdapter, '__init__', lambda self, **kwargs: setattr(self, 'client', http))
        image_profile = client.post('/api/production/model-profiles', json=config().model_dump()).json()
        video_profile = client.post('/api/production/model-profiles', json=config('video').model_dump()).json()
        assert image_profile['executable'] and video_profile['executable']
        request = CreateMediaRun(expected_version=1, shot_key='shot-1', frame_role='first',
            profile={'profile_id': image_profile['id'], 'version': 1}, idempotency_key='ark-image-request-1', size='1536x864')
        image = images.create(project, board['id'], request)
        assert images.run_once()  # Default dispatch, not an injected fake image adapter.
        images.select(project, board['id'], image['id'], 1)
        video_request = VideoRequest(expected_version=1, shot_key='shot-1',
            profile={'profile_id': video_profile['id'], 'version': 1}, idempotency_key='ark-video-request-1')
        runtime = VideoRuntime(images.store)
        yield client, runtime, project, board, video_request, url, seen, state


def test_ark_http_to_durable_media_and_api_selection(ark):
    client, runtime, project, board, request, url, seen, _ = ark
    assert 'ark_seedance' in client.get('/api/production/video-adapters').json()['registered']
    first = client.post(url + '/video-runs', json=request.model_dump())
    assert first.status_code == 201, first.text
    identity = first.json()['id']
    assert client.post(url + '/video-runs', json=request.model_dump()).json()['id'] == identity
    assert runtime.run_once()
    saved = runtime.list(project, board['id'])['runs'][0]
    assert saved['status'] == 'submitted' and saved['external_id'] == 'cgt-test-original'
    assert not runtime.run_once()
    make_due(runtime, identity)
    assert runtime.run_once()
    saved = runtime.list(project, board['id'])['runs'][0]
    assert saved['status'] == 'succeeded' and saved['output']['metadata']['duration_ms'] == 4000
    assert 'signature' not in json.dumps(saved)
    assert client.get(saved['media_url']).content == make_video(frames=40)
    assert client.post(url + '/video-runs/' + identity + '/select', json={'expected_version': 1}).json()['selected']
    assert len([r for r in seen if r.method == 'POST']) == 2  # One image and one video.
    assert not runtime.run_once()


def test_timeout_is_durable_unknown_without_a_second_submit(ark):
    _, runtime, project, board, request, _, seen, state = ark
    state['submit'] = 'timeout'
    identity = runtime.create(project, board['id'], request)['id']
    runtime.run_once()
    assert runtime.list(project, board['id'])['runs'][0]['status'] == 'unknown'
    assert runtime.create(project, board['id'], request)['id'] == identity
    assert not runtime.run_once()
    assert len([r for r in seen if r.method == 'POST']) == 2


def test_poll_failure_preserves_external_id_and_retries_get_only(ark):
    _, runtime, project, board, request, _, seen, state = ark
    identity = runtime.create(project, board['id'], request)['id']
    runtime.run_once()
    state['poll'] = 'transient'
    make_due(runtime, identity)
    runtime.run_once()
    saved = runtime.list(project, board['id'])['runs'][0]
    assert saved['status'] == 'submitted' and saved['external_id'] == 'cgt-test-original'
    state['poll'] = 'succeeded'
    make_due(runtime, identity)
    runtime.run_once()
    assert runtime.list(project, board['id'])['runs'][0]['status'] == 'succeeded'
    assert len([r for r in seen if r.method == 'POST']) == 2


def test_revision_requires_its_own_selected_first_frame(ark):
    client, runtime, project, board, request, url, seen, _ = ark
    updated = json.loads(json.dumps(board['content']))
    updated['shots'][0]['duration_ms'] = 4500
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': updated}).status_code == 201
    assert client.post(url + '/confirm', json={'expected_version': 2}).status_code == 200
    # No image carried across the revision: the existing boundary rejects early.
    result = client.post(url + '/video-runs', json=request.model_dump() | {'expected_version': 2})
    assert result.status_code == 409
    assert not runtime.list(project, board['id'])['runs']
    assert len(seen) == 1


def test_missing_key_after_queue_fails_before_external_submit(ark, monkeypatch):
    _, runtime, project, board, request, _, seen, _ = ark
    runtime.create(project, board['id'], request)
    monkeypatch.delenv('TEST_ARK_KEY')
    runtime.run_once()
    saved = runtime.list(project, board['id'])['runs'][0]
    assert saved['status'] == 'failed' and saved['error_code'] == 'missing_key'
    assert len(seen) == 1  # Only the prior image call.


def test_ark_workbench_browser(ark, monkeypatch):
    node = shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('playwright')"], capture_output=True).returncode:
        pytest.skip('需要 Node.js 和 Playwright')
    client, runtime, project, _, _, _, seen, _ = ark
    monkeypatch.setattr('app.production.video_runtime.POLL_INTERVAL_SECONDS', 0)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, host='127.0.0.1', log_level='error'))
    web = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    stop, errors = Event(), []
    def work():
        try:
            while not stop.is_set():
                runtime.run_once()
                stop.wait(.05)
        except Exception as exc:
            errors.append(type(exc).__name__)
    worker = Thread(target=work, daemon=True)
    web.start()
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert web.is_alive() and time.monotonic() < deadline
            time.sleep(.05)
        result = subprocess.run([node, '--test', 'tests/ark-workbench.test.cjs'], cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ, FRAMEPILOT_UI_URL=f'http://127.0.0.1:{port}', FRAMEPILOT_PROJECT=project),
            capture_output=True, encoding='utf-8', errors='replace', timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not errors, errors
        assert len([request for request in seen if request.method == 'POST']) == 2
    finally:
        stop.set()
        worker.join(timeout=15)
        server.should_exit = True
        web.join(timeout=15)
        listener.close()
        assert not worker.is_alive() and not web.is_alive()
