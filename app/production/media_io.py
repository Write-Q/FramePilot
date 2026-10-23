"""Bounded, single-attempt image generation and validated immutable local files."""
import base64
import binascii
import hashlib
import io
import json
import os
from pathlib import Path
import re
from dataclasses import dataclass, field
from uuid import uuid4
import warnings

import httpx
from PIL import Image, UnidentifiedImageError

from app.production.chat import PlannerError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_RESPONSE_BYTES = 28 * 1024 * 1024
FORMATS = {'PNG': ('image/png', 'png'), 'JPEG': ('image/jpeg', 'jpg'), 'WEBP': ('image/webp', 'webp')}


@dataclass(frozen=True)
class ImageResult:
    data: bytes
    mime_type: str
    metadata: dict = field(default_factory=dict)


def _inspect(data, mime_type=None):
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise PlannerError('图片为空或超过文件大小限制。', 'invalid_output')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in FORMATS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError()
                actual_mime, suffix = FORMATS[image.format]
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS or min(width, height) < 1:
                    raise ValueError()
                if mime_type is not None and mime_type != actual_mime:
                    raise ValueError()
                image.verify()
            # verify() alone does not decode all compressed pixel data.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        return actual_mime, suffix, {'width': width, 'height': height}
    except (ValueError, OSError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PlannerError('图片格式、解码或尺寸校验失败，仅接受静态 PNG/JPEG/WebP。', 'invalid_output') from None


class MediaFiles:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path(os.getenv('FRAMEPILOT_MEDIA_ROOT') or
            Path(__file__).resolve().parents[2] / 'data' / 'media')
        self.root = self.root.resolve()

    def path(self, storage_key):
        if not isinstance(storage_key, str) or not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg|webp)', storage_key):
            raise ValueError('非法媒体存储标识')
        target = (self.root / storage_key).resolve()
        if target.parent != self.root:
            raise ValueError('媒体路径越界')
        return target

    def put(self, data, mime_type):
        actual_mime, suffix, metadata = _inspect(data, mime_type)
        self.root.mkdir(parents=True, exist_ok=True)
        storage_key = uuid4().hex + '.' + suffix
        target = self.path(storage_key)
        # Exclusive creation: collisions or existing files never get overwritten.
        with target.open('xb') as output:
            output.write(data)
        return {'storage_key': storage_key, 'checksum': hashlib.sha256(data).hexdigest(),
                'size_bytes': len(data), 'mime_type': actual_mime, 'metadata': metadata}


class ImageAdapter:
    def __init__(self, *, client=None):
        self.client = client

    def generate(self, config, prompt, size):
        if config.adapter != 'openai_images' or config.purpose != 'image':
            raise PlannerError('此执行器仅支持 openai_images 图像配置。', 'unsupported_adapter')
        if config.parameters.model_dump(exclude_none=True) or config.reasoning_protocol != 'none' or config.reasoning_levels:
            raise PlannerError('此图像协议不支持文本采样或思考参数，请清空后重试。', 'unsupported_parameters')
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(size, str) or not re.fullmatch(r'[1-9][0-9]{1,4}x[1-9][0-9]{1,4}|auto', size):
            raise PlannerError('图片提示词或尺寸无效。', 'invalid_input')
        if size != 'auto':
            width, height = map(int, size.split('x'))
            if width * height > MAX_IMAGE_PIXELS:
                raise PlannerError('图片请求尺寸超过像素限制。', 'invalid_input')
        key = os.getenv(config.api_key_env, '') if config.api_key_env else ''
        if config.api_key_env and not key:
            raise PlannerError('未找到配置指定的密钥环境变量。', 'missing_key')
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        payload = {'model': config.model, 'prompt': prompt, 'n': 1, 'size': size}
        client = self.client or httpx.Client()
        try:
            with client.stream('POST', config.base_url + '/images/generations', json=payload, headers=headers,
                               timeout=httpx.Timeout(config.timeout_seconds, connect=min(15, config.timeout_seconds)),
                               follow_redirects=False) as response:
                if response.status_code >= 500 or response.status_code == 408:
                    raise PlannerError('图像服务执行结果未知，未自动重试。', 'outcome_unknown')
                if not 200 <= response.status_code < 300:
                    raise PlannerError(f'图像服务请求失败（HTTP {response.status_code}），未自动重试。')
                chunks, count = [], 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    count += len(chunk)
                    if count > MAX_RESPONSE_BYTES:
                        raise PlannerError('图像服务响应超过限制，未采用结果。', 'invalid_output')
                    chunks.append(chunk)
                body = json.loads(b''.join(chunks))
            items = body['data']
            if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
                raise ValueError()
            encoded = items[0].get('b64_json')
            if not encoded and items[0].get('url'):
                raise PlannerError('当前适配器不支持 URL 输出，请选择返回 base64 的图像服务。', 'unsupported_output')
            if not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError()
            data = base64.b64decode(encoded, validate=True)
            mime, _, metadata = _inspect(data)
            return ImageResult(data, mime, metadata)
        except httpx.HTTPError:
            raise PlannerError('图像服务连接失败或超时，执行结果未知；未自动重试。', 'outcome_unknown') from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, binascii.Error):
            raise PlannerError('图像服务未返回完整有效图片，未采用结果。', 'invalid_output') from None
        finally:
            if self.client is None:
                client.close()
