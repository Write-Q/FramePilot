import pytest

from app.production.frame_prompt import build_frame_prompt


def board():
    return {'title': '板', 'visual_style': '水彩', 'scenes': [{'key': 's1', 'title': '夜晚厨房', 'source_quote': '原文'}],
            'shots': [{'key': 'a', 'scene_key': 's1', 'source_quote': '原文', 'purpose': '目的',
                       'action': '奔跑后开门', 'duration_ms': 1000, 'camera_motion': '快速推镜',
                       'dialogue': '秘密对白', 'sound': '警报声', 'characters': ['小明'],
                       'composition': '人物居左', 'frame_prompts': {'first': '手停在门把上', 'key': '门半开', 'last': '站在门外'}}]}


@pytest.mark.parametrize('role,phrase', [('first', '手停在门把上'), ('key', '门半开'), ('last', '站在门外')])
def test_static_prompt_uses_selected_frame_and_context(role, phrase):
    result = build_frame_prompt(board(), 'a', role)
    assert all(t in result['prompt'] for t in (phrase, '水彩', '夜晚厨房', '小明', '人物居左'))
    assert all(t not in result['prompt'] for t in ('奔跑后开门', '快速推镜', '秘密对白', '警报声'))
    assert result['manifest']['reference_images'] == []
    assert result['manifest']['workflow_version'] == 'frame-prompt-1.0.0'
    assert result == build_frame_prompt(board(), 'a', role)


def test_missing_frame_is_not_filled_from_motion_or_legacy_image_prompt():
    content = board()
    content['shots'][0]['frame_prompts'] = {}
    content['shots'][0]['image_prompt'] = 'legacy'
    with pytest.raises(ValueError):
        build_frame_prompt(content, 'a', 'first')
    assert '用户自填' in build_frame_prompt(content, 'a', 'first', '用户自填')['prompt']


@pytest.mark.parametrize('key,role', [('absent', 'first'), ('a', 'other')])
def test_reject_invalid_target(key, role):
    with pytest.raises(ValueError):
        build_frame_prompt(board(), key, role)


@pytest.mark.parametrize('text', ['{{ref 1}} 在左边', '@图2人物', '根据参考图1绘制'])
def test_reference_placeholders_cannot_pretend_images_were_supplied(text):
    with pytest.raises(ValueError):
        build_frame_prompt(board(), 'a', 'first', text)


def test_preview_can_be_submitted_without_wrapping_again():
    first = build_frame_prompt(board(), 'a', 'first')['prompt']
    assert build_frame_prompt(board(), 'a', 'first', first)['prompt'] == first
