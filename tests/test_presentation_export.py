from app.presentation import export_story


def test_readable_export_preserves_user_content():
    original = 'original_story 和 draft 是道具上的字。'
    state = dict(mode='collaborative', status='confirmed', reviewed_version=2, version=2,
                 draft=original, original_story=original, constraints='保留 draft',
                 issues=[dict(category='continuity', description='draft 与 original_story 冲突',
                              suggestion='检查 draft', related_facets=['props'],
                              evidence=[dict(source='original', quote=original)], needs_user=True,
                              carried_forward=True, version=1)],
                 decision_history=[dict(version=2, action='revise', feedback='保留 original_story',
                                        decisions=[dict(choice='replace', instruction=original)])])
    result = export_story(state)
    assert '状态：已确认' in result
    assert '当前剧本 与 用户原稿 冲突' in result
    assert '关联卡片：道具' in result
    assert '依据来自版本 1' in result
    assert result.count(original) == 4
    assert '保留 original_story' in result
    assert '"issues"' not in result
    assert 'confirmed' not in result


def test_direct_and_unknown_values():
    state = dict(mode='direct', draft='原稿', original_story='原稿', constraints='', issues=[], decision_history=[])
    assert '未经故事审核' in export_story(state)
    state.update(mode='free', status='future_status', reviewed_version=0, version=1,
                 decision_history=[dict(version=1,action='future',decisions=[dict(choice='future',instruction='原文')])])
    result=export_story(state)
    assert '状态待确认' in result and '其他处理：原文' in result
    assert 'future' not in result
