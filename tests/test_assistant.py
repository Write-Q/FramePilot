"""Assistant lifecycle against isolated PostgreSQL; no paid provider calls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app.production.contracts import ModelConfig
from app.production.store import ProductionStore
from tests.test_production_contracts import model_config


class Actions:
    def __init__(self, store):
        self.store, self.calls, self.fingerprint = store, [], 'snapshot-1'

    def context(self, project_id, context):
        return {'fingerprint': self.fingerprint, 'stage': context['stage'], 'available_actions': ['writer_create']}

    def prepare(self, project_id, context, proposal):
        return {**proposal, 'preview': {'story': proposal['params'].get('story', '')},
                'execution_model': None, 'may_call_model': False, 'available': True,
                'unavailable_reason': None}

    def execute(self, project_id, proposal, idempotency_key, reserved_project_id=None):
        self.calls.append(idempotency_key)
        identity = project_id or reserved_project_id
        table = sa.Table('fp_projects', sa.MetaData(), autoload_with=self.store.engine)
        with self.store.engine.begin() as conn:
            if not conn.execute(sa.select(table.c.id).where(table.c.id == identity)).scalar():
                conn.execute(table.insert().values(id=identity, snapshot={'state': {}}, max_calls=10,
                                                  created_at=sa.func.now()))
        return {'project_id': identity, 'stage': 'writer', 'result': {'created': True}}


class Planner:
    def __init__(self, output=None):
        self.calls = 0
        self.output = output or {'reply': '可以创建剧本，请确认提案。', 'proposals': [
            {'kind': 'writer_create', 'title': '创建剧本', 'summary': '保存原文', 'params': {'story': '故事'}}]}

    def generate(self, config, messages):
        self.calls += 1
        return self.output, {'total_tokens': 17}


@pytest.fixture
def setup_assistant(database_url):
    from app.assistant_service import AssistantService
    store = ProductionStore(database_url)
    profile = store.create_profile(ModelConfig(**model_config()))
    actions, planner = Actions(store), Planner()
    service = AssistantService(store, actions, planner)
    yield service, store, actions, planner, profile
    store.close()


def key():
    return uuid4().hex


def create(service):
    from app.assistant_contracts import CreateThread
    return service.create(CreateThread(idempotency_key=key()))


def request(profile, revision=0, **changes):
    from app.assistant_contracts import Message
    body = dict(expected_revision=revision, text='请创建剧本', context={'stage': 'writer'},
                profile={'profile_id': profile['id'], 'version': 1}, idempotency_key=key())
    body.update(changes)
    return Message(**body)


def decision(value='accept', **changes):
    from app.assistant_contracts import Decision
    return Decision(decision=value, idempotency_key=key(), **changes)


def test_persistent_unbound_chat_accept_and_project_restore(setup_assistant):
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    req = request(profile)
    state = service.message(thread['id'], req)
    assert state['revision'] == 1 and not state['active']
    assert state['project_id'] is None and len(state['messages']) == 2
    assert service.message(thread['id'], req) == state and planner.calls == 1
    proposal = state['proposals'][0]
    accept = decision()
    result = service.decide(thread['id'], proposal['id'], accept)
    assert result['project_id'] and result['proposals'][0]['status'] == 'accepted'
    assert service.decide(thread['id'], proposal['id'], accept) == result
    assert len(actions.calls) == 1
    from app.assistant_contracts import CreateThread
    restored = service.create(CreateThread(project_id=result['project_id'], idempotency_key=key()))
    assert restored['id'] == thread['id']


def test_conflicts_reject_and_stale_context(setup_assistant):
    from app.assistant_service import AssistantConflict
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    req = request(profile)
    state = service.message(thread['id'], req)
    with pytest.raises(AssistantConflict):
        service.message(thread['id'], req.model_copy(update={'text': 'different'}))
    with pytest.raises(AssistantConflict):
        service.message(thread['id'], request(profile))
    proposal = state['proposals'][0]
    with pytest.raises(AssistantConflict):
        service.decide(thread['id'], proposal['id'], decision(workspace_dirty=True))
    actions.fingerprint = 'changed'
    with pytest.raises(AssistantConflict):
        service.decide(thread['id'], proposal['id'], decision())
    result = service.decide(thread['id'], proposal['id'], decision('reject'))
    assert result['proposals'][0]['status'] == 'rejected' and not actions.calls
    with pytest.raises(AssistantConflict):
        service.decide(thread['id'], proposal['id'], decision())


@pytest.mark.parametrize('output', [
    {'reply': 'bad', 'proposals': [{'kind': 'shell_execute', 'title': 'run', 'summary': '', 'params': {}}]},
    {'reply': 'bad', 'proposals': 'invalid'},
    {'wrong': 'secret-provider-response'},
])
def test_invalid_model_output_is_safe_and_never_executes(setup_assistant, output):
    service, store, actions, planner, profile = setup_assistant
    planner.output = output
    thread = create(service)
    result = service.message(thread['id'], request(profile))
    assert result['messages'][-1]['status'] == 'failed'
    assert not result['proposals'] and not actions.calls
    assert 'secret-provider-response' not in str(result)


def test_busy_thread_and_late_abandoned_result(setup_assistant):
    from app.assistant_service import AssistantConflict
    service, store, actions, planner, profile = setup_assistant
    entered, release = Event(), Event()
    original = planner.generate
    def blocked(config, messages):
        entered.set()
        assert release.wait(15)
        return original(config, messages)
    planner.generate = blocked
    thread = create(service)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(service.message, thread['id'], request(profile))
        assert entered.wait(10)
        active = service.read(thread['id'])
        assert active['active']
        with pytest.raises(AssistantConflict):
            service.message(thread['id'], request(profile, 1))
        service.abandon(thread['id'], active['messages'][-1]['id'])
        release.set()
        result = future.result()
    assert not result['active'] and not result['proposals']
    assert result['messages'][-1]['status'] == 'unknown'


def test_concurrent_accept_claim_executes_once(setup_assistant):
    from app.assistant_service import AssistantConflict
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    state = service.message(thread['id'], request(profile))
    proposal_id = state['proposals'][0]['id']
    entered, release = Event(), Event()
    execute = actions.execute
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return execute(*args, **kwargs)
    actions.execute = blocked
    accept = decision()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(service.decide, thread['id'], proposal_id, accept)
        assert entered.wait(10)
        assert service.decide(thread['id'], proposal_id, accept)['active']
        with pytest.raises(AssistantConflict):
            service.decide(thread['id'], proposal_id, decision())
        release.set()
        result = future.result()
    assert result['proposals'][0]['status'] == 'accepted' and len(actions.calls) == 1


def test_failure_after_project_creation_binds_thread_and_never_replays(setup_assistant):
    from app.assistant_contracts import CreateThread
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    state = service.message(thread['id'], request(profile))
    execute = actions.execute
    def partial(*args, **kwargs):
        execute(*args, **kwargs)
        raise RuntimeError('secret-provider-error')
    actions.execute = partial
    accept = decision()
    result = service.decide(thread['id'], state['proposals'][0]['id'], accept)
    assert result['project_id'] and result['proposals'][0]['status'] == 'unknown'
    assert 'secret-provider-error' not in str(result)
    assert service.decide(thread['id'], state['proposals'][0]['id'], accept) == result
    assert service.create(CreateThread(project_id=result['project_id'], idempotency_key=key()))['id'] == thread['id']
    assert len(actions.calls) == 1


def test_model_secret_echo_and_unknown_outcome_are_not_replayed(setup_assistant, monkeypatch):
    from app.production.chat import PlannerError
    service, store, actions, planner, profile = setup_assistant
    monkeypatch.setenv('FP_PLANNER_KEY', 'secret-response-must-not-be-shown')
    planner.output = {'reply': 'secret-response-must-not-be-shown', 'proposals': []}
    thread = create(service)
    failed = service.message(thread['id'], request(profile))
    assert failed['messages'][-1]['status'] == 'failed'
    assert 'secret-response-must-not-be-shown' not in str(failed)
    def unknown(config, messages):
        planner.calls += 1
        raise PlannerError('secret-error', 'outcome_unknown', {'total_tokens': 3})
    planner.generate = unknown
    req = request(profile, 1)
    result = service.message(thread['id'], req)
    assert result['messages'][-1]['status'] == 'unknown' and not result['active']
    assert service.message(thread['id'], req) == result and planner.calls == 2


def test_configured_credential_is_private_with_any_environment_name(setup_assistant, monkeypatch):
    service, store, actions, planner, profile = setup_assistant
    monkeypatch.setenv('CUSTOM_CREDENTIAL', 'opaque-credential-do-not-echo')
    config = model_config()
    config['api_key_env'] = 'CUSTOM_CREDENTIAL'
    custom = store.create_profile(ModelConfig(**config))
    planner.output = {'reply': 'opaque-credential-do-not-echo', 'proposals': []}
    thread = create(service)
    result = service.message(thread['id'], request(custom))
    assert result['messages'][-1]['status'] == 'failed'
    assert 'opaque-credential-do-not-echo' not in str(result)


def test_database_guards_preserve_terminal_history_and_binding(setup_assistant):
    from sqlalchemy.exc import DBAPIError
    from app.models import assistant_tables as tables
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    state = service.message(thread['id'], request(profile))
    accepted = service.decide(thread['id'], state['proposals'][0]['id'], decision())
    writes = [
        tables['turns'].update().values(reply='overwrite'),
        tables['proposals'].update().values(proposal={}),
        tables['executions'].update().values(result={}),
        tables['threads'].update().values(project_id=None),
        tables['threads'].delete(),
    ]
    for write in writes:
        with pytest.raises(DBAPIError):
            with store.engine.begin() as conn:
                conn.execute(write)
    assert service.read(thread['id']) == accepted


def test_prompt_budget_keeps_current_snapshot_and_limits_history():
    from app.assistant_service import AssistantService
    history = [{'role': 'assistant', 'text': str(i) + 'x' * 5000, 'status': 'succeeded'} for i in range(30)]
    snapshot = {'fingerprint': 'current', 'saved': 's' * 20000}
    data = {'text': 'q' * 8000, 'context': {'stage': 'writer', 'selection': 'z' * 4000}}
    messages = AssistantService._prompt(history[-20:], data, snapshot)
    assert sum(len(m['content']) for m in messages) <= 48000
    assert len(messages) <= 22 and 's' * 20000 in messages[-1]['content']
    assert 'z' * 4000 in messages[-1]['content']


def test_frozen_assistant_migration_matches_metadata(setup_assistant):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.models import Base
    service, store, actions, planner, profile = setup_assistant
    with store.engine.connect() as conn:
        changes = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assistant_changes = [change for change in changes if 'fp_assistant_' in str(change)]
    assert assistant_changes == []


def test_abandon_execution_recovers_project_and_ignores_late_result(setup_assistant):
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    state = service.message(thread['id'], request(profile))
    proposal_id = state['proposals'][0]['id']
    entered, release = Event(), Event()
    execute = actions.execute
    def partial(*args, **kwargs):
        result = execute(*args, **kwargs)
        entered.set()
        assert release.wait(15)
        return result
    actions.execute = partial
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(service.decide, thread['id'], proposal_id, decision())
        assert entered.wait(10)
        result = service.abandon_execution(thread['id'], proposal_id)
        assert result['project_id'] and not result['active']
        assert result['proposals'][0]['status'] == 'unknown'
        release.set()
        assert future.result() == result


def test_abandoned_unknown_creation_cannot_create_second_project(setup_assistant):
    from app.assistant_service import AssistantConflict
    from app.models import assistant_tables as tables
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    state = service.message(thread['id'], request(profile))
    entered, release = Event(), Event()
    identities = []
    def unknown(project, proposal, key, reserved_project_id=None):
        identities.append(reserved_project_id)
        entered.set()
        assert release.wait(15)
        raise RuntimeError('unknown')
    actions.execute = unknown
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(service.decide, thread['id'], state['proposals'][0]['id'], decision())
        assert entered.wait(10)
        service.abandon_execution(thread['id'], state['proposals'][0]['id'])
        release.set()
        future.result()
    next_state = service.message(thread['id'], request(profile, 1))
    with pytest.raises(AssistantConflict):
        service.decide(thread['id'], next_state['proposals'][-1]['id'], decision())
    assert len(identities) == 1


def test_http_real_actions_create_then_storyboard_revision(database_url):
    from copy import deepcopy
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.test_story import FakeModel, STORY
    from tests.test_production_contracts import board_content
    planner = Planner({'reply': '请确认创建', 'proposals': [{'kind': 'writer_create', 'title': '创建故事',
        'summary': '创建并检查故事', 'params': {'story': STORY}}]})
    with TestClient(create_app(database_url=database_url, provider=FakeModel(), assistant_provider=planner)) as client:
        profile = client.post('/api/production/model-profiles', json=model_config()).json()
        thread = client.post('/api/assistant/threads', json={'idempotency_key': key()}).json()
        base = '/api/assistant/threads/' + thread['id']
        response = client.post(base + '/messages', json=request(profile).model_dump(mode='json'))
        assert response.status_code == 200, response.text
        state = response.json()
        assert state['messages'][-1]['status'] == 'succeeded', state
        response = client.post(base + '/proposals/' + state['proposals'][0]['id'] + '/decision',
                               json=decision().model_dump(mode='json'))
        assert response.status_code == 200, response.text
        state = response.json()
        assert state['project_id'] and state['proposals'][0]['status'] == 'accepted', state
        project_id = state['project_id']
        project = client.get('/api/projects/' + project_id).json()
        assert client.post('/api/projects/' + project_id + '/resume', json={
            'action': 'confirm', 'version': project['state']['version'],
            'interrupt_id': project['interrupt']['id']}).status_code == 200
        board = client.post('/api/production/projects/' + project_id + '/storyboards',
                            json={'source_version': 1, 'content': board_content()}).json()
        content = deepcopy(board['content'])
        content['shots'][0]['camera_motion'] = '固定机位'
        planner.output = {'reply': '请确认分镜修改', 'proposals': [{'kind': 'storyboard_revise',
            'title': '修改镜头', 'summary': '固定机位', 'params': {'content': content}}]}
        response = client.post(base + '/messages', json=request(profile, 1,
            context={'stage': 'storyboard', 'storyboard_id': board['id'], 'shot_key': 'shot-1'}).model_dump(mode='json'))
        assert response.status_code == 200, response.text
        state = response.json()
        assert state['messages'][-1]['status'] == 'succeeded', state
        proposal = state['proposals'][-1]
        assert proposal['available'], proposal
        response = client.post(base + '/proposals/' + proposal['id'] + '/decision',
                               json=decision().model_dump(mode='json'))
        assert response.status_code == 200, response.text
        assert response.json()['proposals'][-1]['status'] == 'accepted', response.json()


def test_project_open_during_creation_restores_reserving_thread(setup_assistant):
    from app.assistant_contracts import CreateThread
    service, store, actions, planner, profile = setup_assistant
    thread = create(service)
    state = service.message(thread['id'], request(profile))
    execute = actions.execute
    opened = []
    def open_project(*args, **kwargs):
        result = execute(*args, **kwargs)
        opened.append(service.create(CreateThread(project_id=result['project_id'], idempotency_key=key())))
        return result
    actions.execute = open_project
    result = service.decide(thread['id'], state['proposals'][0]['id'], decision())
    assert opened[0]['id'] == thread['id']
    assert result['proposals'][0]['status'] == 'accepted'
