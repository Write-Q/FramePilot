from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import production_tables
from app.production.chat import PlannerError
from tests.test_production import confirmed_project
from tests.test_production_contracts import board_content, model_config
from tests.test_story import FakeModel
from tests.test_storyboard_review_contracts import report


class Reviewer:
    def __init__(self):
        self.calls = []
        self.output = report()
        self.started = self.release = None

    def generate(self, config, messages):
        self.calls.append((config, messages))
        if self.started:
            self.started.set()
            assert self.release.wait(10)
        return deepcopy(self.output), {'total_tokens': 24}


@pytest.fixture
def setup(database_url):
    reviewer = Reviewer()
    with TestClient(create_app(database_url=database_url, provider=FakeModel(), review_provider=reviewer)) as client:
        project = confirmed_project(client)
        base = f'/api/production/projects/{project}/storyboards'
        board = client.post(base, json={'source_version': 1, 'content': board_content()}).json()
        config = model_config() | {'purpose': 'review'}
        profile = client.post('/api/production/model-profiles', json=config).json()
        request = {'expected_version': 1, 'profile': {'profile_id': profile['id'], 'version': 1},
                   'idempotency_key': 'r' * 32}
        yield client, reviewer, base + '/' + board['id'], request


def test_truncated_review_keeps_usage_and_actionable_error_without_retry(setup):
    client, reviewer, url, request = setup
    calls = []

    def fail(*args):
        calls.append(1)
        raise PlannerError('private-detail', 'output_truncated', {'completion_tokens': 12000})

    reviewer.generate = fail
    response = client.post(url + '/review-runs', json=request)
    assert response.status_code == 201
    run = response.json()
    assert run['status'] == 'failed' and run['report'] is None
    assert run['error_code'] == 'output_truncated'
    assert run['usage'] == {'completion_tokens': 12000}
    assert '降低思考等级' in run['error'] and 'private-detail' not in response.text
    assert client.post(url + '/review-runs', json=request).json()['id'] == run['id']
    assert len(calls) == 1


def test_review_is_explicit_idempotent_and_does_not_confirm_or_edit(setup):
    client, reviewer, url, request = setup
    assert client.get(url + '/review-runs').json() == [] and not reviewer.calls
    response = client.post(url + '/review-runs', json=request)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'succeeded' and run['applicable']
    assert run['report']['issues'][0]['key'] == 'issue-1'
    assert run['manifest']['skills'][0]['version'] == '1.1.0'
    assert client.post(url + '/review-runs', json=request).json()['id'] == run['id']
    assert len(reviewer.calls) == 1
    assert client.post(url + '/review-runs', json=request | {'expected_version': 2}).status_code == 409
    board = client.get(url).json()
    assert board['version'] == 1 and not board['confirmed']
    assert client.post(url + '/versions', json={'expected_version': 1, 'content': board['content']}).status_code == 201
    stale = client.get(url + '/review-runs').json()[0]
    assert not stale['applicable'] and 'board_changed' in stale['stale_reasons']
    assert stale['version'] == 1
    assert client.post(url + '/review-runs', json=request | {'idempotency_key': 's' * 32}).status_code == 409


@pytest.mark.parametrize('invalid', ['quote', 'empty_object'])
def test_invalid_evidence_is_failed_without_partial_report(setup, invalid):
    client, reviewer, url, request = setup
    if invalid == 'quote':
        reviewer.output['issues'][0]['evidence'][0]['quote'] = '原文没有这句话'
    else:
        reviewer.output = {}
    run = client.post(url + '/review-runs', json=request).json()
    assert run['status'] == 'failed' and run['error_code'] == 'invalid_output'
    assert run['report'] is None and len(reviewer.calls) == 1


def test_empty_report_is_valid_but_never_a_pass(setup):
    client, reviewer, url, request = setup
    reviewer.output = {'issues': []}
    run = client.post(url + '/review-runs', json=request).json()
    assert run['status'] == 'succeeded' and run['report']['issues'] == []
    assert 'passed' not in run['report']


