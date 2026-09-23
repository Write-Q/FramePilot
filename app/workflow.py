"""LangGraph 只负责流程；权限、额度和证据验证由确定性代码约束。"""
import hashlib
import json

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from pydantic import ValidationError

from app.domain import StoryState, Extraction, Revision, Review, StoryPlan, Brainstorm
from app.provider import ProviderError


# 组装状态图；内部节点闭包共用模型适配器、业务仓库和检查点存储。
def build_graph(provider, repo, checkpointer):
    # 节点调用模型的统一入口：先占调用额度，再校验结构并记录请求结果。
    def ask(state, task, schema, validation_feedback=None):
        call_id = repo.reserve_call(state['project_id'], task)
        payload = {key: state.get(key) for key in (
            'revision_instructions', 'outline', 'original_story', 'draft', 'mode', 'constraints', 'card', 'issues', 'feedback_history')}
        if validation_feedback:
            payload['validation_feedback'] = validation_feedback
        try:
            raw, usage = provider.generate(task, payload, schema.model_json_schema())
            parsed = schema.model_validate(raw)
        except ValidationError:
            repo.finish_call(call_id, 'invalid_output')
            raise ProviderError('模型输出未通过数据约定检查，未采用该结果。') from None
        except Exception:
            repo.finish_call(call_id, 'failed')
            raise
        repo.finish_call(call_id, 'succeeded', usage)
        return parsed.model_dump()

    # 校验标为原稿/用户来源的引用，不能证明概括的语义判断一定正确。
    def check_card(state, card):
        user_text = state['constraints'] + '\n' + '\n'.join(state['feedback_history'])
        for name, facet in card.items():
            source, quote = facet['source'], facet['evidence']
            if source in ('original', 'user'):
                haystack = state['original_story'] if source == 'original' else user_text
                if not quote or quote not in haystack:
                    raise ProviderError(f'理解卡片的 {name} 来源引用不是对应材料中的连续原文。请逐字引用，不拼接、不省略、不改写 evidence；text 仍应概括总结。')

    # 自由模式：先构思故事骨架。
    def plan(state):
        return ask(state, 'plan', StoryPlan)

    # 协作模式：生成候选方向，并由程序分配方向编号。
    def brainstorm(state):
        result = ask(state, 'brainstorm', Brainstorm)
        return {'directions': [dict(option, id=f"direction_{index}") for index, option in enumerate(result['directions'])],
                'status': 'awaiting_direction', 'stop_reason': '请选择或调整一个故事方向，再开始编写。'}

    # 人工选择方向的暂停点；恢复后记录授权并推进正文版本。
    def direction_choice(state):
        answer = interrupt({'version': state['version'], 'status': state['status'],
                            'directions': state['directions'], 'actions': ['choose']})
        selected = next(option for option in state['directions'] if option['id'] == answer['direction_id'])
        feedback = '采用故事方向：' + selected['outline'] + '\n补充要求：' + answer['feedback']
        return {'outline': selected['outline'], 'version': state['version'] + 1,
                'feedback_history': [*state['feedback_history'], feedback],
                'decision_history': [*state.get('decision_history', []), {'version': state['version'], 'action': 'choose', 'direction': selected, 'feedback': answer['feedback']}],
                'status': 'running'}

    # 按故事骨架首次写出正文及卡片；与后续 revise 修订分开计数。
    def compose(state):
        result = ask(state, 'compose', Revision)
        check_card(state, result['card'])
        repo.version({**state, **result})
        return result

    # 理解已有输入并生成卡片；来源引用不合格时最多纠正一次。
    def extract(state):
        result = ask(state, 'extract', Extraction)
        try:
            check_card(state, result['card'])
        except ProviderError as exc:
            # 仅纠正一次引用格式，仍经持久化额度闸门计费；再次错误直接停止。
            result = ask(state, 'extract', Extraction, validation_feedback=str(exc))
            check_card(state, result['card'])
        repo.version({**state, **result})
        return result

    # 审核当前稿、验证引用、补充问题编号并保留未处理旧问题。
    def review(state):
        result = ask(state, 'review', Review)
        sources = {'original': state['original_story'], 'draft': state['draft'],
                   'constraints': state['constraints'], 'feedback': '\n'.join(state['feedback_history'])}
        issues = []
        for item in result['issues']:
            for evidence in item['evidence']:
                if evidence['quote'] not in sources[evidence['source']]:
                    raise ProviderError('审核引用了不存在的原文，未将本次审核视为通过。')
            # 同类型、同一组证据维持相同编号。换说法的语义匹配暂不宣称已解决。
            signature = json.dumps([item['category'], sorted((e['source'], e['quote']) for e in item['evidence'])], ensure_ascii=False)
            item['id'] = 'issue_' + hashlib.sha256(signature.encode()).hexdigest()[:16]
            item['version'] = state['version']
            if item['category'] == 'constraint' and state['mode'] != 'free':
                item['needs_user'] = True
            if not any(x['id'] == item['id'] for x in issues):
                issues.append(item)
        for pending in state.get('protected_issues', []):
            if not any(i['id'] == pending['id'] for i in issues):
                issues.append({**pending, 'carried_forward': True})
        previous = {i['id'] for i in state.get('issues', [])}
        current = {i['id'] for i in issues}
        # 保守检测：只认同类型且逐字证据相同的问题，不宣称语义相似度评估。
        stagnant = state.get('stagnant_rounds', 0) + 1 if current and previous and previous <= current else 0
        return {'stagnant_rounds': stagnant, 'issues': issues, 'reviewed_version': state['version'],
                'review_history': [*state['review_history'], {'version': state['version'], 'issues': issues}]}

    # 确定性路由：判断人工介入、无进展、修订上限和调用预算。
    def decide(state):
        issues = state['issues']
        if not issues:
            status, reason, next_step = 'awaiting_confirmation', '未发现待处理问题，请用户审阅。', 'human'
        elif state['mode'] != 'free' or state.get('clarification_only') or any(i['needs_user'] for i in issues):
            status, reason, next_step = 'awaiting_input', '存在需要用户补充或选择的内容。', 'human'
        elif state.get('stagnant_rounds', 0) >= 2:
            status, reason, next_step = 'no_progress', '连续两轮未消除已有的同证据问题，已停止自动修订。请补充新的修改方向。', 'human'
        elif state['revision_count'] >= 3:
            status, reason, next_step = 'limit_reached', '累计已修订 3 轮，保留未解决问题。', 'human'
        elif repo.get(state['project_id'])['calls_used'] + 2 > repo.get(state['project_id'])['max_calls']:
            status, reason, next_step = 'budget_exhausted', '剩余额度不足以完成修订及审核，已暂停。', 'human'
        else:
            status, reason, next_step = 'running', '', 'revise'
        return {'status': status, 'stop_reason': reason, 'next_step': next_step}

    # 按审核及用户授权改稿，保存新版本，再回到审核。
    def revise(state):
        # 再次保护边界，避免未来改图时绕过路由上限。
        if state['revision_count'] >= 3:
            raise ProviderError('已达到累计修订上限。')
        result = ask(state, 'revise', Revision)
        check_card(state, result['card'])
        updates = {**result, 'version': state['version'] + 1,
                   'revision_count': state['revision_count'] + 1, 'status': 'running',
                   'accepted_issue_ids': [], 'stop_reason': ''}
        repo.version({**state, **updates})
        return updates

    # 人工暂停点；confirm 结束，clarify 仅复审，revise 修改后复审。
    def human(state):
        # interrupt 前不执行模型请求或数据写入，恢复时节点会从头运行。
        answer = interrupt({'version': state['version'], 'status': state['status'],
                            'reason': state['stop_reason'], 'issues': state['issues'],
                            'actions': ['confirm', 'revise', 'clarify']})
        if answer['action'] == 'confirm':
            return {'status': 'confirmed', 'next_step': 'end', 'stop_reason': '当前版本已由用户确认。',
                    'accepted_issue_ids': answer['accepted_issue_ids']}
        return {'feedback_history': [*state['feedback_history'], answer['feedback']],
                'revision_instructions': answer.get('revision_instructions', []),
                'protected_issues': answer.get('protected_issues', []),
                'decision_history': [*state.get('decision_history', []), {'version': state['version'], 'action': answer['action'], 'feedback': answer['feedback'], 'decisions': answer.get('revision_instructions', [])}],
                'clarification_only': answer['action'] == 'clarify',
                'status': 'running', 'stagnant_rounds': 0,
                'next_step': 'review' if answer['action'] == 'clarify' else 'revise'}

    graph = StateGraph(StoryState)
    for name, function in [('brainstorm', brainstorm), ('direction_choice', direction_choice), ('plan', plan), ('compose', compose), ('extract', extract), ('review', review), ('decide', decide),
                           ('revise', revise), ('human', human)]:
        graph.add_node(name, function)
    graph.add_conditional_edges(START, lambda s: 'plan' if s['mode'] == 'free' else 'extract', {'plan':'plan', 'extract':'extract'})
    graph.add_edge('plan', 'compose')
    graph.add_edge('compose', 'review')
    graph.add_conditional_edges('extract', lambda s: 'brainstorm' if s['mode'] == 'collaborative' and s.get('input_kind') in ('idea','fragment') else 'review', {'brainstorm':'brainstorm','review':'review'})
    graph.add_edge('brainstorm','direction_choice')
    graph.add_edge('direction_choice','compose')
    graph.add_edge('review', 'decide')
    graph.add_conditional_edges('decide', lambda s: s['next_step'], {'human': 'human', 'revise': 'revise'})
    graph.add_edge('revise', 'review')
    graph.add_conditional_edges('human', lambda s: s['next_step'], {'end': END, 'revise': 'revise', 'review': 'review'})
    return graph.compile(checkpointer=checkpointer)

