"""游戏规则和状态服务测试；模型替身不验证创作质量。"""
from copy import deepcopy
import pytest
from app.game.service import GameService, GameConflict
from app.game.store import MemoryStore


class Model:
    """固定失败判定和文字结果，验证程序掌握状态修改。"""
    def generate(self, task, payload, schema):
        if task == 'game_open':
            return {'text':'你站在雨夜车站。','scene':'车站','characters':['守夜人'], 'inventory':['车票'], 'choices':['询问守夜人','进入车站'], 'visual_change':True}, {}
        if task == 'game_assess':
            return {'attribute':'agility','difficulty':18,'damage':4,'check':True}, {}
        if task == 'game_background':
            return {'backgrounds':['雨夜车站','失忆城市','漂浮岛屿']}, {}
        return {'text':'你跌落台阶，失去了车票。','scene':'车站','characters':['守夜人'], 'inventory':[], 'choices':['求助','休息'], 'visual_change':False}, {}


def service():
    """每个测试拥有独立内存存档。"""
    return GameService(MemoryStore(), Model(), roller=lambda:1)


def test_fork_keeps_old_route_and_snapshots():
    game=service(); s=game.create('雨夜车站','adventure',False,False)
    origin=deepcopy(s['turns'][0])
    s=game.act(s['id'],s['active_branch'],'跳下台阶','one',s['revision'])
    assert s['turns'][-1]['state']['hp']==6
    s=game.fork(s['id'],origin['id'],s['revision'])
    assert s['turns'][0]==origin
    assert game.current(s)['state']['hp']==10
    assert len(s['branches'])==2


def test_hardcore_death_and_fork_rejected():
    game=service(); s=game.create('车站','hardcore',True,False)
    first=s['turns'][0]['id']
    for n in range(3):
        s=game.act(s['id'],s['active_branch'],'跳下','op'+str(n),s['revision'])
    assert game.current(s)['state']['hp']==0
    with pytest.raises(GameConflict): game.fork(s['id'],first,s['revision'])
    with pytest.raises(GameConflict): game.act(s['id'],s['active_branch'],'继续','dead',s['revision'])


def test_story_mode_survives_and_duplicate_is_idempotent():
    game=service(); s=game.create('车站','story',False,False)
    for n in range(3):
        s=game.act(s['id'],s['active_branch'],'跳下','op'+str(n),s['revision'])
    assert game.current(s)['state']['hp']==1
    before=s['calls']; count=len(s['turns'])
    s=game.act(s['id'],s['active_branch'],'跳下','op2',s['revision'])
    assert len(s['turns'])==count and s['calls']==before


def test_reference_selection_excludes_other_branch_future():
    game=service(); s=game.create('车站','adventure',True,False)
    first=s['turns'][0]['id']
    s=game.act(s['id'],s['active_branch'],'跳下','one',s['revision'])
    future=s['turns'][-1]['id']
    s['images']=[{'id':'past','turn_id':first,'status':'ready'}, {'id':'future','turn_id':future,'status':'ready'}]
    game.store.save(s,s['revision'])
    s=game.fork(s['id'],first,game.get(s['id'])['revision'])
    assert [i['id'] for i in game.references(s,first)]==['past']


def test_postgres_restart(database_url):
    from app.game.store import PostgresStore
    game=GameService(PostgresStore(database_url),Model())
    s=game.create('车站','adventure',True,False)
    another=GameService(PostgresStore(database_url),Model())
    assert another.get(s['id'])['background']=='车站'
    with pytest.raises(GameConflict): another.fork(s['id'],s['turns'][0]['id'],999)


def test_retry_keeps_die_after_narration_failure():
    class Flaky(Model):
        def __init__(self): self.failed=False
        def generate(self,task,payload,schema):
            if task=='game_turn' and not self.failed:
                self.failed=True; raise RuntimeError('offline')
            return super().generate(task,payload,schema)
    rolls=[]
    def roller(): rolls.append(1); return 1
    game=GameService(MemoryStore(),Flaky(),roller)
    s=game.create('车站','adventure',True,False)
    s=game.act(s['id'],s['active_branch'],'跳下','retry',s['revision'])
    assert s['pending']['result']['die']==1
    s=game.act(s['id'],s['active_branch'],'跳下','retry',s['revision'])
    assert len(rolls)==1 and game.current(s)['state']['hp']==6


