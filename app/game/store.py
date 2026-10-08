"""版本化游戏存档；事务只用于持久化，不跨越模型请求。"""
from copy import deepcopy
from sqlalchemy import create_engine, text
import json


class StoreConflict(Exception):
    """另一操作已经更新该存档。"""


class MemoryStore:
    """测试替身，模拟乐观版本检查。"""
    def __init__(self):
        self.items={}

    def get(self, identifier):
        return deepcopy(self.items[identifier])

    def save(self, state, expected):
        if expected is None:
            if state['id'] in self.items: raise StoreConflict()
        elif self.items[state['id']]['revision']!=expected:
            raise StoreConflict()
        state['revision']=(expected or 0)+1
        self.items[state['id']]=deepcopy(state)
        return state

    def list(self):
        return sorted([deepcopy(x) for x in self.items.values()],key=lambda x:x['created_at'],reverse=True)

    def close(self):
        pass


class PostgresStore:
    """单局JSONB快照包含回合历史和媒体清单，采用CAS保护并发。"""
    def __init__(self, url):
        self.engine=create_engine(url)

    def get(self, identifier):
        with self.engine.connect() as conn:
            row=conn.execute(text('SELECT snapshot FROM fp_game_sessions WHERE id=:id'),{'id':identifier}).first()
        if not row: raise KeyError(identifier)
        return row[0]

    def save(self, state, expected):
        next_revision=(expected or 0)+1
        data=deepcopy(state); data['revision']=next_revision
        values={'id':state['id'],'revision':next_revision,'expected':expected,'snapshot':json.dumps(data,ensure_ascii=False)}
        with self.engine.begin() as conn:
            if expected is None:
                result=conn.execute(text('INSERT INTO fp_game_sessions(id,revision,snapshot) VALUES (:id,:revision,CAST(:snapshot AS jsonb)) ON CONFLICT DO NOTHING'),values)
            else:
                result=conn.execute(text('UPDATE fp_game_sessions SET revision=:revision,snapshot=CAST(:snapshot AS jsonb) WHERE id=:id AND revision=:expected'),values)
            if result.rowcount!=1: raise StoreConflict()
        state['revision']=next_revision
        return state

    def list(self):
        with self.engine.connect() as conn:
            return list(conn.execute(text('SELECT snapshot FROM fp_game_sessions ORDER BY created_at DESC')).scalars())

    def close(self):
        self.engine.dispose()
