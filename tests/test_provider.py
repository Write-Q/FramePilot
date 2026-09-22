import httpx
import pytest
from app.provider import DeepSeekProvider, ProviderError


@pytest.mark.parametrize('body', [
    {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'content': 'not-json'}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'content': '[]'}}]},
])
def test_invalid_response_rejected(monkeypatch, body):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unit-test-only')
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        provider = DeepSeekProvider(client=client)
        with pytest.raises(ProviderError):
            provider.generate('extract', {}, {})


def test_failure_does_not_expose_provider_body(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unit-test-only')
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text='secret-response'))) as client:
        with pytest.raises(ProviderError) as error:
            DeepSeekProvider(client=client).generate('extract', {}, {})
        assert '401' in str(error.value)
        assert 'secret-response' not in str(error.value)
        assert 'unit-test-only' not in str(error.value)
