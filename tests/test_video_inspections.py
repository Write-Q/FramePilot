"""Real local video evidence and append-only manual review, without model calls."""
import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from tests.test_shot_media import media
from tests.test_video_runtime import video, make_due
from tests.test_video_files import make_video
from app.models import production_tables as tables
from app.production.store import ProductionConflict


def test_inspection_request_contract():
    from app.production.inspection_contracts import CreateInspection, ManualReview
    assert CreateInspection(idempotency_key='inspection-key-0001').count == 8
    for count in (0, 13, True):
        with pytest.raises(ValidationError):
            CreateInspection(idempotency_key='inspection-key-0001', count=count)
    with pytest.raises(ValidationError):
        ManualReview(expected_version=1, idempotency_key='inspection-note-001', decision='needs_revision')
    with pytest.raises(ValidationError):
        ManualReview(expected_version=1, idempotency_key='inspection-note-001', decision='reviewed',
            findings=[{'start_ms': 9, 'end_ms': 1, 'severity': 'high', 'description': '倒序'}])


@pytest.fixture
def inspection(video, tmp_path, monkeypatch):
    from app.production.video_files import VideoFiles
    from app.production.media_io import MediaFiles
    from app.production.inspection import InspectionService
    client, runtime, adapter, project, board, request, url = video
    runtime.files = VideoFiles(tmp_path / 'videos')
    run = runtime.create(project, board['id'], request)
    runtime.run_once()
    make_due(runtime, run['id'])
    from app.production.video_input import VideoPoll
    adapter.result = VideoPoll('succeeded', make_video(), 'video/mp4')
    runtime.run_once()
    service = InspectionService(runtime.store, runtime=runtime, frames=MediaFiles(tmp_path / 'evidence'))
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(runtime.files.root))
    monkeypatch.setenv('FRAMEPILOT_MEDIA_ROOT', str(service.frames.root))
    return client, service, runtime, project, board, run['id'], url


def create(inspection, **updates):
    _, service, _, project, board, run, _ = inspection
    return service.create(project, board['id'], run, {'idempotency_key': 'inspection-key-0001', **updates})


def note_request(**updates):
    return {'expected_version': 1, 'idempotency_key': 'inspection-note-001', 'decision': 'reviewed', **updates}


def test_real_evidence_is_pending_and_does_not_select(inspection):
    _, service, runtime, project, board, run, _ = inspection
    report = create(inspection, count=3)
    assert report['content_status'] == 'pending' and report['applicable']
    assert report['technical']['actual'] == {'width': 64, 'height': 36, 'duration_ms': 1000}
    assert report['technical']['planned'] == {'duration_ms': 4000, 'aspect_ratio': '16:9'}
    assert 'duration_mismatch' in report['technical']['warnings']
    assert len(report['frames']) == 3 and report['notes'] == []
    assert 'storage_key' not in str(report) and 'evidence' not in str(report)
    from PIL import Image
    for index, frame in enumerate(report['frames']):
        assert 0 <= frame['at_ms'] < 1000
        assert frame['url'].endswith(f'/inspections/{report["id"]}/frames/{index}')
        path, mime = service.frame(project, board['id'], run, report['id'], index)
        assert mime == 'image/jpeg'
        with Image.open(path) as image:
            assert image.size == (64, 36)
    assert not runtime.list(project, board['id'])['runs'][0]['selected']
    assert service.list(project, board['id'], run)['reports'][0]['id'] == report['id']


