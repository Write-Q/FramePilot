"""模型仅选择当前材料的片段编号；页面和持久化仍使用原文引用。"""
from copy import deepcopy
import re

from app.provider import StructuredOutputError


class EvidenceContract:
    def __init__(self, schema, payload):
        self.schema = deepcopy(schema)
        definitions = self.schema.get('$defs', {})
        self.card = 'Facet' in definitions
        self.review = 'Evidence' in definitions
        self.enabled = self.card or self.review
        self.catalog = []
        if not self.enabled:
            return
        self._add('original', 'original_story', payload.get('original_story') or '')
        if self.card:
            self._add('user', 'constraints', payload.get('constraints') or '')
        else:
            self._add('constraints', 'constraints', payload.get('constraints') or '')
            self._add('draft', 'draft', payload.get('draft') or '')
        for index, text in enumerate(payload.get('feedback_history') or []):
            self._add('user' if self.card else 'feedback', 'feedback_history', text, index)
        self.lookup = {item['id']: item for item in self.catalog}
        for name, old in [('Facet', 'evidence'), ('Evidence', 'quote')]:
            if name not in definitions:
                continue
            definition = definitions[name]
            refs = [item['id'] for item in self.catalog]
            if name == 'Facet':
                refs = ['', *refs]
            field = {'type': 'string', 'description': '选择当前evidence_catalog的id，不抄写原文。AI建议/未知的卡片填空字符串。'}
            if refs:
                field['enum'] = refs
            definition['properties'].pop(old)
            definition['properties']['evidence_ref'] = field
            definition['required'] = [x for x in definition.get('required', []) if x != old] + ['evidence_ref']

    def _add(self, source, field, text, index=None):
        # 保留偏移及标点；不跨独立材料拼接。硬切分仅约束最长片段。
        spans = [(m.start(), m.end()) for m in re.finditer(r'.*?(?:[。！？；\n]+|$)', text, re.S) if m.end() > m.start()]
        if len(spans) > 64:
            # 大量短句合并为相邻连续片段，避免目录元数据和Schema枚举膨胀。
            grouped = []
            for start, end in spans:
                if grouped and end - grouped[-1][0] <= 500:
                    grouped[-1] = (grouped[-1][0], end)
                else:
                    grouped.append((start, end))
            spans = grouped
        for begin, limit in spans:
            for start in range(begin, limit, 1000):
                end = min(start + 1000, limit)
                fragment = text[start:end]
                if fragment.strip():
                    self.catalog.append({'id': f'e{len(self.catalog)+1}', 'source': source,
                                         'field': field, 'index': index, 'start': start,
                                         'end': end, 'text': fragment})

    def resolve(self, raw):
        result = deepcopy(raw)
        if not isinstance(result, dict):
            raise StructuredOutputError('输出必须是JSON对象。', output=raw)
        if self.card and isinstance(result.get('card'), dict):
            for name, facet in result['card'].items():
                if isinstance(facet, dict):
                    self._resolve_item(facet, 'evidence', f'card.{name}', raw, card_only=True)
        if self.review and isinstance(result.get('issues'), list):
            for index, issue in enumerate(result['issues']):
                if isinstance(issue, dict) and isinstance(issue.get('evidence'), list):
                    for evidence in issue['evidence']:
                        if isinstance(evidence, dict):
                            self._resolve_item(evidence, 'quote', f'issues.{index}.evidence', raw)
        return result

    def _resolve_item(self, item, target, path, raw, card_only=False):
        def reject(message):
            raise StructuredOutputError(f'{path}: {message}', output=raw, card_only=card_only)
        if target in item:
            reject(f'不能输出自由引用字段{target}，请仅输出evidence_ref编号。')
        ref = item.get('evidence_ref')
        if not isinstance(ref, str):
            reject('缺少字符串evidence_ref。')
        source = item.get('source')
        if card_only and source in ('ai_suggestion', 'unknown'):
            if ref:
                reject('AI建议或未知项的evidence_ref必须为空，不能冒用事实引用。')
            text = ''
        else:
            selected = self.lookup.get(ref)
            if not selected or selected['source'] != source:
                reject('evidence_ref不存在或与source不匹配；请从当前目录选择对应来源的编号。')
            text = selected['text']
        item.pop('evidence_ref')
        item[target] = text
