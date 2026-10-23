"""Postproduction contracts and isolated PostgreSQL persistence with real local media."""
import io
import wave

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from app.production.editing_contracts import TimelineContent, TimelineRequest, ExportRequest
from app.production.editing_service import EditingService
from app.production.store import ProductionConflict, InvalidProduction
from app.production.video_files import VideoFiles
from app.production.video_input import VideoPoll
from tests.test_video_runtime import video, make_due
from tests.test_shot_media import media
from tests.test_video_files import make_video


def content(run='a' * 32):
    return {'preset': 'landscape', 'clips': [{'run_id': run, 'start_ms': 0, 'end_ms': 800}],
            'subtitles': [], 'audio_tracks': []}


@pytest.mark.parametrize('change', [
    {'clips': []}, {'clips': [{'run_id': 'x', 'start_ms': 0, 'end_ms': 199}]},
    {'subtitles': [{'start_ms': 0, 'end_ms': 801, 'text': '越界'}]},
    {'audio_tracks': [{'asset_id': 'x', 'offset_ms': 800, 'gain': 1, 'loop': False}]},
    {'path': 'C:/private.mp4'}, {'clips': [{'run_id': 'x', 'start_ms': 0, 'end_ms': 800, 'gain': float('nan')}]},
])
def test_timeline_rejects_invalid_intervals_or_uncontrolled_paths(change):
    with pytest.raises(ValidationError):
        TimelineContent.model_validate(content() | change)


@pytest.fixture
def editing(video, tmp_path):
    client, runtime, adapter, project, board, request, url = video
    runtime.files = VideoFiles(tmp_path / 'video')
    run = runtime.create(project, board['id'], request)
    runtime.run_once(); make_due(runtime, run['id'])
    adapter.result = VideoPoll('succeeded', make_video(), 'video/mp4')
    runtime.run_once()
    runtime.select(project, board['id'], run['id'], 1)
    service = EditingService(runtime.store, files=runtime.files, audio_root=tmp_path / 'audio')
    return client, service, runtime, project, board, run, url


def save(editing):
    _, service, _, project, board, run, _ = editing
    return service.save(project, board['id'], {'expected_version': 0, 'source_version': 1, 'content': content(run['id'])})


def test_timeline_immutable_versions_optimistic_lock_and_duration(editing):
    _, service, _, project, board, run, _ = editing
    first = save(editing)
    assert first['version'] == 1 and first['applicable']
    with pytest.raises(ProductionConflict):
        save(editing)
    second = service.save(project, board['id'], {'expected_version': 1, 'source_version': 1, 'content': content(run['id'])})
    assert second['version'] == 2
    assert service.list(project, board['id'], 1)['timeline']['id'] == first['id']
    too_long = content(run['id']); too_long['clips'][0]['end_ms'] = 1001
    with pytest.raises(InvalidProduction):
        service.save(project, board['id'], {'expected_version': 2, 'source_version': 1, 'content': too_long})
    from app.models import production_tables as tables
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError), service.store.engine.begin() as conn:
        conn.execute(tables['editing_timelines'].update().values(content=content()))


def test_export_idempotency_success_manual_accept_and_tamper(editing):
    _, service, _, project, board, _, _ = editing
    timeline = save(editing)
    request = {'expected_version': timeline['version'], 'idempotency_key': 'export-request-key-1'}
    task = service.create_export(project, board['id'], request)
    assert service.create_export(project, board['id'], request)['id'] == task['id']
    assert service.run_once(renderer=lambda *args: make_video())
    assert not service.run_once()
    row = service.exports(project, board['id'])[0]
    assert row['status'] == 'succeeded' and not row['accepted']
    assert service.media(project, board['id'], row['id'])[0].read_bytes() == make_video()
    assert service.accept(project, board['id'], row['id'], {'comment': '人工检查通过'})['accepted']
    service.files.path(row['output']['storage_key']).write_bytes(b'tampered')
    with pytest.raises(KeyError):
        service.media(project, board['id'], row['id'])


def test_stale_timeline_readable_but_export_refused(editing):
    client, service, _, project, board, _, url = editing
    save(editing)
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    assert not service.list(project, board['id'])['timeline']['applicable']
    with pytest.raises(ProductionConflict):
        service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, 'wb') as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(8000)
        target.writeframes(b'\0\0' * 8000)
    return out.getvalue()


def test_audio_decode_scope_and_invalid_input(editing):
    _, service, _, project, board, _, _ = editing
    saved = service.upload_audio(project, board['id'], wav_bytes())
    assert saved['duration_ms'] == 1000
    assert service.audio_media(project, board['id'], saved['id'])[0].read_bytes() == wav_bytes()
    with pytest.raises(InvalidProduction):
        service.upload_audio(project, board['id'], b'not wav')
    from tests.test_production import confirmed_project
    other = confirmed_project(editing[0])
    with pytest.raises(KeyError):
        service.audio_media(other, board['id'], saved['id'])


