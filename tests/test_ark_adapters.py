import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from app.production.ark import ARK_BASE_URL, ArkImageAdapter, ArkVideoAdapter
from app.production.chat import PlannerError
from app.production.contracts import ModelConfig


def config(purpose='image', **changes):
    return ModelConfig.model_validate(dict(name='Ark', purpose=purpose,
        adapter='ark_seedream' if purpose == 'image' else 'ark_seedance',
        base_url=ARK_BASE_URL, api_key_env='TEST_ARK_KEY',
        model='doubao-seedream-5-0-flash-260628' if purpose == 'image' else 'doubao-seedance-2-0-260128',
        capabilities={'first_frame': purpose == 'video'}, **changes))


def picture():
    output = BytesIO()
    Image.new('RGB', (640, 360), 'green').save(output, format='PNG')
    return output.getvalue()


def packet(duration=4000, audio=False):
    return {'prompt': '缓慢推进', 'duration_ms': duration,
            'manifest': {'requires_audio_capability': audio}}


def test_default_video_options_are_materialized_in_versioned_config():
    assert config('video').model_dump()['video_options'] == {
        'resolution': '720p', 'generate_audio': False, 'watermark': True}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv('TEST_ARK_KEY', 'test-not-real-key')


def test_seedream_single_image_wire_contract():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(picture()).decode()}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = ArkImageAdapter(client=client).generate(config(), '静态构图', '1536x864')
    assert result.data == picture() and result.mime_type == 'image/png'
    assert json.loads(requests[0].content) == {'model': config().model, 'prompt': '静态构图',
        'size': '1536x864', 'response_format': 'b64_json', 'stream': False, 'watermark': True}
    assert requests[0].headers['authorization'] == 'Bearer test-not-real-key'
    assert str(requests[0].url) == ARK_BASE_URL + '/images/generations'


def test_seedream_45_uses_single_image_and_validates_pixels():
    cfg = config().model_copy(update={'model': 'doubao-seedream-4-5-251128'})
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(picture()).decode()}]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = ArkImageAdapter(client=client)
        with pytest.raises(PlannerError, match='像素'):
            adapter.generate(cfg, '静态构图', '1536x864')
        adapter.generate(cfg, '静态构图', '2560x1440')
    assert len(seen) == 1 and seen[0]['sequential_image_generation'] == 'disabled'


@pytest.mark.parametrize('changes', [dict(base_url='https://other.example/api/v3'),
    dict(model='ep-unknown'), dict(parameters={'seed': 2}), dict(api_key_env='MISSING_ARK_KEY')])
def test_bad_config_never_sends(changes):
    calls = []
    cfg = config().model_dump() | changes
    with httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        with pytest.raises(PlannerError):
            ArkImageAdapter(client=client).generate(ModelConfig.model_validate(cfg), 'prompt', '1536x864')
    assert not calls


@pytest.mark.parametrize('body', [{'data': [{'url': 'https://internal/private'}]},
    {'data': [{'b64_json': '!!!'}]}, {'data': []}, {'data': [{}, {}]}, {}])
def test_invalid_image_response_sanitized(body):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))) as client:
        with pytest.raises(PlannerError) as error:
            ArkImageAdapter(client=client).generate(config(), 'prompt', '1536x864')
    assert error.value.code == 'invalid_output' and 'internal' not in str(error.value)


def test_seedance_first_frame_and_explicit_cost_parameters():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'id': 'cgt-original-task'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        value = ArkVideoAdapter(client=client).submit(config('video'), packet(), picture())
    payload = json.loads(seen[0].content)
    assert value.external_id == 'cgt-original-task'
    assert payload == {'model': config('video').model, 'content': [{'type': 'text', 'text': '缓慢推进'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(picture()).decode()}, 'role': 'first_frame'}],
        'duration': 4, 'resolution': '720p', 'ratio': 'adaptive', 'generate_audio': False, 'watermark': True}


@pytest.mark.parametrize('duration', [3999, 4500, 16000, -1])
def test_duration_not_rounded_or_silently_changed(duration):
    with pytest.raises(PlannerError, match='时长'):
        ArkVideoAdapter().validate_input(config('video'), packet(duration))


