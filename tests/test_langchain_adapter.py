import json
import httpx
import pytest
from langchain_deepseek import ChatDeepSeek
from app.provider import DeepSeekProvider, ProviderError


def test_real_langchain_adapter_with_mock_http(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only')
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'id':'test', 'object':'chat.completion',
            'created':0, 'model':'deepseek-chat', 'choices':[{'index':0,
            'finish_reason':'stop', 'message':{'role':'assistant','content':'{"issues":[]}'}}],
            'usage':{'prompt_tokens':12,'completion_tokens':4,'total_tokens':16}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = DeepSeekProvider(client=client)
        result, usage = provider.generate('review', {'draft':'test {story}'}, {'type':'object','properties':{'issues':{'type':'array','items':{'type':'object'}}}})
        assert isinstance(provider.chat_model, ChatDeepSeek)
        assert result == {'issues': []}
        assert usage['total_tokens'] == 16
        assert seen[0]['response_format'] == {'type':'json_object'}
        assert [m['role'] for m in seen[0]['messages']] == ['system','user']
        assert json.loads(seen[0]['messages'][1]['content'])['draft'] == 'test {story}'


def test_sdk_does_not_silently_retry(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only')
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429, json={'error':{'message':'secret-response'}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError):
            DeepSeekProvider(client=client).generate('review', {}, {})
    assert len(calls) == 1
