from scripts.evaluate_review_controls import cases
from app.production.contracts import StoryboardContent
from app.production.review_prompt import build_review_packet


def test_controls_are_valid_inputs_and_keep_intentional_semantic_errors():
    controls = {case['id']: case for case in cases()}
    assert len(controls) == 4
    for case in controls.values():
        StoryboardContent.model_validate(case['content'])
        packet = build_review_packet(case['script'], {}, '', case['content'])
        assert packet['manifest']['skills'][0]['version'] == '1.1.0'
    clean = controls['slack']['content']['shots'][0]
    assert sum(b['duration_ms'] for b in clean['action_beats']) < clean['duration_ms']
    assert controls['ownership']['content']['shots'][0]['state_end'] != clean['state_end']
    assert controls['first_frame']['content']['shots'][0]['frame_prompts']['first'] != clean['frame_prompts']['first']