def test_audio_intent_cannot_be_silently_dropped():
    with pytest.raises(PlannerError, match='声音'):
        ArkVideoAdapter().validate_input(config('video'), packet(audio=True))
    ArkVideoAdapter().validate_input(config('video', video_options={'generate_audio': True}), packet(audio=True))


def test_seedance_25_requests_mp4_and_rejects_incompatible_hevc_before_submit():
    cfg = config('video').model_copy(update={'model': 'doubao-seedance-2-5-260628'})
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'cgt-25'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        ArkVideoAdapter(client=client).submit(cfg, packet(30000), picture())
    assert seen[0]['output_format'] == 'mp4' and seen[0]['duration'] == 30
    cfg = ModelConfig.model_validate(cfg.model_dump() | {'video_options': {'resolution': '1080p'}})
    with pytest.raises(PlannerError, match='HEVC'):
        ArkVideoAdapter().validate_input(cfg, packet())


@pytest.mark.parametrize('status', [408, 500, 503, 'timeout', 'broken_json'])
def test_submit_unknown_never_retries(status):
    calls = []
    def handle(request):
        calls.append(request)
        if status == 'timeout':
            raise httpx.ReadTimeout('private-key')
        if status == 'broken_json':
            return httpx.Response(200, content=b'{')
        return httpx.Response(status, json={'private-key': 'private-key'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(PlannerError) as error:
        ArkVideoAdapter(client=client).submit(config('video'), packet(), picture())
    assert len(calls) == 1 and error.value.code == 'outcome_unknown'
    assert 'private-key' not in str(error.value)


@pytest.mark.parametrize('status,expected', [('queued', 'pending'), ('running', 'pending'),
    ('failed', 'failed'), ('expired', 'failed'), ('cancelled', 'failed')])
def test_poll_status_mapping(status, expected):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'id': 'cgt-task', 'status': status}))) as client:
        assert ArkVideoAdapter(client=client).poll(config('video'), 'cgt-task').status == expected


def test_video_download_has_no_bearer_and_does_not_leak_signed_url():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.host == 'ark.cn-beijing.volces.com':
            return httpx.Response(200, json={'id': 'cgt-task', 'status': 'succeeded', 'content': {
                'video_url': 'https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/file?signature=secret'}})
        return httpx.Response(200, content=b'mp4-requires-later-real-decoding')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        value = ArkVideoAdapter(client=client).poll(config('video'), 'cgt-task')
    assert value.status == 'succeeded' and value.mime_type == 'video/mp4'
    assert 'authorization' in seen[0].headers and 'authorization' not in seen[1].headers
    assert 'signature' not in repr(value)


@pytest.mark.parametrize('url', ['http://127.0.0.1/secret', 'https://private.example/file',
    'https://evil.tos-cn-beijing.volces.com.evil.test/file', 'https://user@a.tos-cn-beijing.volces.com/file',
    'https://a.tos-cn-beijing.volces.com:444/file'])
def test_untrusted_download_urls_are_never_requested(url):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'id': 'cgt-task', 'status': 'succeeded', 'content': {'video_url': url}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(PlannerError):
        ArkVideoAdapter(client=client).poll(config('video'), 'cgt-task')
    assert len(calls) == 1


def test_download_is_bounded_and_redirect_not_followed(monkeypatch):
    import app.production.ark as module
    monkeypatch.setattr(module, 'MAX_VIDEO_BYTES', 4)
    for response in [httpx.Response(200, content=b'12345'), httpx.Response(302, headers={'location': 'http://internal'})]:
        calls = []
        def handle(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(200, json={'id': 'cgt-task', 'status': 'succeeded', 'content': {
                    'video_url': 'https://ark-content-generation-cn-beijing.tos-cn-beijing.volces.com/file'}})
            return response
        with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(PlannerError):
            ArkVideoAdapter(client=client).poll(config('video'), 'cgt-task')
        assert len(calls) == 2
