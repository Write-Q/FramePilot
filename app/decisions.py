"""把用户逐条选择转换为明确授权；AI 原建议只从服务端记录读取。"""

def resolve_decisions(state, decisions):
    known = {item['id']: item for item in state['issues']}
    resolved = []
    seen = set()
    for decision in decisions:
        if decision.issue_id not in known or decision.issue_id in seen:
            raise ValueError('建议编号不存在或重复，请刷新后重新选择。')
        seen.add(decision.issue_id)
        item = known[decision.issue_id]
        resolved.append({'issue_id': decision.issue_id, 'choice': decision.choice,
                         'instruction': item['suggestion'] if decision.choice == 'adopt' else decision.text,
                         'original_suggestion': item['suggestion'],
                         'related_facets': item.get('related_facets', [])})
    return resolved
