from copy import deepcopy

import pytest

from app.domain import CreateProject
from app.provider import ProviderError
from app.service import StoryService
from tests.test_story import FakeModel, STORY, card, resume


class ShapeModel(FakeModel):
    def __init__(self, task='review', forever=False, card_only=False):
        super().__init__()
        self.task = task; self.forever = forever; self.card_only = card_only
        self.payloads = []

    def generate(self, task, payload, schema):
        self.payloads.append((task, deepcopy(payload)))
        if task == 'repair_card':
            self.calls.append(task)
            result = {'card': card()}
            if self.forever: result['card']['actions_placeholder'] = {}
            return result, {'total_tokens': 11}
        result, usage = super().generate(task, payload, schema)
        if task == self.task and (self.forever or sum(n == task for n, _ in self.payloads) == 1):
            if self.card_only: result['card']['actions_placeholder'] = {}
            else: result['extra_field'] = '不能静默删除'
        return result, usage


@pytest.mark.parametrize('task', ['extract', 'review', 'plan', 'brainstorm'])
def test_schema_error_gets_one_feedback_correction(database_url, task):
    model = ShapeModel(task)
    # A title is needed only for brainstorm; this model supplies its own classification.
    original_generate = model.generate
    def generate(name, payload, schema):
        if name == 'brainstorm':
            model.calls.append(name); model.payloads.append((name, deepcopy(payload)))
            result = {'directions': [{'title': '甲', 'outline': '甲方向'}, {'title': '乙', 'outline': '乙方向'}]}
            if len([x for x in model.calls if x == name]) == 1: result['extra_field'] = '错误'
            return result, {'total_tokens': 10}
        result, usage = original_generate(name, payload, schema)
        if name == 'extract' and task == 'brainstorm': result['input_kind'] = 'idea'
        return result, usage
    model.generate = generate
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY, mode='free' if task == 'plan' else 'collaborative'))
        assert p['state']['status'] in ('awaiting_confirmation', 'awaiting_direction')
        assert model.calls.count(task) == 2
        second = [p for n, p in model.payloads if n == task][1]
        assert 'extra_field' in second['validation_feedback']
        bad = next(c for c in p['calls'] if c['status'] == 'invalid_output')
        assert bad['usage']['total_tokens'] == 10


def test_repeated_schema_error_stops_and_cannot_confirm(database_url):
    with StoryService(database_url, ShapeModel(forever=True)) as service:
        p = service.create(CreateProject(story=STORY))
        assert p['state']['status'] == 'failed'
        assert p['calls_used'] == 3
        assert p['state']['reviewed_version'] == 0 and not p['interrupt']


def test_schema_repair_respects_project_budget(database_url):
    with StoryService(database_url, ShapeModel(), max_calls=2) as service:
        p = service.create(CreateProject(story=STORY))
        assert p['state']['status'] == 'budget_exhausted'
        assert p['calls_used'] == 2


@pytest.mark.parametrize('task', ['compose', 'revise'])
def test_card_shape_repair_preserves_candidate_body(database_url, task):
    model = ShapeModel(task, card_only=True)
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY, mode='free' if task == 'compose' else 'collaborative'))
        if task == 'revise': p = resume(service, p, 'revise', '补充归还钥匙。')
        assert p['state']['status'] == 'awaiting_confirmation'
        assert model.calls.count(task) == 1 and model.calls.count('repair_card') == 1
        expected = STORY if task == 'compose' else STORY+'\n此前阿林已把钥匙还给小禾。'
        assert p['state']['draft'] == expected


def test_card_shape_repair_restart_keeps_candidate(database_url):
    with StoryService(database_url, ShapeModel('revise', forever=True, card_only=True)) as service:
        p = service.create(CreateProject(story=STORY))
        p = resume(service, p, 'revise', '补充归还钥匙。')
        assert p['state']['status'] == 'failed'
        assert p['state']['draft'] == STORY
    model = ShapeModel('unused')
    with StoryService(database_url, model) as service:
        p = service.retry(p['id'])
        assert p['state']['status'] == 'awaiting_confirmation'
        assert model.calls == ['repair_card', 'review']


