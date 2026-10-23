"""Real routes and business delegates; deterministic planner, no external model calls."""
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.production.contracts import ModelConfig
from app.production.store import ProductionStore
from tests.test_production_contracts import model_config
from tests.test_story import FakeModel, STORY


class Planner:
    def __init__(self):
        self.calls = 0

    def generate(self, config, messages):
        self.calls += 1
        current = json.loads(messages[-1]['content'])
        assert len(messages[-1]['content']) < 48000
        assert current['context']['available_actions'][0]['params_schema']
        return {'reply': '请核对后创建，原稿直接保存。', 'proposals': [
            {'kind': 'writer_create', 'title': '保存原稿', 'params': {'story': STORY, 'mode': 'direct'}}
        ]}, {'total_tokens': 31}


def test_real_api_unbound_create_bind_and_restore(database_url):
    planner = Planner()
    with _store(database_url) as store:
        profile = store.create_profile(ModelConfig(**model_config()))
    with TestClient(create_app(database_url=database_url, provider=FakeModel(), assistant_provider=planner)) as client:
        thread = client.post('/api/assistant/threads', json={'idempotency_key': uuid4().hex}).json()
        url = '/api/assistant/threads/' + thread['id']
        payload = {'expected_revision': 0, 'text': '保存这个故事', 'context': {'stage': 'writer'},
                   'profile': {'profile_id': profile['id'], 'version': 1}, 'idempotency_key': uuid4().hex}
        response = client.post(url + '/messages', json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['messages'][-1]['status'] == 'succeeded', response.text
        proposal = response.json()['proposals'][0]
        assert proposal['available'] and not proposal['may_call_model']
        assert client.post(url + '/messages', json=payload).status_code == 200
        assert planner.calls == 1
        key = uuid4().hex
        path = url + '/proposals/' + proposal['id'] + '/decision'
        accepted = client.post(path, json={'decision': 'accept', 'idempotency_key': key})
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()
        assert result['proposals'][0]['status'] == 'accepted', accepted.text
        project = result['project_id']
        assert client.get('/api/projects/' + project).json()['state']['draft'] == STORY
        assert client.post(path, json={'decision': 'accept', 'idempotency_key': key}).json() == result
        restored = client.post('/api/assistant/threads', json={'project_id': project, 'idempotency_key': uuid4().hex})
        assert restored.json()['id'] == thread['id']
        assert restored.json()['proposals'][0]['status'] == 'accepted'
        invalid = client.post(url + '/messages', json=payload | {'secret-key': 'must-not-echo'})
        assert invalid.status_code == 422 and 'must-not-echo' not in invalid.text


from contextlib import contextmanager


@contextmanager
def _store(url):
    store = ProductionStore(url)
    try:
        yield store
    finally:
        store.close()
