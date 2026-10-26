"""Selected provider is registered without claiming real capabilities verified."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_story import FakeModel


def test_default_registry_has_ark_and_explicit_empty_override_is_respected(database_url):
    with TestClient(create_app(database_url=database_url, provider=FakeModel())) as client:
        response = client.get('/api/production/video-adapters')
        assert response.status_code == 200
        assert response.json() == {'registered': ['ark_seedance'], 'media_validator_configured': True,
                                   'capabilities_verified': False}
        client.app.state.video_adapters = {}
        assert client.get('/api/production/video-adapters').json()['registered'] == []
        paths = client.get('/openapi.json').json()['paths']
        assert any(path.endswith('/video-runs') for path in paths)
        assert any(path.endswith('/recover-poll') for path in paths)
