"""Independent local clips: real media, ownership, immutable history and explicit adoption."""
from urllib.parse import quote

import pytest
import sqlalchemy as sa

from tests.test_production import client, confirmed_project
from tests.test_production_contracts import board_content
from tests.test_video_files import make_video
from app.production.video_files import VideoFiles


@pytest.fixture
def local(client, tmp_path, monkeypatch):
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(tmp_path / 'local-video'))
    project = confirmed_project(client)
    base = f'/api/production/projects/{project}/storyboards'
    board = client.post(base, json={'source_version': 1, 'content': board_content()}).json()
    url = base + '/' + board['id']
    assert client.post(url + '/confirm', json={'expected_version': 1}).status_code == 200
    return client, project, board, url


def upload(local, data=None, key='local-request-key-1', **headers):
    client, _, _, url = local
    return client.post(url + '/editing/local-clips', content=make_video() if data is None else data,
        headers={'Content-Type': 'video/mp4', 'X-Expected-Version': '1',
            'X-Idempotency-Key': key, 'X-Filename': quote('本地片段.mp4'), **headers})


def test_upload_independent_clip_is_not_automatically_adopted(local):
    client, project, board, url = local
    response = upload(local)
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset['id'].startswith('local_') and asset['source'] == 'local_upload'
    assert asset['filename'] == '本地片段.mp4' and asset['applicable']
    assert asset['duration_ms'] == 1000 and asset['version'] == 1
    assert client.get(asset['media_url']).content == make_video()
    listing = client.get(url + '/editing').json()
    assert listing['selected_clips'] == [] and listing['timeline'] is None
    assert [x['id'] for x in listing['local_clips']] == [asset['id']]
    from app.models import production_tables as tables
    with client.app.state.production.engine.connect() as conn:
        for name in ('profiles', 'video_runs'):
            assert conn.execute(sa.select(sa.func.count()).select_from(tables[name])).scalar_one() == 0


def test_idempotent_replay_after_board_changes_and_changed_request_conflict(local):
    client, _, board, url = local
    asset = upload(local).json()
    assert upload(local).json()['id'] == asset['id']
    assert upload(local, data=make_video(9)).status_code == 409
    assert upload(local, **{'X-Filename': 'changed.mp4'}).status_code == 409
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    repeat = upload(local)
    assert repeat.status_code == 201 and repeat.json()['id'] == asset['id']
    assert not repeat.json()['applicable']
    assert upload(local, key='local-new-key-0001').status_code == 409
    assert client.get(asset['media_url']).status_code == 200
    assert not client.get(url + '/editing/local-clips').json()[0]['applicable']


@pytest.mark.parametrize('data,headers', [
    (b'fake movie', {}), (b'', {}), (make_video()[:100], {}),
    (make_video(), {'Content-Type': 'video/webm'}),
    (make_video(), {'Content-Type': 'application/octet-stream'}),
    (make_video(), {'X-Expected-Version': 'secret-not-version'}),
    (make_video(), {'X-Expected-Version': '-1'}),
    (make_video(), {'X-Idempotency-Key': 'secret'}),
    (make_video(), {'X-Filename': 'x' * 181}),
    (make_video(), {'X-Filename': '%FF'}),
    (make_video(), {'X-Filename': '%ZZ'}),
])
def test_upload_rejects_invalid_media_and_headers_without_echo(local, data, headers):
    result = upload(local, data=data, **headers)
    assert result.status_code == 422, result.text
    assert 'secret' not in result.text and 'Traceback' not in result.text
    client, _, _, url = local
    assert client.get(url + '/editing/local-clips').json() == []


def test_upload_sanitizes_display_filename_and_checks_scope(local):
    client, project, board, url = local
    asset = upload(local, **{'X-Filename': quote('C:\\private\\<clip>\x00.mp4')}).json()
    assert asset['filename'] == '<clip>.mp4'
    other = confirmed_project(client)
    other_base = f'/api/production/projects/{other}/storyboards'
    second = client.post(other_base, json={'source_version': 1, 'content': board_content()}).json()
    foreign = other_base + '/' + second['id'] + '/editing/local-clips/' + asset['id'] + '/media'
    assert client.get(foreign).status_code == 404
    assert client.get(asset['media_url'].replace(project, other)).status_code == 404
    same = client.post(f'/api/production/projects/{project}/storyboards',
        json={'source_version': 1, 'content': board_content()}).json()
    assert client.get(asset['media_url'].replace(board['id'], same['id'])).status_code == 404


