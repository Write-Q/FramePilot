"""面向用户的交接文档；保持原稿、正文、引用和用户决策逐字不变。"""
import re

STATUSES = dict(awaiting_input='等待补充', awaiting_confirmation='等待确认', confirmed='已确认', limit_reached='已达修订上限', budget_exhausted='调用额度不足', failed='执行失败', running='执行中', no_progress='自动修订无进展', awaiting_direction='等待选择方向', ready_for_production='原稿待交接')
FACETS = dict(theme='主题与情绪', characters='人物', plot='剧情', props='道具', scenes='场景', actions='动作与表演', camera='镜头语言', visual_style='视觉风格', sound='声音', pacing='节奏与规格')
FIELDS = dict(FACETS, original_story='用户原稿', original='用户原稿', draft='当前剧本', constraints='创作要求', text='概括内容', evidence='引用依据', related_facets='关联卡片', needs_user='需要用户补充', suggestion='修改建议', description='问题说明')

def display_text(value):
    return re.sub(r'(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z_0-9]*(?![A-Za-z0-9_])', lambda m: FIELDS.get(m[0], m[0]), str(value or ''))

def export_story(state):
    review = '未经故事审核' if state['mode']=='direct' else f"审核版本：{state['reviewed_version']}；当前版本：{state['version']}；状态：{STATUSES.get(state['status'], '状态待确认')}"
    lines = ['# FramePilot 剧本交接', review, '## 当前剧本', state['draft'], '## 最初输入', state['original_story'], '## 用户要求', state['constraints'], '## 未解决问题']
    categories=dict(missing='信息待补充', continuity='连续性待核对', constraint='与创作要求不符', creative='创作建议')
    for index, issue in enumerate(state.get('issues', []), 1):
        lines += [f"### 问题 {index}：{categories.get(issue.get('category'), '待审阅')}", display_text(issue.get('description')), '修改建议：'+display_text(issue.get('suggestion'))]
        facets=[FACETS[key] for key in issue.get('related_facets', []) if key in FACETS]
        if facets: lines.append('关联卡片：'+'、'.join(facets))
        if issue.get('needs_user'): lines.append('需要用户补充或确认。')
        if issue.get('carried_forward'): lines.append(f"此项尚未处理，依据来自版本 {issue.get('version', '待确认')}。")
        for evidence in issue.get('evidence', []):
            source=dict(original='用户原稿',draft='当前剧本',constraints='创作要求',user='用户补充').get(evidence.get('source'),'参考材料')
            lines += ['引用依据（'+source+'）：', evidence.get('quote','')]
    if not state.get('issues'): lines.append('暂无已记录的待处理问题；不代表已完成审核或质量保证。')
    lines.append('## 决策记录')
    for entry in state.get('decision_history', []):
        action=dict(revise='修改',clarify='澄清',choose='选择方向',confirm='确认').get(entry.get('action'),'其他操作')
        lines += [f"### 版本 {entry.get('version', '待确认')} · {action}", entry.get('feedback','')]
        for item in entry.get('decisions', []):
            choice=item.get('choice')
            name=dict(adopt='采用建议',replace='替换建议',keep='保留设定').get(choice,'其他处理')
            instruction=item.get('instruction','')
            lines.append(name+'：'+(display_text(instruction) if choice=='adopt' else instruction))
    if not state.get('decision_history'): lines.append('暂无决策记录。')
    return '\n\n'.join(lines)+'\n'
