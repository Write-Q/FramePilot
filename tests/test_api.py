import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_story import FakeModel, STORY


@pytest.fixture
def client(database_url):
    with TestClient(create_app(database_url=database_url, provider=FakeModel())) as value:
        yield value


def test_create_get_confirm(client):
    response = client.post('/api/projects', json={'story': STORY})
    assert response.status_code == 201
    project = response.json()
    assert project['state']['status'] == 'awaiting_confirmation'
    assert client.get('/api/projects/' + project['id']).status_code == 200
    assert len(client.get('/api/projects/' + project['id'] + '/versions').json()) == 1
    confirmed = client.post('/api/projects/' + project['id'] + '/resume', json={
        'action': 'confirm', 'version': 1, 'interrupt_id': project['interrupt']['id']})
    assert confirmed.json()['state']['status'] == 'confirmed'


def test_input_missing_and_pages(client):
    assert client.post('/api/projects', json={'story': '  '}).status_code == 422
    assert client.get('/api/projects/missing').status_code == 404
    assert client.get('/').status_code == 200
    assert '/static/swagger/swagger-ui-bundle.js' in client.get('/docs').text
    assert client.get('/static/swagger/swagger-ui-bundle.js').status_code == 200
    assert 'DEEPSEEK_API_KEY' not in client.get('/api/health').text
