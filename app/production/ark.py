"""Volcengine Ark: one image or one first-frame video. Never retry paid POSTs.

HTTP success is not media validation or a claim about model quality. The existing
media stores inspect images and decode videos before accepting their output.
"""
import base64
import binascii
import json
import os
import re
from urllib.parse import urlsplit

import httpx

from app.production.chat import PlannerError
from app.production.contracts import VideoOptions
from app.production.media_io import ImageResult, MAX_IMAGE_BYTES, MAX_RESPONSE_BYTES, _inspect
from app.production.video_input import VideoPoll, VideoSubmission

ARK_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
MAX_VIDEO_BYTES = 256 * 1024 * 1024
TASK_PATH = '/contents/generations/tasks'


def _common(config, purpose, adapter):
    if config.purpose != purpose or config.adapter != adapter or config.base_url != ARK_BASE_URL:
        raise PlannerError('火山配置须使用北京区域官方 API 地址和对应用途。', 'unsupported_adapter')
    if config.parameters.model_dump(exclude_none=True) or config.reasoning_protocol != 'none' or config.reasoning_levels:
        raise PlannerError('图片和视频不接受文本采样或思考参数。', 'unsupported_parameters')


def _headers(config):
    key = os.getenv(config.api_key_env, '') if config.api_key_env else ''
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise PlannerError('未找到有效的火山 API 密钥环境变量，请在本机配置并重启服务。', 'missing_key')
    return {'Authorization': 'Bearer ' + key}


class _Transport:
    def __init__(self, *, client=None):
        self.client = client

    def _request(self, config, method, url, *, payload=None, download=False, limit=1024 * 1024,
                 invalid_code='invalid_output'):
        client = self.client or httpx.Client(trust_env=False)
        response = None
        try:
            request = client.build_request(method, url, json=payload,
                headers={} if download else _headers(config),
                timeout=httpx.Timeout(config.timeout_seconds, connect=min(15, config.timeout_seconds)))
            if download:
                # Never send Ark credentials, injected client credentials or cookies to TOS.
                request.headers.pop('authorization', None)
                request.headers.pop('cookie', None)
            response = client.send(request, stream=True, follow_redirects=False, auth=None)
            if not 200 <= response.status_code < 300:
                code = ('outcome_unknown' if method == 'POST' and (response.status_code >= 500 or response.status_code == 408)
                        else 'poll_error' if method == 'GET' and (response.status_code >= 500 or response.status_code in (408, 429))
                        else 'provider_error')
                raise PlannerError(f'火山服务请求未完成（HTTP {response.status_code}）；未重新提交生成。', code)
            chunks, count = [], 0
            for chunk in response.iter_bytes(chunk_size=65536):
                count += len(chunk)
                if count > limit:
                    raise PlannerError('火山服务响应超过大小限制，未采用结果。', invalid_code)
                chunks.append(chunk)
            return b''.join(chunks)
        except httpx.HTTPError:
            raise PlannerError('火山服务连接失败或超时；不会自动重新提交生成。',
                'outcome_unknown' if method == 'POST' else 'poll_error') from None
        finally:
            if response is not None:
                response.close()
            if self.client is None:
                client.close()

    def _json(self, config, method, path, *, payload=None, limit=1024 * 1024, invalid_code='invalid_output'):
        raw = self._request(config, method, ARK_BASE_URL + path, payload=payload, limit=limit, invalid_code=invalid_code)
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError, UnicodeError):
            raise PlannerError('火山服务响应不完整或格式无效。', invalid_code) from None


class ArkImageAdapter(_Transport):
    @staticmethod
    def validate_input(config, prompt, size):
        _common(config, 'image', 'ark_seedream')
        match = re.fullmatch(r'doubao-seedream-(5-0-(?:pro|flash|lite)|4-5|4-0)-[0-9]{6}', config.model)
        if not match:
            raise PlannerError('请使用完整 Seedream 4.0/4.5/5.0 Model ID；当前不解析 Endpoint ID。', 'unsupported_adapter')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            raise PlannerError('图片提示词须为非空文本且不超过12000字。', 'invalid_input')
        if not isinstance(size, str) or not re.fullmatch(r'[1-9][0-9]{1,3}x[1-9][0-9]{1,3}', size):
            raise PlannerError('请填写像素尺寸，例如 2560x1440。', 'invalid_input')
        width, height = map(int, size.split('x'))
        family = match[1]
        low = 3686400 if family in ('4-5', '5-0-lite') else 921600
        high = 4624220 if family in ('5-0-pro', '5-0-flash') else 16777216
        if not low <= width * height <= high or not 1 / 16 <= width / height <= 16:
            raise PlannerError(f'此型号要求总像素 {low}–{high}，宽高比 1:16–16:1；请调整图片尺寸。', 'invalid_input')
        _headers(config)
        return family

    def generate(self, config, prompt, size):
        family = self.validate_input(config, prompt, size)
        payload = {'model': config.model, 'prompt': prompt, 'size': size,
                   'response_format': 'b64_json', 'stream': False, 'watermark': True}
        if family not in ('5-0-pro', '5-0-flash'):
            payload['sequential_image_generation'] = 'disabled'
        body = self._json(config, 'POST', '/images/generations', payload=payload, limit=MAX_RESPONSE_BYTES)
        try:
            items = body['data']
            if not isinstance(items, list) or len(items) != 1:
                raise ValueError()
            encoded = items[0]['b64_json']
            if not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError()
            data = base64.b64decode(encoded, validate=True)
            mime, _, metadata = _inspect(data)
            return ImageResult(data, mime, metadata)
        except (ValueError, TypeError, KeyError, IndexError, binascii.Error):
            raise PlannerError('火山未返回唯一且有效的图片数据，未采用结果。', 'invalid_output') from None