def test_reference_protocol_is_used_by_workflow(database_url):
    class ReferencedModel(FakeModel):
        evidence_references = True
        def generate(self, task, payload, schema):
            if task == 'extract':
                self.calls.append(task)
                assert payload['evidence_catalog']
                assert 'evidence_ref' in schema['$defs']['Facet']['properties']
                facets = {k: dict(text=v['text'], source=v['source'], evidence_ref='') for k, v in card().items()}
                ref = next(x for x in payload['evidence_catalog'] if x['source'] == 'original')
                facets['characters'] = dict(text='小禾与阿林', source='original', evidence_ref=ref['id'])
                return {'card': facets}, {'total_tokens': 10}
            return super().generate(task, payload, schema)
    with StoryService(database_url, ReferencedModel()) as service:
        p = service.create(CreateProject(story=STORY))
        assert p['state']['status'] == 'awaiting_confirmation'
        assert p['state']['card']['characters']['evidence'] in STORY
        assert 'evidence_ref' not in p['state']['card']['characters']


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('bad_first', [False, True])
def test_actual_adapter_reference_protocol_and_json_correction(database_url, monkeypatch, stream, bad_first):
    import json
    import httpx
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.provider import DeepSeekProvider
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unit-only')
    requests = []
    def handle(request):
        body = json.loads(request.content); requests.append(body)
        payload = json.loads(body['messages'][1]['content'])
        assert 'evidence_catalog' in payload
        assert '来源片段编号协议' in body['messages'][0]['content']
        if bad_first and len(requests) == 1:
            content = 'not-json'
        elif len(requests) <= (2 if bad_first else 1):
            facets = {k: dict(text=v['text'], source=v['source'], evidence_ref='') for k, v in card().items()}
            ref = next(x for x in payload['evidence_catalog'] if x['source'] == 'original')
            facets['characters'] = dict(text='小禾', source='original', evidence_ref=ref['id'])
            content = json.dumps({'card': facets}, ensure_ascii=False)
        else:
            content = '{"issues":[]}'
        if body.get('stream'):
            event = {'id': 't', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'deepseek-chat',
                     'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
                     'usage': {'prompt_tokens': 12, 'completion_tokens': 4, 'total_tokens': 16}}
            return httpx.Response(200, text='data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json={'id': 't', 'object': 'chat.completion', 'created': 0, 'model': 'deepseek-chat',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 4, 'total_tokens': 16}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with TestClient(create_app(database_url=database_url, provider=DeepSeekProvider(client=http))) as client:
            response = client.post('/api/projects/stream' if stream else '/api/projects', json={'story': STORY})
            if stream:
                events = [json.loads(s[6:]) for s in response.text.splitlines() if s.startswith('data: ')]
                p = next(e['data'] for e in events if e['event'] == 'result')
            else: p = response.json()
            assert p['state']['status'] == 'awaiting_confirmation'
            assert p['state']['card']['characters']['evidence'] in STORY
            assert p['calls_used'] == (3 if bad_first else 2)
            if bad_first:
                assert p['calls'][0]['status'] == 'invalid_output'
                assert p['calls'][0]['usage']['total_tokens'] == 16
                assert json.loads(requests[1]['messages'][1]['content'])['validation_feedback']


@pytest.mark.parametrize('finish', ['length', 'content_filter'])
def test_incomplete_or_filtered_response_not_retried(database_url, monkeypatch, finish):
    import httpx
    from app.provider import DeepSeekProvider
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unit-only')
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'id': 't', 'object': 'chat.completion', 'created': 0, 'model': 'deepseek-chat',
            'choices': [{'index': 0, 'finish_reason': finish, 'message': {'role': 'assistant', 'content': '{}'}}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with StoryService(database_url, DeepSeekProvider(client=http)) as service:
            p = service.create(CreateProject(story=STORY))
            assert p['state']['status'] == 'failed'
            assert p['calls_used'] == 1 and len(requests) == 1


@pytest.mark.parametrize('task', ['extract', 'review'])
def test_structure_and_quote_failures_share_one_automatic_correction(database_url, task):
    from tests.test_story import issue
    class Mixed(FakeModel):
        def generate(self, name, payload, schema):
            result, usage = super().generate(name, payload, schema)
            if name == task:
                if self.calls.count(task) == 1:
                    result['extra_field'] = '错误'
                elif task == 'extract':
                    result['card']['actions'] = dict(text='动作', source='original', evidence='不存在')
                else:
                    problem = issue(); problem['evidence'] = [{'source': 'draft', 'quote': '不存在'}]
                    result = {'issues': [problem]}
            return result, usage
    model = Mixed()
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY))
        assert p['state']['status'] == 'failed'
        assert model.calls.count(task) == 2


@pytest.mark.parametrize('second_error', ['shape', 'quote'])
def test_second_candidate_is_preserved_without_third_automatic_call(database_url, second_error):
    class SecondCandidate(FakeModel):
        def generate(self, task, payload, schema):
            result, usage = super().generate(task, payload, schema)
            if task == 'compose':
                result['draft'] = STORY + f"候选{self.calls.count('compose')}"
                if self.calls.count('compose') == 1:
                    result['extra_field'] = '错误'
                elif second_error == 'shape':
                    result['card']['extra_field'] = '错误'
                else:
                    result['card']['actions'] = dict(text='动作', source='original', evidence='不存在')
            return result, usage
    with StoryService(database_url, SecondCandidate()) as service:
        p = service.create(CreateProject(story=STORY, mode='free'))
        assert p['state']['status'] == 'failed'
        assert p['calls_used'] == 3  # plan + compose + one correction
        assert p['state']['pending_generation']['result']['draft'] == STORY+'候选2'
        assert p['state']['draft'] == STORY
    model = ShapeModel('unused')
    with StoryService(database_url, model) as service:
        recovered = service.retry(p['id'])
        assert recovered['state']['status'] == 'awaiting_confirmation'
        assert recovered['state']['draft'] == STORY+'候选2'
        assert model.calls == ['repair_card', 'review']