def test_images_are_persisted_and_references_are_real_bytes(tmp_path):
    from app.game.images import GameImages
    class ImageModel:
        configured=True
        def __init__(self): self.requests=[]
        def generate(self,prompt,references):
            self.requests.append(references)
            return b'\x89PNG\r\n\x1a\nimage', 'image/png'
    game=service(); provider=ImageModel(); images=GameImages(game,provider,tmp_path)
    s=game.create('车站','adventure',True,False)
    turn=s['turns'][0]['id']
    job=images.reserve(s['id'],turn); images.run(s['id'],job)
    s=game.get(s['id']); assert s['images'][0]['status']=='ready'
    job=images.reserve(s['id'],turn); images.run(s['id'],job)
    assert provider.requests[-1][0]['data'].startswith(b'\x89PNG')
    assert game.get(s['id'])['image_calls']==2


def test_unconfigured_images_do_not_charge(tmp_path):
    from app.game.images import GameImages
    class Missing: configured=False
    game=service(); s=game.create('车站','story',False,True)
    images=GameImages(game,Missing(),tmp_path)
    with pytest.raises(GameConflict): images.reserve(s['id'],s['turns'][0]['id'])
    assert game.get(s['id'])['image_calls']==0


def test_http_game_routes_and_hidden_stats(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.game.api import install_game
    from app.game.images import GameImages
    class Missing: configured=False
    app=FastAPI();app.state.game=service();app.state.game_images=GameImages(app.state.game,Missing(),tmp_path)
    install_game(app)
    with TestClient(app) as client:
        s=client.post('/api/game/sessions',json={'background':'车站','death':'adventure','show_stats':False}).json()
        assert s['show_stats'] is False
        r=client.post(f"/api/game/sessions/{s['id']}/actions",json={'action':'跳下','operation_id':'one','branch':s['active_branch'],'revision':s['revision']})
        assert r.status_code==200
        s=r.json();assert s['turns'][-1]['state']['hp']==6
        assert client.post(f"/api/game/sessions/{s['id']}/images",json={'turn_id':s['turns'][0]['id']}).status_code==409
        assert '你跌落' in client.get(f"/api/game/sessions/{s['id']}/export").text
        assert client.get('/play').status_code==200


def test_cancel_does_not_allow_reroll_of_same_action():
    class Flaky(Model):
        def generate(self,task,payload,schema):
            if task=='game_turn':raise RuntimeError('offline')
            return super().generate(task,payload,schema)
    rolls=[]
    def roller():rolls.append(1);return 1
    game=GameService(MemoryStore(),Flaky(),roller);s=game.create('车站')
    s=game.act(s['id'],s['active_branch'],'跳下','one',s['revision'])
    s=game.settings(s['id'],s['revision'],cancel_pending=True)
    s=game.act(s['id'],s['active_branch'],'跳下','two',s['revision'])
    assert len(rolls)==1


def test_assessment_receives_latest_event():
    class Capture(Model):
        def generate(self,task,payload,schema):
            if task=='game_assess':assert '雨夜车站' in payload['current_scene']
            return super().generate(task,payload,schema)
    game=GameService(MemoryStore(),Capture(),lambda:1);s=game.create('车站')
    s=game.act(s['id'],s['active_branch'],'进入','one',s['revision'])
    assert not s['error']


def test_image_failure_can_retry_without_changing_turn(tmp_path):
    from app.game.images import GameImages
    class Broken:
        configured=True
        def generate(self,*args):raise RuntimeError('offline')
    game=service();s=game.create('车站');original=deepcopy(s['turns'])
    images=GameImages(game,Broken(),tmp_path);job=images.reserve(s['id'],s['turns'][0]['id'])
    images.run(s['id'],job);s=game.get(s['id'])
    assert s['images'][0]['status']=='failed' and s['turns']==original
    another=images.reserve(s['id'],s['turns'][0]['id'])
    assert another!=job
    images.recover();assert game.get(s['id'])['images'][-1]['status']=='failed'
