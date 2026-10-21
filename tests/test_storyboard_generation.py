from copy import deepcopy
import json
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.main import create_app
from app.production import chat
from app.production.contracts import ModelConfig
from tests.test_production import confirmed_project
from tests.test_production_contracts import board_content, model_config
from tests.test_story import FakeModel, STORY


class Planner:
    def __init__(self, output=None):
        self.calls = []
        self.output = output or board_content()

    def generate(self, config, messages):
        self.calls.append((config, messages))
        return deepcopy(self.output), {'total_tokens': 42}


@pytest.fixture
def setup(database_url):
    planner = Planner()
    app = create_app(database_url=database_url, provider=FakeModel(), storyboard_provider=planner)
    with TestClient(app) as client:
        project = confirmed_project(client)
        profile = client.post('/api/production/model-profiles', json=model_config()).json()
        payload = {'source_version': 1, 'profile': {'profile_id': profile['id'], 'version': 1},
                   'idempotency_key': 'a' * 32, 'target_shots': 1}
        yield client, planner, project, payload


def test_chat_adapter_one_request_fixed_parameters_and_secret_reference(monkeypatch):
    requests = []
    monkeypatch.setenv('FP_PLANNER_KEY', 'private-token')

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(board_content())}}],
                                        'usage': {'total_tokens': 42}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        adapter = chat.ChatPlanner(client=client)
        config = ModelConfig(**model_config())
        output, usage = adapter.generate(config, [{'role': 'system', 'content': 'JSON'}])
    assert len(requests) == 1
    assert str(requests[0].url) == 'https://example.test/v1/chat/completions'
    assert requests[0].headers['authorization'] == 'Bearer private-token'
    assert 'private-token' not in requests[0].content.decode()
    assert json.loads(requests[0].content)['model'] == 'model-a'
    assert output['title'] == '钥匙' and usage['total_tokens'] == 42


def test_selected_effort_is_fixed_and_invalid_choice_does_not_reserve(setup):
    client, planner, project, request = setup
    config = model_config() | {'reasoning_protocol': 'deepseek'}
    profile = client.post('/api/production/model-profiles', json=config).json()
    url = f'/api/production/projects/{project}/storyboard-runs'
    request = request | {'profile': {'profile_id': profile['id'], 'version': 1}, 'reasoning_effort': 'medium'}
    assert client.post(url, json=request).status_code == 422
    assert client.get(url).json() == [] and not planner.calls
    request['reasoning_effort'] = 'high'
    response = client.post(url, json=request)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'succeeded'
    assert run['manifest']['request_parameters']['reasoning_effort'] == 'high'
    assert run['manifest']['request_parameters']['thinking'] == {'type': 'enabled'}
    assert planner.calls[0][0].parameters.reasoning_effort == 'high'
    assert client.post(url, json=request).json()['id'] == run['id']
    assert client.post(url, json=request | {'reasoning_effort': 'low'}).status_code == 409
    assert len(planner.calls) == 1


@pytest.mark.parametrize('kind', ['timeout', 'http', 'truncated', 'invalid', 'refusal'])
def test_chat_errors_are_sanitized_and_never_retried(monkeypatch, kind):
    monkeypatch.setenv('FP_PLANNER_KEY', 'private-token')
    requests = []

    def respond(request):
        requests.append(request)
        if kind == 'timeout':
            raise httpx.ReadTimeout('private-token', request=request)
        if kind == 'http':
            return httpx.Response(429, text='private-token')
        if kind == 'invalid':
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': 'private-token'}}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length' if kind == 'truncated' else 'stop',
                                        'message': {'content': '{}', 'refusal': 'private-token' if kind == 'refusal' else None}}]})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(chat.PlannerError) as error:
            chat.ChatPlanner(client=client).generate(ModelConfig(**model_config()), [])
    assert 'private-token' not in str(error.value)
    assert len(requests) == 1


def test_missing_key_fails_before_network(monkeypatch):
    monkeypatch.delenv('FP_PLANNER_KEY', raising=False)
    with pytest.raises(chat.PlannerError, match='环境变量'):
        chat.ChatPlanner().generate(ModelConfig(**model_config()), [])


