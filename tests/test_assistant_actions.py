"""Closed assistant actions use real isolated storage and fake model providers."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from app.domain import CreateProject, ResumeProject
from app.production.contracts import CreateStoryboard, ModelConfig, ReviseStoryboard
from app.production.store import ProductionStore, ProductionConflict
from app.service import StoryService
from tests.test_production_contracts import board_content, model_config
from tests.test_story import FakeModel, STORY
from tests.test_shot_media import media
from tests.test_video_runtime import video
from tests.test_editing import editing
from tests.test_video_inspections import inspection


@pytest.fixture
def setup(database_url):
    from app.assistant_actions import AssistantActions
    with StoryService(database_url, FakeModel()) as stories:
        store = ProductionStore(database_url)
        try:
            actions = AssistantActions(store, stories)
            project = stories.create(CreateProject(story=STORY))
            yield actions, stories, store, project['id']
        finally:
            store.close()


def confirmed_board(stories, store, project):
    current = stories.get(project)
    stories.resume(project, ResumeProject(version=1, interrupt_id=current['interrupt']['id'], action='confirm'))
    return store.create_storyboard(project, CreateStoryboard(source_version=1, content=board_content()))


def test_creation_is_only_action_without_project(setup):
    actions, _, _, _ = setup
    snapshot = actions.context(None, {'stage': 'writer'})
    assert [a['kind'] for a in snapshot['available_actions']] == ['writer_create']
    proposal = actions.prepare(None, snapshot, {'kind': 'writer_create', 'params': {'story': STORY, 'mode': 'direct'}})
    assert proposal['available'] and not proposal['may_call_model']
    reserved = uuid4().hex
    result = actions.execute(None, proposal, uuid4().hex, reserved_project_id=reserved)
    assert result['project_id'] == reserved
    assert actions.execute(None, proposal, uuid4().hex, reserved_project_id=reserved)['project_id'] == reserved


def test_snapshot_has_saved_state_bounded_and_safe_profile(setup):
    actions, _, store, project = setup
    store.create_profile(ModelConfig(**model_config()))
    snapshot = actions.context(project, {'stage': 'writer', 'selection': '我的选择', 'workspace_dirty': True})
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert len(encoded) <= 48000
    assert snapshot['project']['state']['draft'] == STORY
    assert snapshot['project']['interrupt']['id']
    assert snapshot['workspace_dirty'] is True
    assert 'example.test' not in encoded and 'FP_PLANNER_KEY' not in encoded
    assert snapshot['semantic_video_verified'] is False
    assert snapshot['fingerprint'] != actions.context(project, {'stage': 'writer'})['fingerprint']


@pytest.mark.parametrize('kind,params', [('writer_confirm', {}), ('run_code', {'code': 'x'}),
    ('writer_revise', {'feedback': '补充', 'arbitrary_url': 'https://evil.test'})])
def test_closed_actions_reject_unknown_kind_and_fields(setup, kind, params):
    actions, _, _, project = setup
    with pytest.raises(ValueError):
        actions.prepare(project, actions.context(project, {'stage': 'writer'}), {'kind': kind, 'params': params})


def test_writer_resume_pins_interrupt_and_preserves_quota(setup):
    actions, stories, _, project = setup
    snapshot = actions.context(project, {'stage': 'writer'})
    proposal = actions.prepare(project, snapshot, {'kind': 'writer_revise', 'params': {'feedback': '补充钥匙归还过程'}})
    assert proposal['params']['version'] == 1
    assert proposal['params']['interrupt_id'] == snapshot['project']['interrupt']['id']
    result = actions.execute(project, proposal, uuid4().hex)
    assert result['result']['state']['version'] == 2
    assert stories.get(project)['calls_used'] == 4
    with pytest.raises((ValueError, ProductionConflict)):
        actions.execute(project, proposal, uuid4().hex)


def test_board_revision_scope_versions_and_pure_preview(setup):
    actions, stories, store, project = setup
    board = confirmed_board(stories, store, project)
    context = {'stage': 'storyboard', 'storyboard_id': board['id'], 'shot_key': 'shot-1'}
    snapshot = actions.context(project, context)
    content = deepcopy(board['content'])
    content['shots'][0]['camera_motion'] = '固定'
    proposal = actions.prepare(project, snapshot, {'kind': 'storyboard_revise', 'params': {'content': content}})
    assert proposal['params']['expected_version'] == 1
    assert store.get_storyboard(project, board['id'])['version'] == 1
    assert 'camera_motion' in json.dumps(proposal['preview'])
    result = actions.execute(project, proposal, uuid4().hex)
    assert result['result']['version'] == 2
    with pytest.raises(ValueError):
        actions.prepare(project, actions.context(project, context), {'kind': 'storyboard_revise',
            'params': {'content': content, 'expected_version': 1}})
    with pytest.raises(ValueError):
        actions.prepare(project, snapshot, {'kind': 'storyboard_revise',
            'params': {'content': content, 'storyboard_id': uuid4().hex}})


def test_reserved_story_identity_is_trusted_only_and_recovers_existing(setup):
    _, stories, _, _ = setup
    with pytest.raises(ValueError):
        stories.create(CreateProject(story=STORY, mode='direct'), project_id='../other')
    identity = uuid4().hex
    created = stories.create(CreateProject(story=STORY, mode='direct'), project_id=identity)
    recovered = stories.create(CreateProject(story='different', mode='direct'), project_id=identity)
    assert recovered == created


def test_missing_profile_is_unavailable_and_does_not_create_run(setup):
    actions, stories, store, project = setup
    confirmed_board(stories, store, project)
    snapshot = actions.context(project, {'stage': 'storyboard'})
    proposal = actions.prepare(project, snapshot, {'kind': 'storyboard_generate', 'params': {'target_shots': 1}})
    assert not proposal['available'] and proposal['unavailable_reason']
    with pytest.raises(ValueError):
        actions.execute(project, proposal, uuid4().hex)


@pytest.mark.parametrize('field', ['storyboard_id', 'run_id'])
def test_routing_fields_cannot_bypass_writer_contract(setup, field):
    actions, _, _, project = setup
    with pytest.raises(ValueError):
        actions.prepare(project, actions.context(project, {'stage': 'writer'}),
            {'kind': 'writer_revise', 'params': {'feedback': '补充细节', field: uuid4().hex}})


def test_generation_and_review_execute_real_services_with_fake_providers(setup):
    from app.production.generation import StoryboardGenerator
    from app.production.reviews import StoryboardReviewer
    from tests.test_storyboard_generation import Planner

    class ReviewPlanner:
        def generate(self, config, messages):
            return {'schema_version': 1, 'issues': []}, {}

    actions, stories, store, project = setup
    confirmed_board(stories, store, project)
    text = store.create_profile(ModelConfig(**model_config()))
    review = store.create_profile(ModelConfig(**(model_config() | {'purpose': 'review'})))
    actions.generator = StoryboardGenerator(store, Planner())
    actions.reviewer = StoryboardReviewer(store, ReviewPlanner())
    snapshot = actions.context(project, {'stage': 'storyboard'})
    proposal = actions.prepare(project, snapshot, {'kind': 'storyboard_generate',
        'params': {'profile': {'profile_id': text['id'], 'version': 1}, 'target_shots': 1}})
    assert proposal['available'] and proposal['execution_model']['model'] == 'model-a'
    done = actions.execute(project, proposal, uuid4().hex)
    assert done['result']['status'] == 'succeeded'
    board_id = done['storyboard_id']
    snapshot = actions.context(project, {'stage': 'storyboard', 'storyboard_id': board_id})
    proposal = actions.prepare(project, snapshot, {'kind': 'storyboard_review',
        'params': {'profile': {'profile_id': review['id'], 'version': 1}}})
    done = actions.execute(project, proposal, uuid4().hex)
    assert done['result']['status'] == 'succeeded'
    assert not store.get_storyboard(project, board_id)['confirmed']


def test_compacted_context_is_bounded_and_cannot_propose_writes(setup):
    actions, stories, _, project = setup
    project = stories.create(CreateProject(story='长篇故事' * 4000))['id']
    snapshot = actions.context(project, {'stage': 'writer'})
    assert len(json.dumps(snapshot, ensure_ascii=False)) <= 24000
    assert snapshot['truncated'] is True
    proposal = actions.prepare(project, snapshot, {'kind': 'writer_revise', 'params': {'feedback': '补充'}})
    assert not proposal['available']


def test_timeline_preview_rejects_foreign_clip_before_execution(setup):
    actions, stories, store, project = setup
    board = confirmed_board(stories, store, project)
    store.confirm_storyboard(project, board['id'], 1)
    snapshot = actions.context(project, {'stage': 'editing', 'storyboard_id': board['id']})
    with pytest.raises(ValueError):
        actions.prepare(project, snapshot, {'kind': 'timeline_save', 'params': {'content': {
            'clips': [{'run_id': uuid4().hex, 'start_ms': 0, 'end_ms': 1000}]}}})


def test_image_queue_select_and_metadata_never_reads_pixels(media, monkeypatch):
    from app.assistant_actions import AssistantActions
    from tests.test_shot_media import Images
    client, service, project, board, request, _ = media
    actions = AssistantActions(service.store, client.app.state.stories)
    actions.media = service
    monkeypatch.setenv('FP_PLANNER_KEY', 'fake-local-key')
    context = {'stage': 'storyboard', 'storyboard_id': board['id'], 'shot_key': 'shot-1'}
    proposal = actions.prepare(project, actions.context(project, context), {'kind': 'image_generate',
        'params': {'profile': request.profile.model_dump()}})
    queued = actions.execute(project, proposal, uuid4().hex)['result']
    assert queued['status'] == 'queued'
    assert service.run_once(adapter=Images())
    snapshot = actions.context(project, context)
    encoded = json.dumps(snapshot, ensure_ascii=False)
    assert 'storage_key' not in encoded and 'fake-local-key' not in encoded
    assert 'base64' not in encoded and snapshot['semantic_video_verified'] is False
    proposal = actions.prepare(project, snapshot, {'kind': 'image_select', 'params': {'run_id': queued['id']}})
    assert actions.execute(project, proposal, uuid4().hex)['result']['selected'] is True


def test_timeline_and_export_preserve_saved_versions_and_never_accept_output(editing):
    from app.assistant_actions import AssistantActions
    client, service, runtime, project, board, run, _ = editing
    actions = AssistantActions(service.store, client.app.state.stories)
    actions.editing, actions.video = service, runtime
    context = {'stage': 'editing', 'storyboard_id': board['id']}
    proposal = actions.prepare(project, actions.context(project, context), {'kind': 'timeline_save', 'params': {
        'content': {'clips': [{'run_id': run['id'], 'start_ms': 0, 'end_ms': 800}]}}})
    assert proposal['params']['expected_version'] == 0
    saved = actions.execute(project, proposal, uuid4().hex)['result']
    assert saved['version'] == 1
    proposal = actions.prepare(project, actions.context(project, context), {'kind': 'export_create', 'params': {}})
    assert proposal['params']['expected_version'] == 1
    queued = actions.execute(project, proposal, uuid4().hex)['result']
    assert queued['status'] == 'queued' and queued['accepted'] is False


def test_video_selection_and_inspection_produce_evidence_without_semantic_approval(inspection):
    from app.assistant_actions import AssistantActions
    client, service, runtime, project, board, run, _ = inspection
    actions = AssistantActions(service.store, client.app.state.stories)
    actions.video, actions.inspections = runtime, service
    context = {'stage': 'storyboard', 'storyboard_id': board['id'], 'shot_key': 'shot-1'}
    snapshot = actions.context(project, context)
    assert snapshot['videos'][0]['metadata']['width'] == 64
    assert snapshot['semantic_video_verified'] is False
    proposal = actions.prepare(project, snapshot, {'kind': 'video_select', 'params': {'run_id': run}})
    assert actions.execute(project, proposal, uuid4().hex)['result']['selected'] is True
    proposal = actions.prepare(project, actions.context(project, context), {'kind': 'video_inspect',
        'params': {'run_id': run, 'count': 3}})
    report = actions.execute(project, proposal, uuid4().hex)['result']
    assert len(report['frames']) == 3 and report['content_status'] == 'pending'
    assert report['technical']['semantic_review'] == 'not_configured'
