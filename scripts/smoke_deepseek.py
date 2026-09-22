"""真实调用测试：只使用固定虚构故事，不输出密钥。运行会产生 API 费用。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import CreateProject
from app.provider import DeepSeekProvider, ROOT
from app.service import StoryService

with StoryService(ROOT / 'data' / 'smoke', DeepSeekProvider(), max_calls=2) as service:
    project = service.create(CreateProject(
        story='雨停后，小禾走到自家院子，把一株倒伏的幼苗扶正，用木棍支撑好。她浇了少量水，看着叶子上的水珠，微笑着回屋。',
        constraints='温暖写实的十秒短片；只出现小禾一名角色，不需要新增冲突或反转。',
        mode='collaborative',
    ))
    summary = {k: project[k] for k in ['id', 'calls_used', 'calls']}
    summary.update(status=project['state']['status'], error=project['state'].get('error'),
                   facets=list(project['state']['card']), issues=project['state']['issues'])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if project['state']['status'] not in ('awaiting_input', 'awaiting_confirmation'):
        raise SystemExit(1)