def generate(client, project, payload):
    return client.post(f'/api/production/projects/{project}/storyboard-runs', json=payload)


def test_generate_persists_trace_and_deduplicates_across_restart(setup, database_url):
    client, planner, project, payload = setup
    response = generate(client, project, payload)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'succeeded' and run['usage']['total_tokens'] == 42
    assert run['board']['creation_method'] == 'ai'
    assert run['board']['confirmed'] is False
    assert run['board']['content']['bindings']['text'] == payload['profile']
    assert run['manifest']['workflow_version']
    assert len(run['manifest']['skills']) == 3
    assert run['review']['semantic_verified'] is False
    assert generate(client, project, payload).json()['id'] == run['id']
    assert len(planner.calls) == 1
    with TestClient(create_app(database_url=database_url, provider=FakeModel(), storyboard_provider=planner)) as restarted:
        saved = restarted.get(f'/api/production/projects/{project}/storyboard-runs').json()
        assert saved[0]['board']['version_id'] == run['board']['version_id']
        assert generate(restarted, project, payload).json()['id'] == run['id']
    assert len(planner.calls) == 1
    different = payload | {'instructions': '改变参数'}
    assert generate(client, project, different).status_code == 409


@pytest.mark.parametrize('bad', ['quote', 'count', 'aspect', 'bindings', 'schema'])
def test_bad_output_keeps_failed_run_without_partial_board(setup, bad):
    client, planner, project, payload = setup
    if bad == 'quote':
        planner.output['scenes'][0]['source_quote'] = '虚构剧情'
    elif bad == 'count':
        payload['target_shots'] = 2
    elif bad == 'aspect':
        payload['aspect_ratio'] = '9:16'
    elif bad == 'bindings':
        planner.output['bindings'] = {'text': {'profile_id': 'invented', 'version': 1}}
    else:
        planner.output['shots'][0]['duration_ms'] = -1
    response = generate(client, project, payload)
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'failed'
    assert response.json()['error_code'] == 'invalid_output'
    assert client.get(f'/api/production/projects/{project}/storyboards').json() == []
    generate(client, project, payload)
    assert len(planner.calls) == 1


def test_incompatible_profile_and_unconfirmed_source_never_call_planner(setup):
    client, planner, project, payload = setup
    wrong = model_config()
    wrong.update(purpose='video', adapter='vendor_native')
    profile = client.post('/api/production/model-profiles', json=wrong).json()
    assert generate(client, project, payload | {'profile': {'profile_id': profile['id'], 'version': 1}}).status_code == 422
    pending = client.post('/api/projects', json={'story': STORY}).json()['id']
    assert generate(client, pending, payload).status_code == 409
    assert not planner.calls


def test_inflight_request_is_deduplicated_and_abandon_discards_late_output(setup):
    client, planner, project, payload = setup
    entered, release = Event(), Event()
    original = planner.generate

    def blocking(*args):
        entered.set()
        assert release.wait(15)
        return original(*args)
    planner.generate = blocking
    url = f'/api/production/projects/{project}/storyboard-runs'
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(generate, client, project, payload)
        assert entered.wait(10)
        try:
            run = generate(client, project, payload).json()
            assert run['status'] == 'running'
            assert generate(client, project, payload | {'idempotency_key': 'b' * 32}).status_code == 409
            abandoned = client.post(url + '/' + run['id'] + '/abandon')
            assert abandoned.status_code == 200, abandoned.text
            assert abandoned.json()['status'] == 'abandoned'
        finally:
            release.set()
        assert pending.result().json()['status'] == 'abandoned'
    assert client.get(f'/api/production/projects/{project}/storyboards').json() == []


def test_source_changed_during_call_prevents_adoption(setup, database_url):
    from app.models import Project
    from sqlalchemy.orm import Session
    client, planner, project, payload = setup
    original = planner.generate

    def change_source(*args):
        engine = sa.create_engine(database_url)
        try:
            with Session(engine) as session, session.begin():
                row = session.get(Project, project)
                state = deepcopy(row.snapshot)
                state['state']['status'] = 'awaiting_confirmation'
                row.snapshot = state
        finally:
            engine.dispose()
        return original(*args)
    planner.generate = change_source
    result = generate(client, project, payload).json()
    assert result['status'] == 'failed' and result['error_code'] == 'source_changed'
    assert client.get(f'/api/production/projects/{project}/storyboards').json() == []