def test_running_abandon_ignores_late_render_and_never_retries(editing):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _, service, _, project, board, _, _ = editing
    save(editing)
    task = service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    entered, release = Event(), Event()
    def render(*args):
        entered.set(); assert release.wait(10)
        return make_video()
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(service.run_once, render)
        try:
            assert entered.wait(10)
            assert not service.run_once(renderer=render)
            assert service.abandon(project, board['id'], task['id'])['status'] == 'unknown'
        finally:
            release.set()
        assert running.result(timeout=10)
    assert service.exports(project, board['id'])[0]['status'] == 'unknown'
    assert not service.run_once()


def test_queued_export_rechecks_source_without_rendering(editing):
    client, service, _, project, board, _, url = editing
    save(editing)
    service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    calls = []
    assert service.run_once(renderer=lambda *args: calls.append(args))
    assert not calls
    assert service.exports(project, board['id'])[0]['error_code'] == 'source_changed'


def test_queued_export_rechecks_input_checksum_and_does_not_render(editing):
    _, service, runtime, project, board, run, _ = editing
    save(editing)
    service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    output = runtime.list(project, board['id'])['runs'][0]['output']
    service.files.path(output['storage_key']).write_bytes(b'corrupt')
    calls = []
    service.run_once(renderer=lambda *args: calls.append(args))
    assert not calls
    assert service.exports(project, board['id'])[0]['error_code'] == 'input_unavailable'


@pytest.mark.parametrize('failure', ['render', 'invalid_output'])
def test_render_failure_is_sanitized_terminal_and_not_retried(editing, failure):
    _, service, _, project, board, _, _ = editing
    save(editing)
    service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    def render(*args):
        if failure == 'render':
            raise RuntimeError('C:/private/path credential')
        return b'not a movie'
    assert service.run_once(renderer=render)
    task = service.exports(project, board['id'])[0]
    assert task['status'] == 'failed'
    assert 'private' not in str(task)
    assert not service.run_once(renderer=render)
    with pytest.raises(KeyError):
        service.accept(project, board['id'], task['id'])


def test_restart_leaves_interrupted_render_explicitly_unknown_until_abandoned(editing):
    _, service, _, project, board, _, _ = editing
    save(editing)
    task = service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    class ProcessStopped(BaseException):
        pass
    def stop(*args):
        raise ProcessStopped()
    with pytest.raises(ProcessStopped):
        service.run_once(renderer=stop)
    restored = EditingService(service.store, files=service.files, audio_root=service.audio_root)
    assert restored.exports(project, board['id'])[0]['status'] == 'running'
    assert not restored.run_once(renderer=stop)
    assert restored.abandon(project, board['id'], task['id'])['status'] == 'unknown'


def test_audio_tracks_bound_to_pinned_owned_assets(editing):
    _, service, _, project, board, run, _ = editing
    audio = service.upload_audio(project, board['id'], wav_bytes())
    body = content(run['id'])
    body['audio_tracks'] = [{'asset_id': audio['id'], 'offset_ms': 0, 'gain': .5, 'loop': True}]
    timeline = service.save(project, board['id'], {'expected_version': 0, 'source_version': 1, 'content': body})
    assert timeline['manifest']['audio'][0]['output']['checksum'] == audio['output']['checksum']
    service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    received = []
    def render(content, clips, tracks):
        assert clips[0]['path'].is_file() and tracks[0]['path'].is_file()
        assert tracks[0]['gain'] == .5 and tracks[0]['loop']
        received.append(content)
        return make_video()
    assert service.run_once(renderer=render)
    assert received[0]['audio_tracks'][0]['loop']
    assert service.exports(project, board['id'])[0]['status'] == 'succeeded'


def test_wrong_project_and_changed_idempotency_cannot_access_export(editing):
    client, service, _, project, board, _, _ = editing
    save(editing)
    task = service.create_export(project, board['id'], {'expected_version': 1, 'idempotency_key': 'export-request-key-1'})
    with pytest.raises(ProductionConflict):
        service.create_export(project, board['id'], {'expected_version': 2, 'idempotency_key': 'export-request-key-1'})
    from tests.test_production import confirmed_project
    other = confirmed_project(client)
    for operation in (lambda: service.list(other, board['id']), lambda: service.exports(other, board['id']),
            lambda: service.abandon(other, board['id'], task['id']), lambda: service.media(other, board['id'], task['id'])):
        with pytest.raises(KeyError):
            operation()
