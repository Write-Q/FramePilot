"""供应商中立的单次 Chat Completions 文本规划；无隐式重试或协议猜测。"""
import json
import os

import httpx
from app.production.reasoning import build_payload


class PlannerError(RuntimeError):
    def __init__(self, message, code='provider_error', usage=None):
        super().__init__(message)
        self.code = code
        self.usage = usage or {}


class ChatPlanner:
    def __init__(self, *, client=None):
        self.client = client

    def generate(self, config, messages):
        if config.adapter != 'openai_chat' or config.purpose not in ('text', 'review'):
            raise PlannerError('此执行器仅支持 openai_chat 文本或审核配置。', 'unsupported_adapter')
        key = os.getenv(config.api_key_env, '') if config.api_key_env else ''
        if config.api_key_env and not key:
            raise PlannerError('未找到配置指定的密钥环境变量，请在本机设置后重启服务。', 'missing_key')
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        payload = build_payload(config, messages)
        client = self.client or httpx.Client()
        usage = {}
        try:
            # 路由由明确配置决定；不跟随重定向，不把凭证发送到另一个地址。
            with client.stream('POST', config.base_url + '/chat/completions', json=payload, headers=headers,
                               timeout=httpx.Timeout(config.timeout_seconds, connect=min(15, config.timeout_seconds)),
                               follow_redirects=False) as response:
                if not 200 <= response.status_code < 300:
                    raise PlannerError(f'文本服务请求失败（HTTP {response.status_code}），未自动重试。')
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise PlannerError('文本服务响应过大，未采用结果。', 'invalid_output')
                    chunks.append(chunk)
                data = json.loads(b''.join(chunks))
            raw_usage = data.get('usage') or {}
            usage = {name: raw_usage[name] for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                     if type(raw_usage.get(name)) is int and raw_usage[name] >= 0}
            choice = data['choices'][0]
            if choice.get('finish_reason') == 'length':
                raise PlannerError('模型输出达到长度上限，未采用不完整结果。', 'output_truncated', usage)
            if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
                raise PlannerError('模型输出截断、拒绝或未正常结束，未采用结果。', 'invalid_output', usage)
            output = json.loads(choice['message']['content'])
            if not isinstance(output, dict):
                raise ValueError()
            return output, usage
        except httpx.HTTPError:
            raise PlannerError('文本服务连接失败或超时，外部执行结果可能未知；未自动重试。', 'outcome_unknown', usage) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise PlannerError('模型未返回完整 JSON 对象，未采用结果。', 'invalid_output', usage) from None
        finally:
            if self.client is None:
                client.close()