def test_run_project_isolation_and_rules_for_saved_board(setup):
    client, planner, project, payload = setup
    run = generate(client, project, payload).json()
    other = confirmed_project(client)
    assert client.post(f"/api/production/projects/{other}/storyboard-runs/{run['id']}/abandon").status_code == 404
    board = run['board']
    response = client.get(f"/api/production/projects/{project}/storyboards/{board['id']}/review?version=1")
    assert response.status_code == 200, response.text
    assert response.json()['semantic_verified'] is False


def test_generation_pins_old_config_even_when_profile_head_changes(setup):
    client, planner, project, payload = setup
    changed = model_config()
    changed['model'] = 'new-model'
    client.put('/api/production/model-profiles/'+payload['profile']['profile_id'],
               json={'expected_version': 1, 'config': changed})
    run = generate(client, project, payload).json()
    assert run['status'] == 'succeeded'
    assert planner.calls[0][0].model == 'model-a'
    assert run['manifest']['request']['profile']['version'] == 1


def test_timeout_is_persisted_without_exception_or_key_leak(setup):
    client, planner, project, payload = setup
    def timeout(*args):
        raise chat.PlannerError('private-service-detail', 'outcome_unknown')
    planner.generate = timeout
    response = generate(client, project, payload)
    assert response.json()['error_code'] == 'outcome_unknown'
    assert 'private-service-detail' not in response.text
    assert response.json()['status'] == 'failed'


def test_generation_budget_is_durable_and_separate_from_writer(setup):
    client, planner, project, payload = setup
    for index in range(10):
        result = generate(client, project, payload | {'idempotency_key': str(index).zfill(32)})
        assert result.json()['status'] == 'succeeded', result.text
    assert generate(client, project, payload | {'idempotency_key': 'z' * 32}).status_code == 409
    assert len(planner.calls) == 10
    assert client.get('/api/projects/'+project).json()['calls_used'] == 2


def test_clarified_context_during_call_prevents_adoption(setup, database_url):
    from app.models import Project
    from sqlalchemy.orm import Session
    client, planner, project, payload = setup
    original = planner.generate
    def change_context(*args):
        engine = sa.create_engine(database_url)
        try:
            with Session(engine) as session, session.begin():
                row = session.get(Project, project)
                snapshot = deepcopy(row.snapshot)
                snapshot['state']['card']['characters']['text'] = '更新的人物解释'
                row.snapshot = snapshot
        finally:
            engine.dispose()
        return original(*args)
    planner.generate = change_context
    response = generate(client, project, payload)
    assert response.json()['error_code'] == 'source_changed'


def test_rule_bundle_failure_does_not_reserve_or_call_and_old_result_stays_readable(setup, tmp_path, monkeypatch):
    import shutil
    from app.production import planning
    client, planner, project, payload = setup
    saved = generate(client, project, payload).json()
    assert saved['status'] == 'succeeded'
    assert saved['manifest']['workflow_version'] == 'storyboard-planner-1.1.0'
    assert all(s['version'] == '1.1.0' and s['source_locators'] for s in saved['manifest']['skills'])
    root = tmp_path / 'corrupt-rules'
    shutil.copytree(planning.SKILL_ROOT, root)
    rule = root / 'K001-shot-planning.md'
    rule.write_text(rule.read_text(encoding='utf-8') + '\n未经登记的变更', encoding='utf-8')
    monkeypatch.setattr(planning, 'SKILL_ROOT', root)
    rejected = generate(client, project, payload | {'idempotency_key': 'damaged-bundle-test-key'})
    assert rejected.status_code == 503, rejected.text
    assert '分镜规则' in rejected.json()['detail']
    assert str(root) not in rejected.text and '未经登记的变更' not in rejected.text
    assert len(planner.calls) == 1
    old = generate(client, project, payload).json()
    assert old['id'] == saved['id'] and old['status'] == 'succeeded'
    runs = client.get(f'/api/production/projects/{project}/storyboard-runs').json()
    assert len(runs) == 1 and runs[0]['manifest'] == saved['manifest']
