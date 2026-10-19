from copy import deepcopy

import pytest

from app.domain import Extraction, Review
from tests.test_story import card, issue


def material():
    return {'original_story': '小禾坐在院子里。她扶正幼苗。', 'constraints': '只有小禾；无对白。',
            'feedback_history': ['保留结尾。', '只修改动作。'], 'draft': '小禾扶正幼苗，露出微笑。'}


def test_catalog_preserves_exact_source_and_separate_materials():
    from app.evidence_refs import EvidenceContract
    payload = material()
    contract = EvidenceContract(Extraction.model_json_schema(), payload)
    assert contract.catalog
    assert len({item['id'] for item in contract.catalog}) == len(contract.catalog)
    for item in contract.catalog:
        origin = payload['feedback_history'][item['index']] if item['field'] == 'feedback_history' else payload[item['field']]
        assert origin[item['start']:item['end']] == item['text']
        assert 0 < len(item['text']) <= 1000
        assert item['source'] in ('original', 'user')


def test_card_reference_hydrates_without_mutating_output_or_schema():
    from app.evidence_refs import EvidenceContract
    schema = Extraction.model_json_schema(); original = deepcopy(schema)
    contract = EvidenceContract(schema, material())
    result = {'card': {k: dict(text=v['text'], source=v['source'], evidence_ref='') for k, v in card().items()}}
    selected = next(x for x in contract.catalog if x['source'] == 'user')
    result['card']['characters'] = dict(text='只有小禾', source='user', evidence_ref=selected['id'])
    snapshot = deepcopy(result)
    resolved = contract.resolve(result)
    assert resolved['card']['characters']['evidence'] == selected['text']
    assert result == snapshot and schema == original
    assert 'evidence_ref' in contract.schema['$defs']['Facet']['properties']
    assert 'evidence' not in contract.schema['$defs']['Facet']['properties']


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_source', 'free_quote', 'unknown_with_ref'])
def test_bad_references_are_rejected(fault):
    from app.evidence_refs import EvidenceContract
    from app.provider import StructuredOutputError
    contract = EvidenceContract(Extraction.model_json_schema(), material())
    ref = next(x for x in contract.catalog if x['source'] == 'original')['id']
    facet = dict(text='小禾', source='original', evidence_ref=ref)
    if fault == 'missing': facet.pop('evidence_ref')
    if fault == 'unknown': facet['evidence_ref'] = 'nonexistent'
    if fault == 'wrong_source': facet['source'] = 'user'
    if fault == 'free_quote': facet['evidence'] = '自由抄写的原文'
    if fault == 'unknown_with_ref': facet['source'] = 'unknown'
    with pytest.raises(StructuredOutputError):
        contract.resolve({'card': {'theme': facet}})


def test_review_references_hydrate_from_current_draft():
    from app.evidence_refs import EvidenceContract
    contract = EvidenceContract(Review.model_json_schema(), material())
    problem = issue(); selected = next(x for x in contract.catalog if x['source'] == 'draft')
    problem['evidence'] = [{'source': 'draft', 'evidence_ref': selected['id']}]
    resolved = contract.resolve({'issues': [problem]})
    assert resolved['issues'][0]['evidence'] == [{'source': 'draft', 'quote': selected['text']}]
    Review.model_validate(resolved)


def test_long_repeated_and_empty_materials():
    from app.evidence_refs import EvidenceContract
    payload = dict(original_story='甲'*2101+'。同句。同句。', constraints='', feedback_history=[], draft='')
    c = EvidenceContract(Extraction.model_json_schema(), payload)
    assert ''.join(x['text'] for x in c.catalog) == payload['original_story']
    assert len({x['id'] for x in c.catalog}) == len(c.catalog)
    assert all(len(x['text']) <= 1000 for x in c.catalog)
    empty = EvidenceContract(Extraction.model_json_schema(), dict(original_story='', constraints='', feedback_history=[]))
    assert empty.catalog == []


def test_many_short_sentences_do_not_explode_catalog_size():
    import json
    from app.evidence_refs import EvidenceContract
    payload = dict(original_story='甲。'*8000, draft='乙。'*10000, constraints='丙。'*1500, feedback_history=[])
    c = EvidenceContract(Review.model_json_schema(), payload)
    assert len(c.catalog) <= 200
    assert len(json.dumps(c.catalog, ensure_ascii=False)) < 150000
    for item in c.catalog:
        assert item['text'] == payload[item['field']][item['start']:item['end']]