class ArkVideoAdapter(_Transport):
    @staticmethod
    def validate_frame(first_frame):
        mime, _, metadata = _inspect(first_frame)
        width, height = metadata['width'], metadata['height']
        if (len(first_frame) > MAX_IMAGE_BYTES or min(width, height) < 300
                or max(width, height) > 6000 or not 0.4 <= width / height <= 2.5):
            raise PlannerError('视频首帧需为300–6000像素边长、宽高比0.4–2.5、20MB以内的静态图片。', 'invalid_input')
        return mime

    @staticmethod
    def validate_input(config, packet):
        _common(config, 'video', 'ark_seedance')
        match = re.fullmatch(r'doubao-seedance-(2-5|2-0(?:-fast|-mini)?)-[0-9]{6}', config.model)
        if not match or not config.capabilities.first_frame:
            raise PlannerError('请使用声明首帧能力的 Seedance 2.0/2.5 完整 Model ID；当前不解析 Endpoint ID。', 'unsupported_adapter')
        options = config.video_options or VideoOptions()
        maximum = 30000 if match[1] == '2-5' else 15000
        duration = packet.get('duration_ms')
        if type(duration) is not int or not 4000 <= duration <= maximum or duration % 1000:
            raise PlannerError(f'此型号要求镜头时长为4–{maximum // 1000}整秒；不会自动改写或取整。', 'invalid_input')
        if not isinstance(packet.get('prompt'), str) or not packet['prompt'].strip() or len(packet['prompt']) > 12000:
            raise PlannerError('视频提示词为空或过长。', 'invalid_input')
        if options.resolution == '1080p' and ('mini' in match[1] or 'fast' in match[1]):
            raise PlannerError('此型号不支持1080p，请选择480p或720p。', 'unsupported_parameters')
        if options.resolution == '1080p' and match[1] == '2-5':
            raise PlannerError('Seedance 2.5 的1080p使用HEVC，当前播放器与验收仅支持H.264；请选720p。', 'unsupported_parameters')
        if packet.get('manifest', {}).get('requires_audio_capability') and not options.generate_audio:
            raise PlannerError('本镜有声音要求，请开启视频配置中的生成声音，或先修订分镜。', 'invalid_input')
        _headers(config)
        return options

    def submit(self, config, packet, first_frame):
        options = self.validate_input(config, packet)
        mime = self.validate_frame(first_frame)
        payload = {'model': config.model, 'content': [{'type': 'text', 'text': packet['prompt']},
            {'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + base64.b64encode(first_frame).decode()}, 'role': 'first_frame'}],
            'duration': packet['duration_ms'] // 1000, 'resolution': options.resolution,
            'ratio': 'adaptive', 'generate_audio': options.generate_audio, 'watermark': options.watermark}
        if config.model.startswith('doubao-seedance-2-5-'):
            payload['output_format'] = 'mp4'
        body = self._json(config, 'POST', TASK_PATH, payload=payload, invalid_code='outcome_unknown')
        identity = body.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity):
            raise PlannerError('未获得有效外部任务编号，提交结果未知；不会重新提交。', 'outcome_unknown')
        return VideoSubmission(identity)

    def poll(self, config, external_id):
        _common(config, 'video', 'ark_seedance')
        if not isinstance(external_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', external_id):
            raise PlannerError('视频外部任务编号无效。', 'invalid_output')
        body = self._json(config, 'GET', TASK_PATH + '/' + external_id)
        if body.get('id') != external_id:
            raise PlannerError('返回的任务编号与原请求不符。', 'invalid_output')
        status = body.get('status')
        if status in ('queued', 'running'):
            return VideoPoll('pending')
        if status in ('failed', 'cancelled', 'expired'):
            return VideoPoll('failed')
        if status != 'succeeded':
            raise PlannerError('视频服务返回未知状态，未采用结果。', 'invalid_output')
        content = body.get('content')
        url = content.get('video_url') if isinstance(content, dict) else None
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            if (not parsed or parsed.scheme != 'https' or not parsed.hostname
                    or not parsed.hostname.endswith('.tos-cn-beijing.volces.com')
                    or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or parsed.fragment or '\\' in url or len(url) > 16000 or any(ord(c) < 33 for c in url)):
                raise ValueError()
        except ValueError:
            raise PlannerError('视频下载地址未通过火山 TOS 地址校验，未下载。', 'invalid_output') from None
        data = self._request(config, 'GET', url, download=True, limit=MAX_VIDEO_BYTES)
        if not data:
            raise PlannerError('视频下载结果为空。', 'invalid_output')
        return VideoPoll('succeeded', data, 'video/mp4')


def video_adapters():
    return {'ark_seedance': ArkVideoAdapter()}
