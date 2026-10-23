import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from app.models import production_tables as tables
from app.production.chat import PlannerError
from app.production.store import InvalidProduction, ProductionConflict
from app.production.video_input import VideoSubmission, VideoPoll
from app.production.video_runtime import VideoRuntime, VideoRequest
from tests.test_shot_media import media, Images
from tests.test_production_contracts import model_config


class Adapter:
    def __init__(self):
        self.submits, self.polls = [], []
        self.result = VideoPoll('pending')

    def submit(self, config, packet, first_frame):
        self.submits.append((config, packet, first_frame))
        return VideoSubmission('external-video-1')

    def poll(self, config, external_id):
        self.polls.append(external_id)
        return self.result


class RejectingFiles:
    """Injected test validator rejects all fake bytes; no fake video accepted."""
    validated_video = True

    def put(self, data, mime_type):
        raise ValueError('not a decoded video; private details')


@pytest.fixture
def video(media):
    client, images, project, board, image_request, url = media
    image = images.create(project, board['id'], image_request)
    images.run_once(adapter=Images())
    images.select(project, board['id'], image['id'], 1)
    config = model_config() | {'purpose': 'video', 'adapter': 'test_video',
                              'capabilities': {'first_frame': True, 'max_duration_ms': 10000}}
    profile = client.post('/api/production/model-profiles', json=config).json()
    request = VideoRequest(expected_version=1, shot_key='shot-1',
        profile={'profile_id': profile['id'], 'version': 1}, idempotency_key='video-request-key-1')
    adapter = Adapter()
    runtime = VideoRuntime(images.store, adapters={'test_video': adapter}, files=RejectingFiles())
    return client, runtime, adapter, project, board, request, url


def snapshot(video):
    _, runtime, _, project, board, _, _ = video
    return runtime.list(project, board['id'])['runs'][0]


def make_due(runtime, identity):
    # Exercise public recovery to make a pending query due, without mutating frozen inputs.
    t = tables['video_runs']
    with runtime.store.engine.begin() as conn:
        conn.execute(t.update().where(t.c.id == identity, t.c.status == 'submitted').values(
            status='polling', claim_id='test-recovery-claim', next_poll_at=None))
    runtime.recover_poll(*_scope(runtime, identity))


def _scope(runtime, identity):
    t = tables['video_runs']
    with runtime.store.engine.connect() as conn:
        row = conn.execute(sa.select(t).where(t.c.id == identity)).mappings().one()
    return row['project_id'], row['manifest']['storyboard_id'], identity


def test_request_cannot_supply_packet_or_first_frame():
    with pytest.raises(ValidationError):
        VideoRequest(expected_version=1, shot_key='shot-1', profile={'profile_id': 'p', 'version': 1},
                     idempotency_key='video-request-key-1', first_frame={'media_id': 'forged'})


def test_unregistered_adapter_refused_before_queue(video):
    _, runtime, _, project, board, request, _ = video
    runtime.adapters.clear()
    with pytest.raises(InvalidProduction):
        runtime.create(project, board['id'], request)
    assert runtime.list(project, board['id'])['runs'] == []


def test_submit_persist_then_poll_and_no_implicit_resubmission(video):
    _, runtime, adapter, project, board, request, _ = video
    run = runtime.create(project, board['id'], request)
    assert runtime.create(project, board['id'], request)['id'] == run['id']
    assert runtime.run_once()
    saved = snapshot(video)
    assert saved['status'] == 'submitted'
    assert saved['external_id'] == 'external-video-1'
    assert len(adapter.submits) == 1 and not adapter.polls
    assert not runtime.run_once()  # bounded poll cadence
    make_due(runtime, run['id'])
    assert runtime.run_once()
    assert adapter.polls == ['external-video-1']
    assert len(adapter.submits) == 1 and snapshot(video)['status'] == 'submitted'
    assert adapter.submits[0][2].startswith(b'\x89PNG')


def test_no_validator_stops_before_provider(video):
    _, runtime, adapter, project, board, request, _ = video
    runtime.files = None
    runtime.create(project, board['id'], request)
    assert runtime.run_once()
    assert snapshot(video)['status'] == 'failed'
    assert snapshot(video)['error_code'] == 'validator_unavailable'
    assert not adapter.submits


def test_submit_timeout_unknown_never_retried(video):
    _, runtime, adapter, project, board, request, _ = video
    def timeout(*args):
        raise PlannerError('private credential', 'outcome_unknown')
    adapter.submit = timeout
    runtime.create(project, board['id'], request)
    runtime.run_once()
    row = snapshot(video)
    assert row['status'] == 'unknown' and 'private' not in row['error']
    assert not runtime.run_once()


def test_poll_error_keeps_id_and_respects_cadence(video):
    _, runtime, adapter, project, board, request, _ = video
    run = runtime.create(project, board['id'], request)
    runtime.run_once()
    make_due(runtime, run['id'])
    def timeout(*args):
        raise PlannerError('private token', 'outcome_unknown')
    adapter.poll = timeout
    runtime.run_once()
    row = snapshot(video)
    assert row['status'] == 'submitted' and row['external_id'] == 'external-video-1'
    assert row['error_code'] == 'poll_error' and 'private' not in row['error']
    assert not runtime.run_once()


def test_fake_video_never_succeeds_or_enters_media_table(video):
    _, runtime, adapter, project, board, request, _ = video
    from app.models import domain_tables
    run = runtime.create(project, board['id'], request)
    runtime.run_once()
    make_due(runtime, run['id'])
    adapter.result = VideoPoll('succeeded', b'fake video', 'video/mp4')
    runtime.run_once()
    row = snapshot(video)
    assert row['status'] == 'failed' and row['output'] is None
    assert row['error_code'] == 'invalid_output'
    with runtime.store.engine.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(domain_tables['media_files'])).scalar_one() == 1


