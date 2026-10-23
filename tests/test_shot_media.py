from io import BytesIO

from PIL import Image
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.production.chat import PlannerError
from app.production.media_service import MediaService
from app.production.media_contracts import CreateMediaRun
from app.production.media_io import ImageResult, MediaFiles
from tests.test_production import confirmed_project
from tests.test_production_contracts import board_content, model_config
from tests.test_story import FakeModel


class Images:
    def __init__(self): self.calls = []

    def generate(self, config, prompt, size):
        self.calls.append((config, prompt, size))
        stream = BytesIO()
        Image.new('RGB', (16, 9), 'green').save(stream, format='PNG')
        return ImageResult(stream.getvalue(), 'image/png', {})


@pytest.fixture
def media(database_url, tmp_path, monkeypatch):
    monkeypatch.setenv('FRAMEPILOT_MEDIA_ROOT', str(tmp_path / 'media'))
    with TestClient(create_app(database_url=database_url, provider=FakeModel())) as client:
        project = confirmed_project(client)
        base = f'/api/production/projects/{project}/storyboards'
        content = board_content()
        content['shots'][0]['frame_prompts'] = {'first': '小禾握钥匙，阿林空手'}
        content['shots'][0]['video_prompt'] = '小禾将钥匙递给阿林，阿林接住，缓慢推进'
        board = client.post(base, json={'source_version': 1, 'content': content}).json()
        url = base + '/' + board['id']
        assert client.post(url + '/confirm', json={'expected_version': 1}).status_code == 200
        config = model_config() | {'purpose': 'image', 'adapter': 'openai_images'}
        profile = client.post('/api/production/model-profiles', json=config).json()
        service = MediaService(client.app.state.production, files=MediaFiles(tmp_path / 'media'))
        request = CreateMediaRun(expected_version=1, shot_key='shot-1', frame_role='first',
            profile={'profile_id': profile['id'], 'version': 1}, idempotency_key='image-request-key-1', size='1536x864')
        yield client, service, project, board, request, url


def test_queue_execute_candidate_select_and_idempotency(media):
    client, service, project, board, request, url = media
    run = service.create(project, board['id'], request)
    assert run['status'] == 'queued' and run['media_id'] is None
    assert client.get(url + '/video-input?version=1&shot_key=shot-1').status_code == 409
    assert service.create(project, board['id'], request)['id'] == run['id']
    adapter = Images()
    assert service.run_once(adapter=adapter)
    assert not service.run_once(adapter=adapter)
    saved = service.list(project, board['id'], 1)['runs'][0]
    assert saved['status'] == 'succeeded' and not saved['selected']
    picture = client.get(saved['media_url'])
    assert picture.status_code == 200 and picture.headers['content-type'] == 'image/png'
    other = confirmed_project(client)
    assert client.get(f'/api/production/projects/{other}/media/{saved["media_id"]}').status_code == 404
    assert len(adapter.calls) == 1 and adapter.calls[0][0].purpose == 'image'
    assert service.select(project, board['id'], run['id'], 1)['selected']
    video = client.get(url + '/video-input?version=1&shot_key=shot-1')
    assert video.status_code == 200, video.text
    assert video.json()['executable'] is False
    assert video.json()['first_frame']['media_id'] == saved['media_id']
    assert video.json()['duration_ms'] == 4000
    assert service.create(project, board['id'], request)['id'] == run['id']
    assert client.get(url + '/media-runs?version=1').status_code == 200


def test_unknown_is_not_retried_and_cancelled_queue_never_calls(media):
    _, service, project, board, request, _ = media
    class Timeout:
        def generate(self, *args): raise PlannerError('secret', 'outcome_unknown')
    run = service.create(project, board['id'], request)
    service.run_once(adapter=Timeout())
    saved = service.list(project, board['id'], 1)['runs'][0]
    assert saved['status'] == 'unknown' and 'secret' not in saved['error']
    assert not service.run_once(adapter=Timeout())
    next_request = request.model_copy(update={'idempotency_key': 'image-request-key-2'})
    other = service.create(project, board['id'], next_request)
    service.cancel(project, board['id'], other['id'])
    assert not service.run_once(adapter=Images())