def test_review_effort_is_sent_and_recorded_separately(setup):
    client, reviewer, url, request = setup
    config = model_config() | {'purpose': 'review', 'reasoning_protocol': 'effort', 'reasoning_levels': ['high']}
    profile = client.post('/api/production/model-profiles', json=config).json()
    assert profile['reasoning_options'] == ['default', 'high']
    request = request | {'profile': {'profile_id': profile['id'], 'version': 1}, 'reasoning_effort': 'high'}
    run = client.post(url + '/review-runs', json=request).json()
    assert run['status'] == 'succeeded'
    assert reviewer.calls[0][0].parameters.reasoning_effort == 'high'
    assert run['manifest']['request_parameters']['max_completion_tokens'] == 12000
    assert 'max_tokens' not in run['manifest']['request_parameters']


def test_edit_during_review_keeps_exact_historical_target(setup):
    client, reviewer, url, request = setup
    reviewer.started, reviewer.release = Event(), Event()
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, url + '/review-runs', json=request)
        try:
            assert reviewer.started.wait(5)
            assert client.post(url + '/review-runs', json=request | {'idempotency_key': 's' * 32}).status_code == 409
            assert client.post(url + '/versions', json={'expected_version': 1, 'content': board_content()}).status_code == 201
        finally:
            reviewer.release.set()
        run = pending.result().json()
    assert run['status'] == 'succeeded' and run['version'] == 1
    assert not run['applicable'] and 'board_changed' in run['stale_reasons']


def test_abandon_discards_late_result(setup):
    client, reviewer, url, request = setup
    reviewer.started, reviewer.release = Event(), Event()
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, url + '/review-runs', json=request)
        try:
            assert reviewer.started.wait(5)
            active = client.get(url + '/review-runs').json()[0]
            assert client.post(url + '/review-runs/' + active['id'] + '/abandon').json()['status'] == 'abandoned'
        finally:
            reviewer.release.set()
        run = pending.result().json()
    assert run['status'] == 'abandoned' and run['report'] is None


def test_review_purpose_and_model_version_are_explicit(setup):
    client, reviewer, url, request = setup
    profile = client.post('/api/production/model-profiles', json=model_config()).json()
    wrong = request | {'profile': {'profile_id': profile['id'], 'version': 1}}
    assert client.post(url + '/review-runs', json=wrong).status_code == 422
    assert not reviewer.calls and client.get(url + '/review-runs').json() == []
    profile_url = '/api/production/model-profiles/' + request['profile']['profile_id']
    config = model_config() | {'purpose': 'review', 'model': 'changed-model'}
    assert client.put(profile_url, json={'expected_version': 1, 'config': config}).status_code == 200
    run = client.post(url + '/review-runs', json=request).json()
    assert run['profile_version'] == 1 and reviewer.calls[0][0].model == 'model-a'


def test_review_budget_counts_failures_across_board_series(setup):
    client, reviewer, url, request = setup
    reviewer.output = {}
    for index in range(10):
        run = client.post(url + '/review-runs', json=request | {'idempotency_key': f'{index:032d}'}).json()
        assert run['status'] == 'failed'
    other = client.post(url.rsplit('/', 1)[0], json={'source_version': 1, 'content': board_content()}).json()
    other_url = url.rsplit('/', 1)[0] + '/' + other['id']
    assert client.post(other_url + '/review-runs', json=request).status_code == 409
    assert len(reviewer.calls) == 10


def test_terminal_report_cannot_be_overwritten_or_deleted(setup):
    client, reviewer, url, request = setup
    run = client.post(url + '/review-runs', json=request).json()
    table = production_tables['review_runs']
    engine = client.app.state.production.engine
    for operation in [table.update().where(table.c.id == run['id']).values(error_code='forged'),
                      table.delete().where(table.c.id == run['id'])]:
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(operation)
    assert client.get(url + '/review-runs').json()[0]['report'] == run['report']


def test_provider_failure_is_safe_and_other_project_cannot_read(setup):
    client, reviewer, url, request = setup
    def fail(*args):
        raise PlannerError('private-token', 'outcome_unknown')
    reviewer.generate = fail
    response = client.post(url + '/review-runs', json=request)
    run = response.json()
    assert run['status'] == 'failed' and 'private-token' not in response.text
    project = confirmed_project(client)
    other_url = f'/api/production/projects/{project}/storyboards/' + url.rsplit('/', 1)[1]
    assert client.get(other_url + '/review-runs').status_code == 404
    assert client.post(other_url + '/review-runs/' + run['id'] + '/abandon').status_code == 404
