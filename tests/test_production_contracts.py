"""制作底座的数据契约：配置不能携带秘密值，镜头引用必须可定位。"""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.production.contracts import ModelConfig, StoryboardContent


def model_config(**changes):
    return dict(name='分镜规划', purpose='text', adapter='openai_chat',
                base_url='https://example.test/v1', model='model-a',
                api_key_env='FP_PLANNER_KEY', **changes)


def board_content():
    return {'schema_version': 1, 'title': '钥匙', 'aspect_ratio': '16:9',
            'scenes': [{'key': 'scene-1', 'title': '门前', 'source_quote': '小禾把唯一的钥匙交给阿林。'}],
            'shots': [{'key': 'shot-1', 'scene_key': 'scene-1', 'source_quote': '钥匙交给阿林',
                       'purpose': '交代钥匙归属', 'action': '小禾将钥匙递给阿林',
                       'duration_ms': 4000, 'shot_size': '中景', 'camera_angle': '平视',
                       'camera_motion': '缓慢推进', 'state_start': '钥匙在小禾手中',
                       'state_end': '钥匙在阿林手中'}]}


def test_config_keeps_only_environment_secret_reference():
    config = ModelConfig(**model_config())
    assert config.api_key_env == 'FP_PLANNER_KEY'
    assert config.timeout_seconds > 0
    assert 'api_key' not in config.model_dump()


@pytest.mark.parametrize('change', [
    {'base_url': 'https://user:password@example.test/v1'},
    {'base_url': 'https://example.test/v1?api_key=secret'},
    {'base_url': 'file:///tmp/models'},
    {'api_key_env': 'not-an-env-name'},
    {'api_key': 'secret'},
    {'parameters': {'api_key': 'secret'}},
    {'parameters': {'extra_headers': {'Authorization': 'secret'}}},
    {'parameters': {'max_tokens': 0}},
    {'parameters': {'temperature': float('nan')}},
])
def test_config_rejects_credentials_and_uncontrolled_parameters(change):
    value = model_config()
    value.update(change)
    with pytest.raises(ValidationError):
        ModelConfig(**value)


@pytest.mark.parametrize('purpose', ['text', 'image', 'video', 'review', 'asr', 'tts'])
def test_model_purposes_are_separate(purpose):
    value = model_config()
    value.update(purpose=purpose, adapter='vendor_native')
    assert ModelConfig(**value).purpose == purpose


def test_storyboard_has_stable_keys_and_integer_durations():
    board = StoryboardContent(**board_content())
    assert board.shots[0].key == 'shot-1'
    assert board.shots[0].duration_ms == 4000


@pytest.mark.parametrize('kind', ['duplicate_shot', 'missing_scene', 'negative_duration',
                                  'fractional_duration', 'duplicate_scene', 'empty_shots'])
def test_invalid_storyboards_are_rejected(kind):
    value = board_content()
    if kind == 'duplicate_shot':
        value['shots'].append(deepcopy(value['shots'][0]))
    elif kind == 'missing_scene':
        value['shots'][0]['scene_key'] = 'missing'
    elif kind == 'negative_duration':
        value['shots'][0]['duration_ms'] = -1
    elif kind == 'fractional_duration':
        value['shots'][0]['duration_ms'] = 1.5
    elif kind == 'duplicate_scene':
        value['scenes'].append(deepcopy(value['scenes'][0]))
    else:
        value['shots'] = []
    with pytest.raises(ValidationError):
        StoryboardContent(**value)


def test_professional_shot_context_keeps_frames_beats_and_screen_direction_separate():
    value = board_content()
    value['visual_style'] = '克制的写实风格'
    value['shots'][0].update(
        composition='小禾在左、阿林在右，双手与钥匙可见',
        screen_direction='小禾向右看，阿林向左看',
        lighting='沿用已确认门前场景光照',
        action_beats=[{'description': '小禾伸出持钥匙的手', 'duration_ms': 2000},
                      {'description': '阿林接住钥匙', 'duration_ms': 2000}],
        frame_prompts={'first': '钥匙仍在小禾手中', 'key': '两人的手交接钥匙',
                       'last': '钥匙已在阿林手中'})
    board = StoryboardContent(**value)
    shot = board.shots[0]
    assert shot.frame_prompts.first != shot.frame_prompts.last
    assert len(shot.action_beats) == 2
    assert shot.screen_direction


def test_planned_action_beats_cannot_exceed_shot_duration():
    value = board_content()
    value['shots'][0]['action_beats'] = [{'description': '交接钥匙', 'duration_ms': 5000}]
    with pytest.raises(ValidationError, match='动作节拍规划时长'):
        StoryboardContent(**value)


def test_validation_errors_do_not_echo_arbitrary_dictionary_keys():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from app.production.api import PrivateValidationRoute
    router = APIRouter(route_class=PrivateValidationRoute)
    @router.post('/config')
    def configure(request: ModelConfig):
        return {'ok': True}
    app = FastAPI()
    app.include_router(router)
    payload = model_config()
    payload['parameters'] = {'accidentally-pasted-secret-as-key': 'x'}
    response = TestClient(app).post('/config', json=payload)
    assert response.status_code == 422
    assert 'accidentally-pasted-secret-as-key' not in response.text
    assert 'parameters' in response.text