def test_revision_prevents_old_queue_and_selection(media):
    client, service, project, board, request, url = media
    run = service.create(project, board['id'], request)
    content = board['content']
    response = client.post(url + '/versions', json={'expected_version': 1, 'content': content})
    assert response.status_code == 201, response.text
    adapter = Images()
    service.run_once(adapter=adapter)
    assert not adapter.calls
    saved = service.list(project, board['id'], 2)['runs'][0]
    assert saved['status'] == 'failed' and not saved['applicable']
    assert client.post(url + '/media-runs/' + run['id'] + '/select', json={'expected_version': 2}).status_code == 409


def test_api_rejects_wrong_project_and_changed_idempotency(media):
    client, service, project, board, request, url = media
    run = service.create(project, board['id'], request)
    payload = request.model_dump(mode='json') | {'prompt': 'changed'}
    assert client.post(url + '/media-runs', json=payload).status_code == 409
    other = confirmed_project(client)
    assert client.get(f'/api/production/projects/{other}/storyboards/{board["id"]}/media-runs').status_code == 404
    assert client.post(f'/api/production/projects/{other}/storyboards/{board["id"]}/media-runs/{run["id"]}/cancel').status_code == 404


def test_cancel_losing_claim_race_reports_conflict(media, monkeypatch):
    import sqlalchemy as sa
    from app.models import production_tables
    from app.production.store import ProductionConflict
    _, service, project, board, request, _ = media
    run = service.create(project, board['id'], request)
    original = service._run

    def claimed_after_read(conn, *args):
        row = original(conn, *args)
        if row['status'] == 'queued':
            t = production_tables['media_runs']
            with service.store.engine.begin() as worker:
                worker.execute(t.update().where(t.c.id == run['id']).values(status='running', started_at=sa.func.now()))
        return row

    monkeypatch.setattr(service, '_run', claimed_after_read)
    with pytest.raises(ProductionConflict):
        service.cancel(project, board['id'], run['id'])


def test_parallel_workers_and_late_result_after_abandon(media):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import sqlalchemy as sa
    from app.models import domain_tables
    _, service, project, board, request, _ = media
    run = service.create(project, board['id'], request)
    started, release = Event(), Event()

    class Blocking(Images):
        def generate(self, *args):
            started.set()
            assert release.wait(10)
            return super().generate(*args)

    adapter = Blocking()
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(service.run_once, adapter)
        try:
            assert started.wait(10)
            assert pool.submit(service.run_once, adapter).result(timeout=10) is False
            service.abandon(project, board['id'], run['id'])
        finally:
            release.set()
        assert active.result(timeout=10)
    saved = service.list(project, board['id'], 1)['runs'][0]
    assert saved['status'] == 'unknown' and saved['media_id'] is None
    assert len(adapter.calls) == 1
    with service.store.engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(domain_tables['media_files'])).scalar_one() == 0


def test_selected_media_is_pinned_to_board_version_and_terminal_records_immutable(media):
    import sqlalchemy as sa
    from sqlalchemy.exc import DBAPIError
    from app.models import production_tables
    client, service, project, board, request, url = media
    run = service.create(project, board['id'], request)
    service.run_once(adapter=Images())
    service.select(project, board['id'], run['id'], 1)
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    assert client.post(url + '/confirm', json={'expected_version': 2}).status_code == 200
    old = service.list(project, board['id'], 2)['runs'][0]
    assert old['selected'] and not old['applicable']
    assert client.post(url + '/media-runs/' + run['id'] + '/select', json={'expected_version': 2}).status_code == 409
    t = production_tables['media_runs']
    with pytest.raises(DBAPIError), service.store.engine.begin() as conn:
        conn.execute(t.update().where(t.c.id == run['id']).values(status='queued', media_id=None, finished_at=None))
