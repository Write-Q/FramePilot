"""Default host must never present an invented executable video provider."""
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_story import FakeModel


def test_default_video_adapter_registry_is_empty(database_url):
    with TestClient(create_app(database_url=database_url, provider=FakeModel())) as client:
        response = client.get('/api/production/video-adapters')
        assert response.status_code == 200
        assert response.json() == {'registered': [], 'media_validator_configured': True,
                                   'capabilities_verified': False}
        paths = client.get('/openapi.json').json()['paths']
        assert any(path.endswith('/video-runs') for path in paths)
        assert any(path.endswith('/recover-poll') for path in paths)
