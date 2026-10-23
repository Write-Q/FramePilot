"""Cross-module acceptance: deterministic suppliers, real DB/video, restart and staleness."""
from copy import deepcopy
from fastapi.testclient import TestClient
from app.main import create_app
from app.production.media_service import MediaService
from app.production.video_runtime import VideoRuntime
from app.production.video_input import VideoPoll
from tests.test_production import confirmed_project
from tests.test_production_contracts import board_content, model_config
from tests.test_story import FakeModel
from tests.test_storyboard_generation import Planner
from tests.test_shot_media import Images
from tests.test_video_files import make_video
from tests.test_video_runtime import Adapter, make_due


class Review:
    def __init__(self): self.calls = 0
    def generate(self, *args):
        self.calls += 1
        return {'issues': []}, {'total_tokens': 12}


def test_complete_production_restart_and_version_invalidation(database_url, tmp_path, monkeypatch):
    monkeypatch.setenv('FRAMEPILOT_MEDIA_ROOT', str(tmp_path / 'images'))
    monkeypatch.setenv('FRAMEPILOT_VIDEO_ROOT', str(tmp_path / 'videos'))
    content = board_content()
    content['shots'][0].update(frame_prompts={'first': '小禾握着钥匙，阿林空手'},
                              video_prompt='小禾递出钥匙，阿林接住')
    planner, review, image_adapter, video_adapter = Planner(content), Review(), Images(), Adapter()
    app = create_app(database_url=database_url, provider=FakeModel(), storyboard_provider=planner, review_provider=review)
    app.state.video_adapters = {'test_video': video_adapter}
    def post(c, url, payload):
        response = c.post(url, json=payload)
        assert response.status_code in (200, 201), response.text
        return response.json()
    with TestClient(app) as c:
        project = confirmed_project(c)
        profiles = {}
        for purpose, adapter in [('text','openai_chat'), ('review','openai_chat'), ('image','openai_images'), ('video','test_video')]:
            config = model_config() | {'purpose': purpose, 'adapter': adapter, 'api_key_env': ''}
            if purpose == 'video': config['capabilities'] = {'first_frame': True, 'max_duration_ms': 10000}
            value = post(c, '/api/production/model-profiles', config)
            profiles[purpose] = {'profile_id': value['id'], 'version': value['version']}
        base = f'/api/production/projects/{project}'
        planned = post(c, base+'/storyboard-runs', {'source_version':1,'target_shots':1,
            'profile':profiles['text'],'idempotency_key':'system-plan-request-1'})
        assert planned['status'] == 'succeeded'
        board = planned['board']; url = base+'/storyboards/'+board['id']
        report = post(c, url+'/review-runs', {'expected_version':1,'profile':profiles['review'],
            'idempotency_key':'system-review-request-1'})
        assert report['status'] == 'succeeded' and report['applicable']
        post(c, url+'/confirm', {'expected_version':1})
        image = post(c, url+'/media-runs', {'expected_version':1,'shot_key':'shot-1','frame_role':'first',
            'profile':profiles['image'],'idempotency_key':'system-image-request-1','size':'1536x864'})
        images = MediaService(c.app.state.production)
        images.run_once(adapter=image_adapter)
        selected = post(c, url+f'/media-runs/{image["id"]}/select', {'expected_version':1})
        assert c.get(selected['media_url']).status_code == 200
        packet = c.get(url+'/video-input?version=1&shot_key=shot-1').json()
        assert packet['first_frame']['run_id'] == image['id']
        request = {'expected_version':1,'shot_key':'shot-1','profile':profiles['video'],
                   'idempotency_key':'system-video-request-1'}
        run = post(c, url+'/video-runs', request)
        runtime = VideoRuntime(c.app.state.production, adapters=app.state.video_adapters)
        runtime.run_once()
        submitted = c.get(url+'/video-runs').json()['runs'][0]
        assert submitted['external_id'] == 'external-video-1' and submitted['status'] == 'submitted'
    # New application and store instance reads the same persistent external identity.
    restarted = create_app(database_url=database_url, provider=FakeModel(), storyboard_provider=planner, review_provider=review)
    restarted.state.video_adapters = app.state.video_adapters
    with TestClient(restarted) as c:
        assert post(c, url+'/video-runs', request)['id'] == run['id']
        assert len(video_adapter.submits) == 1
        runtime = VideoRuntime(c.app.state.production, adapters=restarted.state.video_adapters)
        make_due(runtime, run['id'])
        encoded = make_video()
        video_adapter.result = VideoPoll('succeeded', encoded, 'video/mp4')
        runtime.run_once()
        success = c.get(url+'/video-runs').json()['runs'][0]
        assert success['status'] == 'succeeded'
        response = c.get(success['media_url'], headers={'Range':'bytes=0-31'})
        assert response.status_code == 206 and response.content == encoded[:32]
        post(c, url+f'/video-runs/{run["id"]}/select', {'expected_version':1})
        newer = deepcopy(board['content']); newer['shots'][0]['camera_motion'] = '固定'
        post(c, url+'/versions', {'expected_version':1,'content':newer})
        post(c, url+'/confirm', {'expected_version':2})
        assert not c.get(url+'/review-runs').json()[0]['applicable']
        assert not c.get(url+'/media-runs?version=2').json()['runs'][0]['applicable']
        assert not c.get(url+'/video-runs?version=2').json()['runs'][0]['applicable']
        assert c.post(url+f'/video-runs/{run["id"]}/select', json={'expected_version':2}).status_code == 409
        assert c.get(url+'/video-input?version=2&shot_key=shot-1').status_code == 409
        assert c.get(success['media_url']).content == encoded  # retained history, no inherited selection
    assert len(planner.calls) == 1 and review.calls == 1 and len(image_adapter.calls) == 1
    assert len(video_adapter.submits) == 1 and len(video_adapter.polls) == 1


def test_thirty_shot_plan_roundtrip_and_revision(database_url):
    content = board_content()
    original = content['shots'][0]
    content['shots'] = [deepcopy(original) | {'key': f'shot-{i+1}'} for i in range(30)]
    planner = Planner(content)
    with TestClient(create_app(database_url=database_url, provider=FakeModel(), storyboard_provider=planner)) as c:
        project = confirmed_project(c)
        profile = c.post('/api/production/model-profiles', json=model_config()).json()
        base = f'/api/production/projects/{project}'
        response = c.post(base+'/storyboard-runs', json={'source_version':1,'target_shots':30,
            'profile':{'profile_id':profile['id'],'version':1},'idempotency_key':'system-thirty-shot-plan'})
        assert response.status_code == 201, response.text
        run = response.json(); assert run['status'] == 'succeeded'
        board = run['board']; url = base+'/storyboards/'+board['id']
        assert len(c.get(url).json()['content']['shots']) == 30
        changed = deepcopy(board['content']); changed['shots'].reverse()
        saved = c.post(url+'/versions', json={'expected_version':1,'content':changed})
        assert saved.status_code == 201, saved.text
        assert c.get(url+'/versions/1').json()['content']['shots'][0]['key'] == 'shot-1'
        assert c.get(url).json()['content']['shots'][0]['key'] == 'shot-30'
        assert c.post(url+'/confirm', json={'expected_version':2}).status_code == 200
    assert len(planner.calls) == 1
