import json
import httpx
from fastapi.testclient import TestClient
from app.main import create_app
from app.provider import DeepSeekProvider
from app.events import progress_sink
from tests.test_story import FakeModel, STORY


def test_provider_emits_chunks(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only')
    seen = []
    def handle(request):
        assert json.loads(request.content)['stream'] is True
        chunks = []
        for content, finish in [('{"issues":', None), ('[]}', None), ('', 'stop')]:
            chunks.append('data: '+json.dumps({'id':'test','object':'chat.completion.chunk','created':0,
                'model':'deepseek-chat','choices':[{'index':0,'delta':{'role':'assistant','content':content},'finish_reason':finish}]})+'\n\n')
        return httpx.Response(200, text=''.join(chunks)+'data: [DONE]\n\n', headers={'content-type':'text/event-stream'})
    token = progress_sink.set(seen.append)
    try:
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            result, _ = DeepSeekProvider(client=client).generate('review', {}, {})
        assert result == {'issues': []}
        assert ''.join(x['data']['text'] for x in seen if x['event']=='delta') == '{"issues":[]}'
    finally:
        progress_sink.reset(token)


def test_stream_endpoint_persists_result(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, provider=FakeModel())) as client:
        response = client.post('/api/projects/stream', json={'story': STORY})
        assert response.status_code == 200
        assert 'text/event-stream' in response.headers['content-type']
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert any(e['event']=='project' for e in events)
        result = next(e['data'] for e in events if e['event']=='result')
        assert result['state']['status'] == 'awaiting_confirmation'
        assert client.get('/api/projects/'+result['id']).json()['calls_used'] == 2
        resumed = client.post('/api/projects/'+result['id']+'/resume/stream', json={
            'version':1,'interrupt_id':result['interrupt']['id'],'action':'confirm'})
        assert 'confirmed' in resumed.text