def test_cancel_and_changed_idempotency(video):
    _, runtime, adapter, project, board, request, _ = video
    run = runtime.create(project, board['id'], request)
    with pytest.raises(ProductionConflict):
        runtime.create(project, board['id'], request.model_copy(update={'shot_key': 'other'}))
    assert runtime.cancel(project, board['id'], run['id'])['status'] == 'cancelled'
    assert not runtime.run_once() and not adapter.submits


def test_stale_queue_never_submits_and_is_not_selectable(video):
    client, runtime, adapter, project, board, request, url = video
    run = runtime.create(project, board['id'], request)
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    runtime.run_once()
    assert snapshot(video)['error_code'] == 'source_changed' and not adapter.submits
    with pytest.raises(ProductionConflict):
        runtime.select(project, board['id'], run['id'], 2)


def test_submitting_abandon_and_polling_recover_are_explicit(video):
    _, runtime, _, project, board, request, _ = video
    t = tables['video_runs']
    run = runtime.create(project, board['id'], request)
    with runtime.store.engine.begin() as conn:
        conn.execute(t.update().where(t.c.id == run['id']).values(status='submitting', claim_id='test-claim', started_at=sa.func.now()))
    assert not runtime.run_once()
    assert runtime.abandon(project, board['id'], run['id'])['status'] == 'unknown'
    with pytest.raises(ProductionConflict):
        runtime.recover_poll(project, board['id'], run['id'])


def test_wrong_project_cannot_access_or_cancel(video):
    client, runtime, _, project, board, request, _ = video
    from tests.test_production import confirmed_project
    run = runtime.create(project, board['id'], request)
    other = confirmed_project(client)
    with pytest.raises(KeyError):
        runtime.list(other, board['id'])
    with pytest.raises(KeyError):
        runtime.cancel(other, board['id'], run['id'])


class ContractOnlySink:
    """Test double for DB success wiring, NOT a video decoder or production sink."""
    validated_video = True

    def put(self, data, mime_type):
        import hashlib
        return {'storage_key': 'test-fixture.mp4', 'checksum': hashlib.sha256(data).hexdigest(),
                'size_bytes': len(data), 'mime_type': mime_type,
                'metadata': {'width': 16, 'height': 9, 'duration_ms': 4000, 'private_path': 'C:/secret/video'},
                'private_path': 'C:/secret/video'}


def test_success_selection_contract_with_explicit_test_sink_not_quality_evidence(video):
    _, runtime, adapter, project, board, request, _ = video
    runtime.files = ContractOnlySink()
    run = runtime.create(project, board['id'], request)
    runtime.run_once()
    make_due(runtime, run['id'])
    adapter.result = VideoPoll('succeeded', b'contract-only-no-real-video', 'video/mp4')
    runtime.run_once()
    saved = snapshot(video)
    assert saved['status'] == 'succeeded' and not saved['selected']
    assert 'secret' not in str(saved['output'])
    assert runtime.select(project, board['id'], run['id'], 1)['selected']
    assert runtime.select(project, board['id'], run['id'], 1)['selected']
    from sqlalchemy.exc import DBAPIError
    t = tables['video_runs']
    with pytest.raises(DBAPIError), runtime.store.engine.begin() as conn:
        conn.execute(t.update().where(t.c.id == run['id']).values(status='queued', output=None, finished_at=None))


def test_cancelled_attempts_still_count_toward_project_budget(video, monkeypatch):
    import app.production.video_runtime as module
    monkeypatch.setattr(module, 'MAX_VIDEO_RUNS', 1)
    _, runtime, _, project, board, request, _ = video
    run = runtime.create(project, board['id'], request)
    runtime.cancel(project, board['id'], run['id'])
    with pytest.raises(ProductionConflict):
        runtime.create(project, board['id'], request.model_copy(update={'idempotency_key': 'video-request-key-2'}))


def test_parallel_submit_and_abandon_suppresses_late_result(video):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _, runtime, adapter, project, board, request, _ = video
    entered, release = Event(), Event()
    original = adapter.submit
    def blocking(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    adapter.submit = blocking
    run = runtime.create(project, board['id'], request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(runtime.run_once)
        try:
            assert entered.wait(10)
            assert pool.submit(runtime.run_once).result(timeout=10) is False
            assert runtime.abandon(project, board['id'], run['id'])['status'] == 'unknown'
        finally:
            release.set()
        assert active.result(timeout=10)
    assert snapshot(video)['status'] == 'unknown'
    assert len(adapter.submits) == 1


def test_recovered_poll_uses_new_claim_so_old_result_cannot_overwrite(video):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    _, runtime, adapter, project, board, request, _ = video
    entered, release = Event(), Event()
    run = runtime.create(project, board['id'], request)
    runtime.run_once()
    make_due(runtime, run['id'])
    def blocking(*args):
        entered.set()
        assert release.wait(10)
        return VideoPoll('failed')
    adapter.poll = blocking
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(runtime.run_once)
        try:
            assert entered.wait(10)
            runtime.recover_poll(project, board['id'], run['id'])
            adapter.poll = lambda *args: VideoPoll('pending')
            assert pool.submit(runtime.run_once).result(timeout=10)
        finally:
            release.set()
        assert active.result(timeout=10)
    row = snapshot(video)
    assert row['status'] == 'submitted' and row['error_code'] is None
    assert row['external_id'] == 'external-video-1'
    assert len(adapter.submits) == 1
