"""真实PostgreSQL + HTTP验证，不调用外部模型或升级业务库。"""
from copy import deepcopy

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from tests.test_production_contracts import model_config, board_content
from tests.test_story import FakeModel, STORY


@pytest.fixture
def client(database_url):
    with TestClient(create_app(database_url=database_url, provider=FakeModel())) as value:
        yield value


def confirmed_project(client):
    project = client.post('/api/projects', json={'story': STORY}).json()
    response = client.post(f"/api/projects/{project['id']}/resume", json={
        'action': 'confirm', 'version': project['state']['version'],
        'interrupt_id': project['interrupt']['id']})
    assert response.status_code == 200, response.text
    return project['id']


def test_model_configuration_history_restart_and_conflict(client, database_url, monkeypatch):
    monkeypatch.setenv('FP_PLANNER_KEY', 'secret-never-return-this')
    url = '/api/production/model-profiles'
    created = client.post(url, json=model_config())
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile['version'] == 1
    assert profile['executable'] is True
    assert profile['capabilities_verified'] is False
    changed = model_config()
    changed['model'] = 'model-b'
    updated = client.put(f"{url}/{profile['id']}", json={'expected_version': 1, 'config': changed})
    assert updated.status_code == 200, updated.text
    assert updated.json()['version'] == 2
    assert client.put(f"{url}/{profile['id']}", json={'expected_version': 1, 'config': changed}).status_code == 409
    old = client.get(f"{url}/{profile['id']}/versions/1")
    assert old.json()['config']['model'] == 'model-a'
    assert client.get(f"{url}/{profile['id']}/versions/99").status_code == 404
    listing = client.get(url)
    assert listing.json()[0]['config']['model'] == 'model-b'
    assert 'secret-never-return-this' not in listing.text + old.text
    with TestClient(create_app(database_url=database_url, provider=FakeModel())) as restarted:
        assert restarted.get(f"{url}/{profile['id']}").json()['version'] == 2


def test_config_validation_never_echoes_secret_inputs(client):
    payload = model_config()
    payload['api_key'] = 'mistaken-secret-input'
    response = client.post('/api/production/model-profiles', json=payload)
    assert response.status_code == 422
    assert 'mistaken-secret-input' not in response.text
    payload = model_config()
    payload['base_url'] = 'https://user:embedded-secret@example.test'
    response = client.post('/api/production/model-profiles', json=payload)
    assert response.status_code == 422
    assert 'embedded-secret' not in response.text


def test_storyboard_handoff_revision_confirmation_and_project_isolation(client):
    project = confirmed_project(client)
    url = f'/api/production/projects/{project}/storyboards'
    initial = board_content()
    created = client.post(url, json={'source_version': 1, 'content': initial})
    assert created.status_code == 201, created.text
    board = created.json()
    assert board['version'] == 1 and not board['confirmed']
    assert board['source_current'] and board['source_confirmed']
    assert board['total_duration_ms'] == 4000
    target = f"{url}/{board['id']}"
    response = client.post(target + '/confirm', json={'expected_version': 1})
    assert response.status_code == 200, response.text
    assert response.json()['confirmation_effective']
    assert client.post(target + '/confirm', json={'expected_version': 1}).status_code == 200
    revised = deepcopy(initial)
    revised['shots'][0]['duration_ms'] = 3000
    new_shot = deepcopy(revised['shots'][0])
    new_shot.update(key='shot-2', shot_size='特写')
    revised['shots'].insert(0, new_shot)
    response = client.post(target + '/versions', json={'expected_version': 1, 'content': revised})
    assert response.status_code == 201, response.text
    assert response.json()['version'] == 2 and not response.json()['confirmed']
    assert [s['key'] for s in response.json()['content']['shots']] == ['shot-2', 'shot-1']
    assert client.post(target + '/versions', json={'expected_version': 1, 'content': revised}).status_code == 409
    assert client.post(target + '/confirm', json={'expected_version': 1}).status_code == 409
    old = client.get(target + '/versions/1').json()
    assert old['content']['shots'][0]['duration_ms'] == 4000
    assert old['confirmed'] and old['confirmation_effective']
    assert client.get(url).json()[0]['version'] == 2
    other = confirmed_project(client)
    assert client.get(f"/api/production/projects/{other}/storyboards/{board['id']}").status_code == 404
    story = client.get(f'/api/projects/{project}').json()
    assert story['state']['draft'] == STORY and story['state']['version'] == 1


def test_unconfirmed_and_direct_script_handoffs_are_rejected(client):
    for mode in ['collaborative', 'direct']:
        project = client.post('/api/projects', json={'story': STORY, 'mode': mode}).json()
        response = client.post(f"/api/production/projects/{project['id']}/storyboards", json={
            'source_version': 1, 'content': board_content()})
        assert response.status_code == 409, response.text