def test_create_and_notes_idempotency_append_only(inspection):
    _, service, runtime, project, board, run, _ = inspection
    report = create(inspection)
    assert create(inspection)['id'] == report['id']
    with pytest.raises(ProductionConflict):
        create(inspection, count=2)
    request = note_request(comment='人工观看完成')
    reviewed = service.note(project, board['id'], run, report['id'], request)
    assert reviewed['content_status'] == 'reviewed' and len(reviewed['notes']) == 1
    assert len(service.note(project, board['id'], run, report['id'], request)['notes']) == 1
    with pytest.raises(ProductionConflict):
        service.note(project, board['id'], run, report['id'], request | {'comment': 'changed'})
    revision = note_request(idempotency_key='inspection-note-002', decision='needs_revision',
        findings=[{'start_ms': 100, 'end_ms': 400, 'severity': 'high', 'description': '需要调整动作'}])
    changed = service.note(project, board['id'], run, report['id'], revision)
    assert changed['content_status'] == 'needs_revision' and len(changed['notes']) == 2
    assert not runtime.list(project, board['id'])['runs'][0]['selected']
    for key in ('video_inspections', 'video_inspection_notes'):
        with pytest.raises(DBAPIError), runtime.store.engine.begin() as conn:
            conn.execute(tables[key].delete().where(tables[key].c.project_id == project))
        with pytest.raises(DBAPIError), runtime.store.engine.begin() as conn:
            conn.execute(tables[key].update().where(tables[key].c.project_id == project)
                .values(idempotency_key='overwritten-history'))


def test_stale_reports_readable_but_notes_and_new_reports_rejected(inspection):
    client, service, _, project, board, run, url = inspection
    report = create(inspection)
    service.note(project, board['id'], run, report['id'], note_request())
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    old = service.list(project, board['id'], run)['reports'][0]
    assert not old['applicable'] and len(old['notes']) == 1
    assert service.frame(project, board['id'], run, report['id'], 0)[0].exists()
    with pytest.raises(ProductionConflict):
        service.note(project, board['id'], run, report['id'], note_request(idempotency_key='inspection-note-002'))
    with pytest.raises(ProductionConflict):
        create(inspection, idempotency_key='inspection-key-0002')


def test_timestamps_checksum_ownership_and_frame_integrity(inspection):
    client, service, runtime, project, board, run, _ = inspection
    report = create(inspection)
    bad = note_request(findings=[{'start_ms': 0, 'end_ms': 1001, 'severity': 'low', 'description': '越界'}])
    with pytest.raises(ProductionConflict):
        service.note(project, board['id'], run, report['id'], bad)
    from tests.test_production import confirmed_project
    other = confirmed_project(client)
    with pytest.raises(KeyError):
        service.list(other, board['id'], run)
    with pytest.raises(KeyError):
        service.frame(other, board['id'], run, report['id'], 0)
    with pytest.raises(KeyError):
        service.frame(project, board['id'], run, report['id'], -1)
    path, _ = service.frame(project, board['id'], run, report['id'], 0)
    path.write_bytes(b'broken')
    with pytest.raises(KeyError):
        service.frame(project, board['id'], run, report['id'], 0)
    output = runtime.list(project, board['id'])['runs'][0]['output']
    runtime.files.path(output['storage_key']).write_bytes(b'broken')
    assert not service.list(project, board['id'], run)['reports'][0]['applicable']
    with pytest.raises(ProductionConflict):
        service.note(project, board['id'], run, report['id'], note_request())


def test_report_and_note_limits_replays_still_work(inspection, monkeypatch):
    import app.production.inspection as module
    monkeypatch.setattr(module, 'MAX_INSPECTIONS', 1)
    monkeypatch.setattr(module, 'MAX_NOTES', 1)
    _, service, _, project, board, run, _ = inspection
    report = create(inspection)
    with pytest.raises(ProductionConflict):
        create(inspection, idempotency_key='inspection-key-0002')
    assert create(inspection)['id'] == report['id']
    service.note(project, board['id'], run, report['id'], note_request())
    with pytest.raises(ProductionConflict):
        service.note(project, board['id'], run, report['id'], note_request(idempotency_key='inspection-note-002'))
    assert len(service.note(project, board['id'], run, report['id'], note_request())['notes']) == 1