def test_local_upload_requires_current_confirmed_board(local):
    client, _, board, url = local
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    assert upload(local, **{'X-Expected-Version': '2'}).status_code == 409
    assert client.post(url + '/confirm', json={'expected_version': 2}).status_code == 200
    assert upload(local, **{'X-Expected-Version': '2'}).status_code == 201


def test_local_clip_explicit_timeline_adoption_and_export_without_provider(local):
    client, _, _, url = local
    asset = upload(local).json()
    body = {'expected_version': 0, 'source_version': 1, 'content': {
        'clips': [{'run_id': asset['id'], 'start_ms': 0, 'end_ms': 800}]}}
    saved = client.post(url + '/editing/timeline', json=body)
    assert saved.status_code == 201, saved.text
    manifest = saved.json()['manifest']['clips'][0]
    assert manifest == {'run_id': asset['id'], 'shot_key': asset['filename'], 'source': 'local_upload',
        'filename': asset['filename'], 'output': asset['output']}
    from app.production.editing_service import EditingService
    service = EditingService(client.app.state.production)
    exported = service.create_export(local[1], local[2]['id'], {'expected_version': 1, 'idempotency_key': 'local-export-key-001'})
    assert service.run_once(renderer=lambda *args: make_video())
    assert service.exports(local[1], local[2]['id'])[0]['status'] == 'succeeded'
    assert service.media(local[1], local[2]['id'], exported['id'])[0].is_file()


def test_local_clip_checksum_tamper_prevents_media_save_and_render(local):
    client, project, board, url = local
    asset = upload(local).json()
    from app.production.editing_service import EditingService
    service = EditingService(client.app.state.production)
    saved = service.save(project, board['id'], {'expected_version': 0, 'source_version': 1,
        'content': {'clips': [{'run_id': asset['id'], 'start_ms': 0, 'end_ms': 800}]}})
    service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'local-export-key-001'})
    service.files.path(asset['output']['storage_key']).write_bytes(b'tampered')
    assert client.get(asset['media_url']).status_code == 404
    from app.production.store import InvalidProduction
    with pytest.raises(InvalidProduction):
        service.save(project, board['id'], {'expected_version': 1, 'source_version': 1,
            'content': saved['content']})
    assert service.run_once(renderer=lambda *args: pytest.fail('tampered clip must not render'))
    assert service.exports(project, board['id'])[0]['error_code'] == 'input_unavailable'


def test_local_clip_database_history_and_board_version_guard(local):
    client, project, board, url = local
    asset = upload(local).json()
    from app.models import production_tables as tables
    from sqlalchemy.exc import DBAPIError
    engine = client.app.state.production.engine
    t = tables['local_clips']
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(t.update().where(t.c.id == asset['id']).values(filename='changed.mp4'))
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(t.delete().where(t.c.id == asset['id']))
    with engine.begin() as conn:
        row = dict(conn.execute(sa.select(t).where(t.c.id == asset['id'])).mappings().one())
    row.update(id='local_' + 'f' * 32, idempotency_key='other-local-key-01', version_no=2)
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(t.insert().values(**row))


def test_upload_future_expected_version_is_conflict(local):
    assert upload(local, **{'X-Expected-Version': '99'}).status_code == 409


def test_stream_rejects_oversize_before_decode(local, monkeypatch):
    import app.production.editing_api as api
    monkeypatch.setattr(api, 'MAX_VIDEO_BYTES', 10)
    result = upload(local, data=b'x' * 11)
    assert result.status_code == 413
    assert local[0].get(local[3] + '/editing/local-clips').json() == []