def test_quotes_bindings_and_fixed_scene_breakdown_are_validated(client):
    project = confirmed_project(client)
    url = f'/api/production/projects/{project}/storyboards'
    content = board_content()
    content['scenes'][0]['source_quote'] = '模型杜撰的剧情'
    assert client.post(url, json={'source_version': 1, 'content': content}).status_code == 422
    content = board_content()
    content['shots'][0]['source_quote'] = '小禾随后用这把钥匙打开门'
    assert client.post(url, json={'source_version': 1, 'content': content}).status_code == 422
    profile = client.post('/api/production/model-profiles', json=model_config()).json()
    content = board_content()
    content['bindings'] = {'video': {'profile_id': profile['id'], 'version': 1}}
    assert client.post(url, json={'source_version': 1, 'content': content}).status_code == 422
    content['bindings'] = {'text': {'profile_id': profile['id'], 'version': 1}}
    created = client.post(url, json={'source_version': 1, 'content': content})
    assert created.status_code == 201, created.text
    board = created.json()
    changed = model_config()
    changed['model'] = 'new-model'
    client.put('/api/production/model-profiles/' + profile['id'], json={'expected_version': 1, 'config': changed})
    assert client.get(url + '/' + board['id']).json()['content']['bindings']['text']['version'] == 1
    content['scenes'][0]['title'] = '不同的场戏拆解'
    assert client.post(url + '/' + board['id'] + '/versions', json={
        'expected_version': 1, 'content': content}).status_code == 409


def test_upstream_changes_invalidate_confirmation_without_rewriting_history(client, database_url):
    from app.models import Project
    from app.legacy_domain import sync_project
    from sqlalchemy.orm import Session
    project = confirmed_project(client)
    url = f'/api/production/projects/{project}/storyboards'
    board = client.post(url, json={'source_version': 1, 'content': board_content()}).json()
    target = url + '/' + board['id']
    assert client.post(target + '/confirm', json={'expected_version': 1}).status_code == 200
    engine = sa.create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            row = session.get(Project, project)
            snapshot = deepcopy(row.snapshot)
            snapshot['state']['status'] = 'awaiting_confirmation'
            row.snapshot = snapshot
            session.flush()
            sync_project(session.connection(), project)
        loaded = client.get(target).json()
        assert loaded['confirmed'] and not loaded['confirmation_effective']
        assert not loaded['source_confirmed']
        assert client.post(target + '/confirm', json={'expected_version': 1}).status_code == 409
    finally:
        engine.dispose()


def test_configuration_history_is_database_immutable(client, database_url):
    profile = client.post('/api/production/model-profiles', json=model_config()).json()
    engine = sa.create_engine(database_url)
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(sa.text('UPDATE fp_model_profile_versions SET config=\'{}\'::jsonb WHERE profile_id=:id'),
                               {'id': profile['id']})
    finally:
        engine.dispose()


def test_concurrent_profile_updates_accept_only_one_expected_version(client):
    from concurrent.futures import ThreadPoolExecutor
    profile = client.post('/api/production/model-profiles', json=model_config()).json()
    url = '/api/production/model-profiles/' + profile['id']
    def update(name):
        config = model_config()
        config['model'] = name
        return client.put(url, json={'expected_version': 1, 'config': config}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(update, ['model-b', 'model-c']))
    assert sorted(results) == [200, 409]
    assert client.get(url).json()['version'] == 2
    assert client.get(url + '/versions/1').json()['config']['model'] == 'model-a'


def test_concurrent_storyboard_edits_preserve_history(client):
    from concurrent.futures import ThreadPoolExecutor
    project = confirmed_project(client)
    url = f'/api/production/projects/{project}/storyboards'
    board = client.post(url, json={'source_version': 1, 'content': board_content()}).json()
    target = url + '/' + board['id']
    def edit(duration):
        content = board_content()
        content['shots'][0]['duration_ms'] = duration
        return client.post(target + '/versions', json={'expected_version': 1, 'content': content}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, [3000, 3500]))
    assert sorted(results) == [201, 409]
    assert client.get(target).json()['version'] == 2
    assert client.get(target + '/versions/1').json()['content']['shots'][0]['duration_ms'] == 4000


def test_missing_profile_version_and_stale_script_do_not_create_partial_rows(client, database_url):
    project = confirmed_project(client)
    url = f'/api/production/projects/{project}/storyboards'
    content = board_content()
    content['bindings'] = {'text': {'profile_id': 'missing', 'version': 1}}
    assert client.post(url, json={'source_version': 1, 'content': content}).status_code == 422
    assert client.post(url, json={'source_version': 99, 'content': board_content()}).status_code == 409
    assert client.get(url).json() == []
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as conn:
            for name in ['fp_breakdown_versions', 'fp_scenes', 'fp_storyboard_versions', 'fp_shots']:
                assert conn.execute(sa.text(f'SELECT count(*) FROM {name} WHERE project_id=:id'),
                                    {'id': project}).scalar_one() == 0
    finally:
        engine.dispose()


def test_downgrade_refuses_to_delete_saved_profiles(client, database_url):
    from alembic import command
    from alembic.config import Config
    from app.database import ROOT
    profile = client.post('/api/production/model-profiles', json=model_config()).json()
    config = Config(str(ROOT / 'alembic.ini'))
    config.attributes['database_url'] = database_url
    with pytest.raises(RuntimeError, match='非空'):
        command.downgrade(config, '0004_story_game')
    assert client.get('/api/production/model-profiles/' + profile['id']).status_code == 200
