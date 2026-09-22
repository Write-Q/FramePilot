from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_story import FakeModel, STORY

def test_direct_export_and_diff(tmp_path):
    with TestClient(create_app(data_dir=tmp_path,provider=FakeModel(fail=True))) as c:
        p=c.post('/api/projects',json={'story':STORY,'mode':'direct'}).json()
        export=c.get('/api/projects/'+p['id']+'/export')
        assert export.status_code==200
        assert STORY in export.text
        assert '未经故事审核' in export.text
        assert c.get('/api/projects/'+p['id']+'/diff?from_version=1&to_version=999').status_code==404

def test_manual_retry_keeps_budget_and_project(tmp_path):
    model=FakeModel(fail=True)
    with TestClient(create_app(data_dir=tmp_path,provider=model)) as c:
        p=c.post('/api/projects',json={'story':STORY}).json()
        assert p['state']['status']=='failed'
        model.fail=False
        retry=c.post('/api/projects/'+p['id']+'/retry').json()
        assert retry['state']['status']=='awaiting_confirmation'
        assert retry['calls_used']==3
        assert retry['id']==p['id']
        assert c.post('/api/projects/'+p['id']+'/retry').status_code==409