def test_concurrent_identical_uploads_keep_only_the_winning_file(local):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.production.local_clips import LocalClips
    from app.production.video_files import VideoFiles
    client, project, board, _ = local
    gate = Barrier(2)
    class RacingFiles(VideoFiles):
        def put(self, data, mime):
            output = super().put(data, mime)
            gate.wait(timeout=10)
            return output
    files = RacingFiles()
    service = LocalClips(client.app.state.production, files=files)
    def perform():
        return service.upload(project, board['id'], make_video(), 'video/mp4', 1,
            'local.mp4', 'concurrent-local-key')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: perform(), range(2)))
    assert first['id'] == second['id']
    assert len(service.list(project, board['id'])) == len(list(files.root.iterdir())) == 1


def test_recheck_board_after_decode_rolls_back_new_file(local):
    from app.production.local_clips import LocalClips
    from app.production.video_files import VideoFiles
    from app.production.store import ProductionConflict
    from app.production.contracts import ReviseStoryboard
    client, project, board, _ = local
    store = client.app.state.production
    class RevisingFiles(VideoFiles):
        def put(self, data, mime):
            output = super().put(data, mime)
            store.revise_storyboard(project, board['id'], ReviseStoryboard.model_validate({
                'expected_version': 1, 'content': board['content']}))
            return output
    files = RevisingFiles()
    service = LocalClips(store, files=files)
    with pytest.raises(ProductionConflict):
        service.upload(project, board['id'], make_video(), 'video/mp4', 1, 'local.mp4', 'recheck-local-key-1')
    assert list(files.root.iterdir()) == []
    assert service.list(project, board['id']) == []


def test_database_failure_removes_only_new_upload_and_preserves_existing(local, monkeypatch):
    from app.production.local_clips import LocalClips
    client, project, board, _ = local
    asset = upload(local).json()
    service = LocalClips(client.app.state.production)
    original = service.get_owned
    def unavailable(*args):
        raise RuntimeError('private database failure')
    monkeypatch.setattr(service, 'get_owned', unavailable)
    with pytest.raises(RuntimeError):
        service.upload(project, board['id'], make_video(), 'video/mp4', 1, 'new.mp4', 'failure-local-key-1')
    monkeypatch.setattr(service, 'get_owned', original)
    assert len(service.list(project, board['id'])) == 1
    assert list(service.files.root.iterdir()) == [service.files.path(asset['output']['storage_key'])]
    assert service.media(project, board['id'], asset['id'])[0].is_file()


def test_local_assets_project_limit_and_idempotent_retry_at_limit(local):
    from uuid import uuid4
    from app.models import production_tables as tables
    client, project, board, _ = local
    asset = upload(local).json()
    store = client.app.state.production
    t = tables['local_clips']
    with store.engine.begin() as conn:
        row = dict(conn.execute(sa.select(t).where(t.c.id == asset['id'])).mappings().one())
        for i in range(99):
            conn.execute(t.insert().values(**(row | {'id': 'local_' + uuid4().hex,
                'idempotency_key': 'seed-local-key-' + str(i).zfill(4)})))
    assert upload(local).json()['id'] == asset['id']
    assert upload(local, key='limit-local-key-001').status_code == 409
    assert len(list(VideoFiles().root.iterdir())) == 1


def test_default_ffmpeg_exports_independent_local_asset(local):
    import av
    from app.production.editing_service import EditingService
    client, project, board, _ = local
    asset = upload(local).json()
    service = EditingService(client.app.state.production)
    timeline = service.save(project, board['id'], {'expected_version': 0, 'source_version': 1,
        'content': {'clips': [{'run_id': asset['id'], 'start_ms': 0, 'end_ms': 800}]}})
    task = service.create_export(project, board['id'], {'expected_version': timeline['version'],
        'idempotency_key': 'real-local-export-01'})
    assert service.run_once()
    result = service.exports(project, board['id'])[0]
    assert result['status'] == 'succeeded', result
    path, mime = service.media(project, board['id'], task['id'])
    with av.open(str(path)) as source:
        assert (source.streams.video[0].width, source.streams.video[0].height) == (1280, 720)
        assert len(list(source.decode(video=0))) == 19
    assert mime == 'video/mp4'
