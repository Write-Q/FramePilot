"""Explicit, bounded live review controls. No database writes or automatic retries."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv
import httpx

from app.production.chat import ChatPlanner, PlannerError
from app.production.contracts import ModelConfig, StoryboardContent
from app.production.review_contracts import ReviewReport
from app.production.review_prompt import build_review_packet, validate_evidence


def cases():
    script = '门前，小禾把唯一的钥匙交给阿林。阿林接住钥匙。'
    board = {'title': '钥匙交接', 'scenes': [{'key': 'scene-1', 'title': '门前', 'source_quote': script}],
        'shots': [{'key': 'shot-1', 'scene_key': 'scene-1', 'source_quote': script,
            'purpose': '交代钥匙由小禾转交阿林', 'action': '小禾递出钥匙，阿林伸手接住',
            'duration_ms': 6000, 'shot_size': '中景', 'camera_angle': '平视', 'camera_motion': '固定',
            'characters': ['小禾', '阿林'], 'state_start': '唯一钥匙在小禾手中',
            'state_end': '唯一钥匙在阿林手中，小禾手中无钥匙',
            'action_beats': [{'description': '小禾递出钥匙，阿林接住', 'duration_ms': 3000}],
            'frame_prompts': {'first': '小禾握着唯一钥匙，阿林空手', 'last': '阿林握着唯一钥匙，小禾空手'},
            'sound': '环境声，无对白', 'continuity_notes': '交接后钥匙留在阿林手中'}]}
    definitions = [
        ('slack', {}, '不应仅因3000毫秒动作少于6000毫秒镜头而报错或要求补齐。'),
        ('assumption', {'composition': '小禾画左、阿林画右',
            'creative_notes': '原稿未指定左右；采用小禾画左、阿林画右的构图假设，待预演确认。'},
            '不应仅因已披露的左右构图假设未见于原稿而重复报错。'),
        ('ownership', {'state_end': '唯一钥匙仍在小禾手中，阿林手中无钥匙'},
            '必须发现交接已完成但终态仍归小禾的矛盾，不能靠假想交还解释。'),
        ('first_frame', {'frame_prompts': {'first': '阿林已经握着唯一钥匙，小禾空手',
            'last': '阿林握着唯一钥匙，小禾空手'}},
            '必须发现首帧提前完成交接，与开始状态冲突。'),
    ]
    result = []
    for identity, changes, expectation in definitions:
        content = deepcopy(board)
        content['shots'][0].update(changes)
        content = StoryboardContent.model_validate(content).model_dump(mode='json')
        result.append({'id': identity, 'script': script, 'content': content, 'expectation': expectation})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    # Exclusive directory prevents overwriting earlier evidence or accidental resumption.
    args.output.mkdir(parents=True, exist_ok=False)

    def save(name, data):
        (args.output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    controls = cases()
    save('cases.json', controls)
    if not args.live:
        return
    load_dotenv(override=False)
    key = os.getenv('DEEPSEEK_API_KEY')
    if not key:
        raise SystemExit('Missing local model key; no requests made.')
    config = ModelConfig(name='审核控制组', purpose='review', adapter='openai_chat',
        base_url=os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'), model=args.model,
        api_key_env='DEEPSEEK_API_KEY', reasoning_protocol='deepseek', timeout_seconds=120,
        parameters={'reasoning_effort': 'low', 'max_tokens': 12000})
    # Verify account catalogue without writing credentials or raw responses.
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.get(config.base_url + '/models', headers={'Authorization': 'Bearer ' + key})
        if response.status_code != 200:
            raise SystemExit(f'Model catalogue unavailable: HTTP {response.status_code}')
        available = [item.get('id') for item in response.json().get('data', [])]
    if config.model not in available:
        raise SystemExit('Requested model absent from account catalogue; no Chat requests made.')
    summary = {'model': config.model, 'effort': 'low', 'max_tokens': 12000,
               'max_calls': 4, 'calls': [], 'semantic_judgment': 'pending'}
    save('summary.json', summary)
    for case in controls:
        packet = build_review_packet(case['script'], {}, '', case['content'])
        record = {'case': case['id'], 'status': 'started', 'manifest': packet['manifest']}
        summary['calls'].append(record)
        save('summary.json', summary)
        start = time.monotonic()
        stop = False
        try:
            output, usage = ChatPlanner().generate(config, packet['messages'])
            record['usage'] = usage
            save(case['id'] + '-response.json', output)
            report = ReviewReport.model_validate(output)
            validate_evidence(report, case['content'], case['script'])
            record.update(status='valid_report', issue_count=len(report.issues))
        except PlannerError as exc:
            record.update(status='failed', error_code=exc.code, usage=exc.usage)
            stop = exc.code in ('missing_key', 'provider_error', 'outcome_unknown')
        except (ValueError, TypeError, KeyError):
            record.update(status='failed', error_code='invalid_output')
        record['elapsed_seconds'] = round(time.monotonic() - start, 3)
        save('summary.json', summary)
        print(json.dumps({k: v for k, v in record.items() if k != 'manifest'}, ensure_ascii=False), flush=True)
        if stop:
            break


if __name__ == '__main__':
    main()
