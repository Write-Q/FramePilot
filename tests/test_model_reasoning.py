import json

import httpx
import pytest
from pydantic import ValidationError

from app.production.contracts import GenerateStoryboard, ModelConfig
from app.production.chat import ChatPlanner
from app.production.reasoning import build_payload, choose_effort, request_identity, InvalidReasoning
from tests.test_production_contracts import model_config


def config(protocol='none', **changes):
    value = model_config()
    value.update(reasoning_protocol=protocol, **changes)
    return ModelConfig.model_validate(value)


def test_legacy_payload_and_default_identity_stay_unchanged():
    payload = build_payload(config(), [])
    assert payload == {'model': 'model-a', 'messages': [], 'response_format': {'type': 'json_object'},
                       'temperature': 0.2, 'max_tokens': 12000}
    request = GenerateStoryboard(source_version=1, profile={'profile_id': 'p', 'version': 1}, idempotency_key='x'*32)
    assert 'reasoning_effort' not in request_identity(request)
    with pytest.raises(InvalidReasoning):
        choose_effort(config(), 'high')


@pytest.mark.parametrize('effort', ['low', 'high', 'max'])
def test_deepseek_maps_exact_thinking_fields_without_default_temperature(effort):
    chosen = choose_effort(config('deepseek'), effort)
    payload = build_payload(chosen, [])
    assert payload['thinking'] == {'type': 'enabled'}
    assert payload['reasoning_effort'] == effort
    assert payload['max_tokens'] == 12000
    assert 'temperature' not in payload and 'max_completion_tokens' not in payload


def test_disabled_and_provider_default_are_distinct():
    payload = build_payload(choose_effort(config('deepseek'), 'none'), [])
    assert payload['thinking'] == {'type': 'disabled'} and 'reasoning_effort' not in payload
    assert payload['temperature'] == 0.2
    payload = build_payload(choose_effort(config('deepseek'), 'default'), [])
    assert 'thinking' not in payload and 'reasoning_effort' not in payload
    assert 'temperature' not in payload


def test_explicit_default_clears_a_saved_effort_override():
    chosen = choose_effort(config('deepseek', parameters={'reasoning_effort': 'high'}), 'default')
    payload = build_payload(chosen, [])
    assert 'reasoning_effort' not in payload and 'thinking' not in payload


def test_effort_protocol_uses_completion_limit_and_declared_levels():
    chosen = choose_effort(config('effort', reasoning_levels=['low', 'high']), 'high')
    payload = build_payload(chosen, [])
    assert payload['reasoning_effort'] == 'high' and payload['max_completion_tokens'] == 12000
    assert 'max_tokens' not in payload and 'temperature' not in payload
    with pytest.raises(InvalidReasoning):
        choose_effort(chosen, 'medium')
    with pytest.raises(InvalidReasoning):
        choose_effort(config('deepseek'), 'medium')


@pytest.mark.parametrize('changes', [
    {'reasoning_protocol': 'none', 'reasoning_levels': ['high']},
    {'reasoning_protocol': 'deepseek', 'reasoning_levels': ['medium']},
    {'reasoning_protocol': 'effort', 'reasoning_levels': ['high', 'high']},
    {'reasoning_protocol': 'effort', 'parameters': {'temperature': .7}},
])
def test_invalid_config_cannot_claim_unsupported_parameters(changes):
    value=model_config() | changes
    with pytest.raises(ValidationError):
        ModelConfig.model_validate(value)


def test_real_chat_adapter_sends_chosen_effort_once_and_ignores_reasoning_text():
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
            'content':'{"issues":[]}', 'reasoning_content':'private-reasoning'}}]})
    chosen=choose_effort(config('deepseek', api_key_env=''), 'high')
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        output,_=ChatPlanner(client=client).generate(chosen, [])
    assert len(requests)==1 and output=={'issues':[]}
    assert json.loads(requests[0].content)['thinking']=={'type':'enabled'}
