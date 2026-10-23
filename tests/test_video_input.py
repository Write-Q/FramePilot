from copy import deepcopy

import pytest

from app.production.video_input import build_video_input, VideoAdapter, VideoSubmission, VideoPoll


def inputs():
    board = {'version_id': 'bv1', 'version': 1, 'current_version': 1, 'source_current': True,
             'source_confirmed': True, 'confirmed': True, 'confirmation_effective': True,
             'project_id': 'p1', 'content': {'title': '测试',
                 'scenes': [{'key': 'scene', 'title': '厨房', 'source_quote': '原文'}],
                 'shots': [{'key': 'shot', 'scene_key': 'scene', 'source_quote': '原文',
                            'purpose': '推进', 'action': '未采用的其他动作', 'duration_ms': 4321,
                            'video_prompt': '小明缓缓推开门，然后停步。', 'camera_motion': '缓慢推镜',
                            'dialogue_lines': [{'speaker': '小明', 'text': '谁在里面？'}], 'sound': '门轴声'}]}}
    image = {'id': 'run1', 'media_id': 'media1', 'storyboard_version_id': 'bv1',
             'shot_key': 'shot', 'frame_role': 'first', 'status': 'succeeded', 'selected': True,
             'manifest': {'prompt': 'private frame prompt'}}
    return board, image


def test_packet_preserves_explicit_intent_duration_and_real_first_frame():
    board, image = inputs()
    before = deepcopy((board, image))
    packet = build_video_input(board, 'shot', image)
    assert packet['duration_ms'] == 4321
    assert packet['first_frame'] == {'media_id': 'media1', 'run_id': 'run1'}
    assert '小明缓缓推开门，然后停步。' in packet['prompt']
    assert packet['prompt'].count('缓慢推镜') == 1
    assert '谁在里面？' in packet['prompt'] and '门轴声' in packet['prompt']
    assert '未采用的其他动作' not in packet['prompt']
    assert 'private frame prompt' not in str(packet)
    assert packet['manifest']['validation'] == 'input_contract_only; provider_and_media_validation_pending'
    assert build_video_input(board, 'shot', image) == packet
    assert (board, image) == before


@pytest.mark.parametrize('field,value', [('source_current', False), ('source_confirmed', False),
    ('confirmed', False), ('confirmation_effective', False), ('current_version', 2)])
def test_stale_or_unconfirmed_board_rejected(field, value):
    board, image = inputs()
    board[field] = value
    with pytest.raises(ValueError):
        build_video_input(board, 'shot', image)


@pytest.mark.parametrize('field,value', [('selected', False), ('selected', 1), ('status', 'running'),
    ('frame_role', 'last'), ('shot_key', 'other'), ('storyboard_version_id', 'old'), ('id', ''), ('media_id', None)])
def test_wrong_first_frame_rejected(field, value):
    board, image = inputs()
    image[field] = value
    with pytest.raises(ValueError):
        build_video_input(board, 'shot', image)


def test_no_motion_fallback_and_no_duplicate_camera():
    board, image = inputs()
    board['content']['shots'][0]['video_prompt'] += '缓慢推镜'
    assert build_video_input(board, 'shot', image)['prompt'].count('缓慢推镜') == 1
    board['content']['shots'][0]['video_prompt'] = ''
    with pytest.raises(ValueError):
        build_video_input(board, 'shot', image)


def test_missing_shot_and_missing_input_safe_errors():
    board, image = inputs()
    for b, shot, i in [(board, 'missing', image), ({}, 'shot', image), (board, 'shot', None)]:
        with pytest.raises(ValueError):
            build_video_input(b, shot, i)


@pytest.mark.parametrize('field,value', [('project_id', 'other-project'), ('kind', 'video')])
def test_optional_record_identity_cannot_conflict(field, value):
    board, image = inputs()
    image[field] = value
    with pytest.raises(ValueError):
        build_video_input(board, 'shot', image)


def test_silent_input_does_not_invent_audio_or_camera_requirements():
    board, image = inputs()
    shot = board['content']['shots'][0]
    shot.update(camera_motion='', dialogue_lines=[], sound='')
    packet = build_video_input(board, 'shot', image)
    assert packet['prompt'] == '视频运动意图：' + shot['video_prompt']
    assert packet['manifest']['requires_audio_capability'] is False


def test_plain_dialogue_and_style_are_preserved():
    board, image = inputs()
    board['content']['visual_style'] = '手绘风格'
    board['content']['shots'][0].update(dialogue_lines=[], dialogue='VO：不要回头。')
    packet = build_video_input(board, 'shot', image)
    assert 'VO：不要回头。' in packet['prompt'] and '手绘风格' in packet['prompt']
    assert packet['manifest']['requires_audio_capability'] is True


def test_bad_content_error_hides_supplied_data():
    board, image = inputs()
    board['content'] = {'private': 'should-not-leak'}
    with pytest.raises(ValueError) as caught:
        build_video_input(board, 'shot', image)
    assert 'should-not-leak' not in str(caught.value)


@pytest.mark.parametrize('value', ['', '  ', None, 3, 'id\nsecret'])
def test_external_id_is_validated(value):
    with pytest.raises(ValueError):
        VideoSubmission(value)


@pytest.mark.parametrize('kwargs', [{'status': 'unknown'}, {'status': 'succeeded'},
    {'status': 'pending', 'output': b'not-real-video', 'mime_type': 'video/mp4'},
    {'status': 'failed', 'output': b'data'}, {'status': 'succeeded', 'output': b'', 'mime_type': 'video/mp4'},
    {'status': 'succeeded', 'output': 'https://example.test/a.mp4', 'mime_type': 'video/mp4'},
    {'status': 'succeeded', 'output': b'data', 'mime_type': 'image/png'}])
def test_poll_contract_rejects_invalid_combinations(kwargs):
    with pytest.raises(ValueError):
        VideoPoll(**kwargs)


def test_submit_once_poll_separately_contract_not_media_validation():
    class FakeAdapter:
        def __init__(self):
            self.submissions = []
            self.polls = []

        def submit(self, config, packet, first_frame):
            self.submissions.append((config, packet, first_frame))
            return VideoSubmission('external-123')

        def poll(self, config, external_id):
            self.polls.append(external_id)
            return VideoPoll('pending') if len(self.polls) == 1 else VideoPoll('succeeded', b'mock-bytes', 'video/mp4')

    adapter = FakeAdapter()
    assert isinstance(adapter, VideoAdapter)
    board, image = inputs()
    submission = adapter.submit(None, build_video_input(board, 'shot', image), b'fake-first-frame')
    assert adapter.poll(None, submission.external_id).status == 'pending'
    assert adapter.poll(None, submission.external_id).status == 'succeeded'
    assert len(adapter.submissions) == 1
    assert adapter.polls == ['external-123', 'external-123']
    assert VideoPoll('failed').output is None
