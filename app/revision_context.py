"""字符差异是程序事实，不解释用户授权或代替剧情审核。"""
from difflib import SequenceMatcher


def revision_context(previous, current):
    changes = []
    for operation, i, j, a, b in SequenceMatcher(None, previous, current, autojunk=False).get_opcodes():
        if operation != 'equal':
            changes.append({'operation': operation, 'before_start': i, 'before_end': j,
                            'after_start': a, 'after_end': b,
                            'before': previous[i:j], 'after': current[a:b]})
    return {'previous_draft': previous, 'changes': changes}