def test_bad_sample_storage_is_sanitized_without_report(inspection, monkeypatch):
    import app.production.inspection as module
    monkeypatch.setattr(module, 'sample_video', lambda *args: [{'at_ms': 0, 'data': b'not a JPEG'}])
    _, service, _, project, board, run, _ = inspection
    with pytest.raises(ProductionConflict) as caught:
        create(inspection)
    assert 'JPEG' not in str(caught.value)
    assert service.list(project, board['id'], run)['reports'] == []


def test_changed_board_during_sampling_creates_no_report_or_orphan_frames(inspection, monkeypatch):
    import app.production.inspection as module
    client, service, _, project, board, run, url = inspection
    original = module.sample_video
    def change_while_sampling(*args):
        assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
        return original(*args)
    monkeypatch.setattr(module, 'sample_video', change_while_sampling)
    with pytest.raises(ProductionConflict):
        create(inspection)
    assert service.list(project, board['id'], run)['reports'] == []
    assert not list(service.frames.root.glob('*.jpg'))


def test_parallel_replay_creates_one_report_and_cleans_unused_evidence(inspection, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import app.production.inspection as module
    _, service, _, project, board, run, _ = inspection
    original = module.sample_video
    barrier = Barrier(2)
    def simultaneous_samples(*args):
        barrier.wait(timeout=10)
        return original(*args)
    monkeypatch.setattr(module, 'sample_video', simultaneous_samples)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create, inspection, count=2), pool.submit(create, inspection, count=2)
        a, b = first.result(timeout=30), second.result(timeout=30)
    assert a['id'] == b['id']
    assert len(service.list(project, board['id'], run)['reports']) == 1
    assert len(list(service.frames.root.glob('*.jpg'))) == 2


def test_api_reports_frames_notes_and_missing_video_are_safe(inspection):
    client, service, runtime, project, board, run, url = inspection
    base = url + f'/video-runs/{run}/inspections'
    response = client.post(base, json={'idempotency_key': 'api-inspection-0001', 'count': 2})
    assert response.status_code == 201, response.text
    report = response.json()
    assert report['content_status'] == 'pending'
    assert client.get(base).json()['reports'][0]['id'] == report['id']
    frame = client.get(report['frames'][0]['url'])
    assert frame.status_code == 200 and frame.headers['content-type'] == 'image/jpeg'
    note = client.post(base + f'/{report["id"]}/notes', json=note_request())
    assert note.status_code == 201 and note.json()['content_status'] == 'reviewed'
    assert client.post(base + f'/{report["id"]}/notes', json=note_request(decision='approved')).status_code == 422
    assert client.get(base + f'/{report["id"]}/frames/-1').status_code == 404
    output = runtime.list(project, board['id'])['runs'][0]['output']
    runtime.files.path(output['storage_key']).unlink()
    assert client.post(base, json={'idempotency_key': 'api-inspection-0002'}).status_code == 409
    assert client.get(base).json()['reports'][0]['applicable'] is False


def test_database_guards_report_video_checksum_and_note_version(inspection):
    from uuid import uuid4
    _, service, runtime, project, board, run, _ = inspection
    report = create(inspection)
    r, n = tables['video_inspections'], tables['video_inspection_notes']
    with runtime.store.engine.connect() as conn:
        original = dict(conn.execute(sa.select(r).where(r.c.id == report['id'])).mappings().one())
    wrong = original | {'id': uuid4().hex, 'idempotency_key': 'different-inspection-key', 'video_checksum': '0' * 64}
    with pytest.raises(DBAPIError), runtime.store.engine.begin() as conn:
        conn.execute(r.insert().values(**wrong))
    with pytest.raises(DBAPIError), runtime.store.engine.begin() as conn:
        conn.execute(n.insert().values(project_id=project, run_id=run, inspection_id=report['id'],
            idempotency_key='db-note-version-0001', request_sha256='0'*64,
            expected_version=2, decision='reviewed', findings=[], comment=''))
