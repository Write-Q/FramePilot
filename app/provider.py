"""LangChain 模型适配：图编排与业务校验不依赖具体供应商。"""
import json
import os
from pathlib import Path
from typing import Protocol

import httpx
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from openai import APIConnectionError, APIStatusError, LengthFinishReasonError, ContentFilterFinishReasonError

from app.prompts import COMMON, TASKS
from app.events import emit, progress_sink

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)


class ProviderError(RuntimeError):
    pass


class ModelProvider(Protocol):
    def generate(self, task: str, payload: dict, schema: dict) -> tuple[dict, dict]: ...


class DeepSeekProvider:
    def __init__(self, *, client=None):
        self.key = os.getenv('DEEPSEEK_API_KEY', '')
        self.base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
        self.model = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=httpx.Timeout(90, connect=15))
        # 缺少密钥时仍允许启动工作台，由 generate 返回可读错误。
        self.chat_model = ChatDeepSeek(
            model=self.model, api_key=self.key or 'not-configured',
            api_base=self.base_url, temperature=0.2, max_tokens=5000,
            timeout=90, max_retries=0, http_client=self.client,
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ('system', '{instructions}'), ('human', '{payload_json}'),
        ])

    def generate(self, task, payload, schema):
        if not self.key:
            raise ProviderError('未找到 DEEPSEEK_API_KEY，请设置环境变量或本地 .env。')
        instructions = COMMON + TASKS[task] + '\nJSON Schema:\n' + json.dumps(schema, ensure_ascii=False)
        # JSON mode 的 schema 通过提示词传递；业务层仍负责 Pydantic 和证据校验。
        structured_model = self.chat_model.with_structured_output(
            schema, method='json_mode', include_raw=True,
        )
        chain = self.prompt | structured_model
        try:
            inputs = {'instructions': instructions, 'payload_json': json.dumps(payload, ensure_ascii=False)}
            if progress_sink.get() is not None:
                emit('stage', task=task)
                stream_chain = self.prompt | self.chat_model.bind(response_format={'type':'json_object'})
                raw = None
                for chunk in stream_chain.stream(inputs):
                    if isinstance(chunk.content, str) and chunk.content:
                        emit('delta', task=task, text=chunk.content)
                    raw = chunk if raw is None else raw + chunk
                if raw is None:
                    raise ProviderError('模型未返回内容。')
                result = {}
            else:
                result = chain.invoke(inputs)
                raw = result['raw']
            if raw.response_metadata.get('finish_reason') != 'stop':
                raise ProviderError('模型输出未正常结束，未采用截断结果。')
            if result.get('parsing_error'):
                raise ProviderError('DeepSeek 返回的内容不是有效结构化结果。')
            # LangChain 的 JSON parser 可修复部分 JSON；这里不接受截断或围栏结果。
            content = json.loads(raw.content)
            if not isinstance(content, dict):
                raise ProviderError('模型未返回 JSON 对象。')
            tokens = raw.usage_metadata or {}
            usage = {target: tokens[source] for source, target in (
                ('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens'),
                ('total_tokens', 'total_tokens')) if isinstance(tokens.get(source), int)}
            return content, usage
        except (LengthFinishReasonError, ContentFilterFinishReasonError):
            raise ProviderError('模型输出未正常结束，未采用该结果。') from None
        except APIStatusError as exc:
            raise ProviderError(f'DeepSeek 请求失败（HTTP {exc.status_code}）；未自动重试，请检查账户和配置。') from None
        except (APIConnectionError, httpx.HTTPError):
            raise ProviderError('DeepSeek 网络连接失败或超时；本次请求计入调用额度，未自动重试。') from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError('DeepSeek 返回的内容不是有效结构化结果。') from None

    def close(self):
        if self._owns_client:
            self.client.close()

