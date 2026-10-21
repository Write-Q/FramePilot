"""受控思考参数编译；协议/档位是配置声明，不等于模型能力已验证。"""
from app.production.contracts import ModelConfig, REASONING_LEVELS
from app.production.store import InvalidProduction

RULE_VERSION = 'chat-parameters-1.0.0'


class InvalidReasoning(InvalidProduction):
    pass


def options(config):
    return ['default', *(config.reasoning_levels if config.reasoning_levels is not None
                          else REASONING_LEVELS[config.reasoning_protocol])]


def choose_effort(config, effort):
    if effort not in options(config):
        raise InvalidReasoning('此模型配置未声明支持该思考等级，请重新选择；未发送模型请求')
    data = config.model_dump(mode='json')
    data['parameters']['reasoning_effort'] = None if effort == 'default' else effort
    return ModelConfig.model_validate(data)


def request_identity(request):
    data = request.model_dump(mode='json')
    # 旧客户端/旧运行未含此默认字段，保留原幂等指纹，避免升级后复发旧调用。
    if data.get('reasoning_effort') == 'default':
        data.pop('reasoning_effort', None)
    return data


def build_payload(config, messages):
    effort = config.parameters.reasoning_effort
    if effort is not None and effort not in options(config):
        raise InvalidReasoning('思考等级不在配置声明范围内')
    payload = {'model': config.model, 'messages': messages, 'response_format': {'type': 'json_object'}}
    parameters = config.parameters.model_dump(exclude_none=True)
    parameters.pop('reasoning_effort', None)
    limit = parameters.pop('max_tokens', 12000)
    if config.reasoning_protocol == 'effort':
        payload['max_completion_tokens'] = limit
        if effort is not None:
            payload['reasoning_effort'] = effort
    elif config.reasoning_protocol == 'deepseek':
        payload['max_tokens'] = limit
        if effort == 'none':
            payload['thinking'] = {'type': 'disabled'}
            payload['temperature'] = .2
        elif effort is not None:
            payload.update(thinking={'type': 'enabled'}, reasoning_effort=effort)
    else:
        payload.update(max_tokens=limit, temperature=.2)
    payload.update(parameters)
    return payload


def execution_manifest(config):
    payload = build_payload(config, [])
    payload.pop('messages')
    return {'parameter_rules': RULE_VERSION, 'reasoning_protocol': config.reasoning_protocol,
            'request_parameters': payload, 'capabilities_verified': False}
