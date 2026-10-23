import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app.production.chat import PlannerError
from app.production.contracts import ModelConfig
from app.production.media_io import ImageAdapter, MediaFiles


def png():
    output = io.BytesIO()
    Image.new('RGB', (3, 2), 'red').save(output, format='PNG')
    return output.getvalue()


def config(**updates):
    return ModelConfig(name='image', purpose='image', adapter='openai_images', base_url='https://example.test/v1', model='explicit-model', **updates)


def test_store_validated_image_without_overwriting(tmp_path):
    store = MediaFiles(tmp_path)
    first = store.put(png(), 'image/png')
    second = store.put(png(), 'image/png')
    assert first['storage_key'] != second['storage_key']
    assert first['checksum'] == second['checksum']
    assert first['metadata'] == {'width': 3, 'height': 2}
    assert first['size_bytes'] == len(png())
    assert store.path(first['storage_key']).read_bytes() == png()


@pytest.mark.parametrize('key', ['../secret', '/etc/passwd', 'C:\\secret', 'aa/../../secret', 'x\\y', '', 'aa/not.png'])
def test_paths_are_strictly_scoped(tmp_path, key):
    with pytest.raises(ValueError):
        MediaFiles(tmp_path).path(key)


@pytest.mark.parametrize('data,mime', [(b'fake', 'image/png'), (b'<svg/>', 'image/svg+xml'), (png(), 'image/jpeg'), (png()[:30], 'image/png')])
def test_reject_invalid_images_before_write(tmp_path, data, mime):
    with pytest.raises(PlannerError):
        MediaFiles(tmp_path).put(data, mime)
    assert not list(tmp_path.rglob('*'))


def test_decode_limits(tmp_path, monkeypatch):
    import app.production.media_io as module
    monkeypatch.setattr(module, 'MAX_IMAGE_PIXELS', 5)
    with pytest.raises(PlannerError):
        MediaFiles(tmp_path).put(png(), 'image/png')
    monkeypatch.setattr(module, 'MAX_IMAGE_BYTES', 2)
    with pytest.raises(PlannerError):
        MediaFiles(tmp_path).put(png(), 'image/png')


def test_adapter_base64_and_exact_wire_contract(monkeypatch):
    monkeypatch.setenv('TEST_IMAGE_KEY', 'secret-value')
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode(), 'revised_prompt': 'private-provider-data'}], 'secret': 'private-provider-data'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = ImageAdapter(client=client).generate(config(api_key_env='TEST_IMAGE_KEY'), '静态画面', '1024x1024')
    assert result.data == png() and result.mime_type == 'image/png'
    assert result.metadata == {'width': 3, 'height': 2}
    assert str(seen[0].url) == 'https://example.test/v1/images/generations'
    assert json.loads(seen[0].content) == {'model': 'explicit-model', 'prompt': '静态画面', 'n': 1, 'size': '1024x1024'}
    assert seen[0].headers['authorization'] == 'Bearer secret-value'


@pytest.mark.parametrize('status,body,code', [(500, {'secret': 'leak'}, 'outcome_unknown'), (400, {'secret': 'leak'}, 'provider_error'), (200, {'data': [{'url': 'http://internal/secret'}]}, 'unsupported_output'), (200, {'data': [{'b64_json': '%%%'}]}, 'invalid_output')])
def test_errors_are_sanitized_and_not_retried(status, body, code):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(PlannerError) as caught:
        ImageAdapter(client=client).generate(config(), 'prompt', '1024x1024')
    assert caught.value.code == code
    assert 'leak' not in str(caught.value) and 'internal' not in str(caught.value)
    assert len(calls) == 1


def test_timeout_is_unknown():
    def handle(request):
        raise httpx.ReadTimeout('credential-leak')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(PlannerError) as caught:
        ImageAdapter(client=client).generate(config(), 'prompt', '1024x1024')
    assert caught.value.code == 'outcome_unknown'
    assert 'credential' not in str(caught.value)


@pytest.mark.parametrize('fmt,mime', [('JPEG', 'image/jpeg'), ('WEBP', 'image/webp')])
def test_other_allowed_decoders(tmp_path, fmt, mime):
    output = io.BytesIO()
    Image.new('RGB', (4, 5)).save(output, format=fmt)
    assert MediaFiles(tmp_path).put(output.getvalue(), mime)['metadata'] == {'width': 4, 'height': 5}


def test_response_limit(monkeypatch):
    import app.production.media_io as module
    monkeypatch.setattr(module, 'MAX_RESPONSE_BYTES', 10)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x' * 11))) as client:
        with pytest.raises(PlannerError) as caught:
            ImageAdapter(client=client).generate(config(), 'prompt', '1024x1024')
    assert caught.value.code == 'invalid_output'


def test_missing_key_prevents_request(monkeypatch):
    monkeypatch.delenv('ABSENT_TEST_IMAGE_KEY', raising=False)
    with pytest.raises(PlannerError) as caught:
        ImageAdapter().generate(config(api_key_env='ABSENT_TEST_IMAGE_KEY'), 'prompt', '1024x1024')
    assert caught.value.code == 'missing_key'


def test_redirect_is_not_followed():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={'location': 'https://other.test/secret'})
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(PlannerError):
            ImageAdapter(client=client).generate(config(), 'prompt', '1024x1024')
    assert len(calls) == 1


@pytest.mark.parametrize('params', [{'temperature': 0.5}, {'max_tokens': 200}, {'seed': 1}])
def test_text_parameters_are_not_silently_ignored(params):
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500))) as client, pytest.raises(PlannerError) as caught:
        ImageAdapter(client=client).generate(config(parameters=params), 'prompt', '1024x1024')
    assert caught.value.code == 'unsupported_parameters'
    assert not calls


@pytest.mark.parametrize('size', ['1024', '0x1024', '99999x99999', '', '1024x1024\n'])
def test_invalid_size_never_calls_provider(size):
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500))) as client, pytest.raises(PlannerError) as caught:
        ImageAdapter(client=client).generate(config(), 'prompt', size)
    assert caught.value.code == 'invalid_input'
    assert not calls
