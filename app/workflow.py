"""LangGraph 只负责流程；权限、额度和证据验证由确定性代码约束。"""
import hashlib
import json

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from pydantic import ValidationError

from app.domain import StoryState, Extraction, Revision, Review, StoryPlan, Brainstorm, DraftBody
from app.provider import ProviderError, StructuredOutputError
from app.evidence_refs import EvidenceContract
from app.revision_context import revision_context


class QuoteValidationError(ProviderError):
    """自由引用Provider的兼容校验，来源编号协议仍需经此检查。"""


# 组装状态图；内部节点闭包共用模型适配器、业务仓库和检查点存储。
def build_graph(provider, repo, checkpointer):
    # 节点调用模型的统一入口：先占调用额度，再校验结构并记录请求结果。
    def ask_once(state, task, schema, validation_feedback=None, validate=None):
        call_id = repo.reserve_call(state['project_id'], task)
        payload = {key: state.get(key) for key in (
            'revision_instructions', 'outline', 'original_story', 'draft', 'mode', 'constraints', 'card', 'issues', 'feedback_history')}
        if validation_feedback:
            payload['validation_feedback'] = validation_feedback
        if task == 'review' and 'previous_draft' in state:
            payload['revision_context'] = revision_context(state['previous_draft'], state['draft'])
        usage = {}
        raw = None
        try:
            contract = EvidenceContract(schema.model_json_schema(), payload) if getattr(provider, 'evidence_references', False) else None
            if contract and contract.enabled:
                payload['evidence_catalog'] = contract.catalog
            raw, usage = provider.generate(task, payload, contract.schema if contract else schema.model_json_schema())
            if contract and contract.enabled:
                canonical = contract.resolve(raw)
            else:
                canonical = raw
            parsed = schema.model_validate(canonical)
            result = parsed.model_dump()
            if validate:
                validate(result)
        except QuoteValidationError:
            repo.finish_call(call_id, 'invalid_evidence', usage)
            raise
        except StructuredOutputError as exc:
            if usage:
                exc.usage = usage
            repo.finish_call(call_id, 'invalid_output', exc.usage)
            raise
        except ValidationError as exc:
            repo.finish_call(call_id, 'invalid_output', usage)
            errors = exc.errors(include_input=False, include_context=False, include_url=False)
            details = '; '.join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in errors)
            raise StructuredOutputError('模型输出未通过数据约定检查，未采用该结果。请纠正字段后输出完整结果：'+details,
                                        output=raw, usage=usage,
                                        card_only=bool(errors) and all(e['loc'] and e['loc'][0] == 'card' for e in errors)) from None
        except Exception:
            repo.finish_call(call_id, 'failed')
            raise
        repo.finish_call(call_id, 'succeeded', usage)
        return result

    def ask(state, task, schema, validation_feedback=None, validate=None, repair_structure=True):
        try:
            return ask_once(state, task, schema, validation_feedback, validate)
        except StructuredOutputError as exc:
            # 已在纠正调用中或候选正文需要单独保护时，不再嵌套重试。
            if not repair_structure or validation_feedback is not None:
                raise
            try:
                return ask_once(state, task, schema, str(exc), validate)
            except ProviderError as corrected_error:
                corrected_error.correction_used = True
                raise

    def preserved_body(raw):
        if not isinstance(raw, dict) or not set(raw) <= {'draft', 'card', 'input_kind'}:
            return None
        try:
            body = DraftBody.model_validate({'draft': raw.get('draft')})
        except ValidationError:
            return None
        kind = raw.get('input_kind', 'complete')
        if kind not in ('idea', 'fragment', 'complete'):
            return None
        return {'draft': body.draft, 'input_kind': kind, 'card': raw.get('card', {})}

    def pending_result(task, candidate, error='', exhausted=False):
        return {'pending_generation': {'task': task, 'result': candidate,
                                       'validation_feedback': error, 'retry_required': exhausted}}

    # 校验标为原稿/用户来源的引用，不能证明概括的语义判断一定正确。
    def check_card(state, card):
        user_text = state['constraints'] + '\n' + '\n'.join(state['feedback_history'])
        for name, facet in card.items():
            source, quote = facet['source'], facet['evidence']
            if source in ('original', 'user'):
                haystack = state['original_story'] if source == 'original' else user_text
                if not quote or quote not in haystack:
                    raise QuoteValidationError(f'理解卡片的 {name} 来源引用不是对应材料中的连续原文：{quote!r}。请逐字引用，不拼接、不省略、不改写 evidence；text 仍应概括总结。')

    def generate_candidate(state, task):
        # 生成与纠正分属检查点节点；手动重试纠正也不重新生成正文。
        candidate = {}
        def validate(result):
            candidate.update(result)
            check_card(state, result['card'])
        try:
            result = ask(state, task, Revision, validate=validate, repair_structure=False)
        except QuoteValidationError as exc:
            return pending_result(task, candidate, str(exc))
        except StructuredOutputError as exc:
            saved = preserved_body(exc.output) if exc.card_only else None
            if saved is not None:
                return pending_result(task, saved, str(exc))
            try:
                result = ask_once(state, task, Revision, str(exc), validate)
            except QuoteValidationError as corrected_error:
                return pending_result(task, candidate, str(corrected_error), exhausted=True)
            except StructuredOutputError as corrected_error:
                saved = preserved_body(corrected_error.output) if corrected_error.card_only else None
                if saved is not None:
                    return pending_result(task, saved, str(corrected_error), exhausted=True)
                raise
        return pending_result(task, result)

    def accept_candidate(state, task):
        candidate = state['pending_generation']
        if not candidate or candidate['task'] != task:
            raise ProviderError('候选正文检查点不匹配，请重新载入项目。')
        if candidate.get('retry_required'):
            raise ProviderError('本轮自动纠正后卡片仍不合格，已保留候选正文；可手动重试卡片纠正。')
        result = candidate['result']
        if candidate['validation_feedback']:
            corrected = ask({**state, **result}, 'repair_card', Extraction,
                            validation_feedback=candidate['validation_feedback'],
                            validate=lambda r: check_card(state, r['card']))
            result = {**result, 'card': corrected['card']}
        return result

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
        return generate_candidate(state, 'compose')

    def accept_compose(state):
        result = accept_candidate(state, 'compose')
        repo.version({**state, **result})
        return {**result, 'pending_generation': None}

    # 理解已有输入并生成卡片；来源引用不合格时最多纠正一次。
    def extract(state):
        try:
            result = ask(state, 'extract', Extraction, validate=lambda r: check_card(state, r['card']))
        except QuoteValidationError as exc:
            if exc.correction_used:
                raise
            # 仅纠正一次引用格式，仍经持久化额度闸门计费；再次错误直接停止。
            result = ask(state, 'extract', Extraction, validation_feedback=str(exc),
                         validate=lambda r: check_card(state, r['card']))
        repo.version({**state, **result})
        return result

    # 审核当前稿、验证引用、补充问题编号并保留未处理旧问题。
    def review(state):
        sources = {'original': state['original_story'], 'draft': state['draft'],
                   'constraints': state['constraints'], 'feedback': '\n'.join(state['feedback_history'])}
        def validate(result):
            for item in result['issues']:
                for evidence in item['evidence']:
                    if evidence['quote'] not in sources[evidence['source']]:
                        raise QuoteValidationError(f"审核引用了不存在的原文（{evidence['source']}）：{evidence['quote']!r}。未将本次审核视为通过。请核对对应材料并重新输出完整审核结果，不要仅为通过校验而删除真实问题。")
        try:
            result = ask(state, 'review', Review, validate=validate)
        except QuoteValidationError as exc:
            if exc.correction_used:
                raise
            result = ask(state, 'review', Review, validation_feedback=str(exc), validate=validate)
        issues = []
        for item in result['issues']:
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
        return generate_candidate(state, 'revise')

    def accept_revision(state):
        result = accept_candidate(state, 'revise')
        updates = {**result, 'version': state['version'] + 1,
                   'previous_draft': state['draft'],
                   'pending_generation': None,
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
    for name, function in [('brainstorm', brainstorm), ('direction_choice', direction_choice), ('plan', plan), ('compose', compose), ('accept_compose', accept_compose), ('extract', extract), ('review', review), ('decide', decide),
                           ('revise', revise), ('accept_revision', accept_revision), ('human', human)]:
        graph.add_node(name, function)
    graph.add_conditional_edges(START, lambda s: 'plan' if s['mode'] == 'free' else 'extract', {'plan':'plan', 'extract':'extract'})
    graph.add_edge('plan', 'compose')
    graph.add_edge('compose', 'accept_compose')
    graph.add_edge('accept_compose', 'review')
    graph.add_conditional_edges('extract', lambda s: 'brainstorm' if s['mode'] == 'collaborative' and s.get('input_kind') in ('idea','fragment') else 'review', {'brainstorm':'brainstorm','review':'review'})
    graph.add_edge('brainstorm','direction_choice')
    graph.add_edge('direction_choice','compose')
    graph.add_edge('review', 'decide')
    graph.add_conditional_edges('decide', lambda s: s['next_step'], {'human': 'human', 'revise': 'revise'})
    graph.add_edge('revise', 'accept_revision')
    graph.add_edge('accept_revision', 'review')
    graph.add_conditional_edges('human', lambda s: s['next_step'], {'end': END, 'revise': 'revise', 'review': 'review'})
    return graph.compile(checkpointer=checkpointer)

