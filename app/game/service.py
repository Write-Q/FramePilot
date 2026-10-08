"""游戏状态机：程序判定、不可变回合、分支和持久化失败恢复。"""
from copy import deepcopy
from datetime import datetime, timezone
from secrets import randbelow
from threading import RLock
from uuid import uuid4
from app.game.text import Frame, Assessment, Backgrounds
from app.game.store import StoreConflict


class GameConflict(ValueError):
    """用户需刷新或修改操作的游戏冲突。"""


class GameService:
    """单进程本地服务；持久化预占请求，重试保留骰子结果。"""
    def __init__(self, store, model, roller=None):
        self.store=store; self.model=model; self.roller=roller or (lambda:randbelow(20)+1)
        self.lock=RLock(); self.operation_locks={}

    def operation_lock(self,identifier):
        """仅串行化同一存档，避免一个故事等待模型时阻塞其他故事。"""
        with self.lock:
            return self.operation_locks.setdefault(identifier,RLock())

    def get(self, identifier):
        return self.store.get(identifier)

    def save(self, s):
        try: return self.store.save(s,s['revision'])
        except StoreConflict: raise GameConflict('存档已改变，请刷新后重试。') from None

    def current(self,s,branch=None):
        head=s['branches'][branch or s['active_branch']]['head']
        return next(t for t in s['turns'] if t['id']==head)

    def lineage(self,s,turn_id):
        """沿父指针追溯，禁止检索到其他分支未来。"""
        turns={t['id']:t for t in s['turns']}; route=[]
        while turn_id:
            turn=turns[turn_id]; route.append(turn); turn_id=turn['parent']
        return list(reversed(route))

    def references(self,s,turn_id):
        route={t['id'] for t in self.lineage(s,turn_id)}
        images=[i for i in s['images'] if i['status']=='ready' and i['turn_id'] in route]
        # 始终保留初始形象，再补最近两张；不能只链式引用上一张。
        return images[:1]+images[-2:] if len(images)>3 else images

    def call(self,s,task,payload,schema):
        if s['calls']>=100: raise GameConflict('本局已达到100次文字调用上限，请导出或新开一局。')
        s['calls']+=1; self.save(s)
        output,usage=self.model.generate(task,payload,schema.model_json_schema())
        s['usage'].append({'task':task,'usage':usage})
        return schema.model_validate(output)

    def backgrounds(self,requirements,feedback):
        output,_=self.model.generate('game_background',{'requirements':requirements,'feedback':feedback},Backgrounds.model_json_schema())
        return Backgrounds.model_validate(output).model_dump()

    def create(self,background,death='adventure',show_stats=True,auto_images=True):
        if death not in ('story','adventure','hardcore'): raise GameConflict('未知死亡规则')
        identifier=uuid4().hex; branch=uuid4().hex
        s={'schema_version':1,'id':identifier,'revision':0,'created_at':datetime.now(timezone.utc).isoformat(),
           'background':background,'death':death,'show_stats':show_stats,'auto_images':auto_images,
           'calls':0,'usage':[],'image_calls':0,'turns':[],'branches':{branch:{'name':'原路线','head':None}},
           'active_branch':branch,'pending':{'kind':'open'},'images':[],'error':None,'checks':{}}
        self.store.save(s,None)
        return self.resume_open(identifier)

    def resume_open(self,identifier):
        """开局失败保留编号，显式重试而不是丢弃已计费存档。"""
        with self.operation_lock(identifier):
            s=self.get(identifier)
            if s['turns']: return s
            try:
                f=self.call(s,'game_open',{'background':s['background']},Frame)
                state={'hp':10,'attributes':dict(strength=3,agility=3,insight=3,social=3),**f.model_dump(exclude={'text','choices','visual_change'})}
                f.visual_change=True
                self.append(s,None,'开始',f,state,None); s['pending']=None;s['error']=None
            except Exception as exc:
                s['error']='开局未完成，可使用当前存档重试。'; self.save(s)
                return s
            return self.save(s)

    def append(self,s,parent,action,f,state,result):
        """追加回合快照；旧回合不修改。"""
        t={'id':uuid4().hex,'parent':parent,'action':action,'text':f.text,'choices':f.choices,
           'state':deepcopy(state),'result':result,'visual_change':f.visual_change}
        s['turns'].append(t);s['branches'][s['active_branch']]['head']=t['id']

    def act(self,identifier,branch,action,op_id,revision):
        with self.operation_lock(identifier):
            s=self.get(identifier)
            existing=next((t for t in s['turns'] if t.get('operation_id')==op_id),None)
            if existing:
                if existing['action']!=action: raise GameConflict('请求编号已用于其他行动。')
                return s
            if s['revision']!=revision: raise GameConflict('存档已改变，请刷新。')
            if branch!=s['active_branch']: raise GameConflict('请先切换到该路线。')
            t=self.current(s)
            if t['state']['hp']==0: raise GameConflict('此路线已结束，请回溯或新开一局。')
            pending=s['pending']
            if pending and (pending.get('operation_id')!=op_id or pending.get('action')!=action):
                raise GameConflict('尚有失败行动待重试，请先重试或取消。')
            if not pending:
                pending={'kind':'action','operation_id':op_id,'action':action,'result':s.get('checks',{}).get(t['id']+'\n'+action)};s['pending']=pending
                self.save(s)
            try:
                if pending['result'] is None:
                    a=self.call(s,'game_assess',{'background':s['background'],'state':t['state'],'current_scene':t['text'],
                        'history':[{'action':x['action'],'text':x['text']} for x in self.lineage(s,t['id'])[-3:]],'action':action},Assessment)
                    die=self.roller() if a.check else None
                    success=not a.check or die+t['state']['attributes'][a.attribute]>=a.difficulty
                    pending['result']={'die':die,'attribute':a.attribute,'difficulty':a.difficulty,
                                       'success':success,'damage':a.damage if a.check and not success else 0}
                    s.setdefault('checks',{})[t['id']+'\n'+action]=deepcopy(pending['result'])
                    self.save(s)
                result=pending['result']; state=deepcopy(t['state'])
                state['hp']=max(1 if s['death']=='story' else 0,state['hp']-result['damage'])
                f=self.call(s,'game_turn',{'background':s['background'],'state':state,'action':action,'result':result,
                    'history':[{'action':x['action'],'text':x['text']} for x in self.lineage(s,t['id'])[-8:]]},Frame)
                f.visual_change=f.visual_change or f.scene!=t['state']['scene'] or bool(set(f.characters)-set(t['state']['characters']))
                state.update(f.model_dump(exclude={'text','choices','visual_change'},exclude_unset=True))
                self.append(s,t['id'],action,f,state,result);s['turns'][-1]['operation_id']=op_id
                s['pending']=None;s['error']=None
            except Exception:
                s['error']='行动未完成，已保存判定。重试不会重新掷骰；失败请求仍计入额度。'
            return self.save(s)

    def fork(self,identifier,turn_id,revision):
        with self.operation_lock(identifier):
            s=self.get(identifier)
            if s['revision']!=revision: raise GameConflict('存档已改变，请刷新。')
            if s['death']=='hardcore': raise GameConflict('硬核模式禁用回溯。')
            if s['pending']: raise GameConflict('先完成或取消待处理行动。')
            if turn_id not in {x['id'] for x in s['turns']}: raise GameConflict('回合不存在。')
            branch=uuid4().hex;s['branches'][branch]={'name':'路线 '+str(len(s['branches'])+1),'head':turn_id}
            s['active_branch']=branch
            return self.save(s)

    def settings(self,identifier,revision,**changes):
        """设置只修改展示和当前路线，不允许修改死亡规则或既有状态。"""
        with self.operation_lock(identifier):
            s=self.get(identifier)
            if s['revision']!=revision: raise GameConflict('存档已改变，请刷新。')
            if 'active_branch' in changes:
                if s['pending']: raise GameConflict('先处理待完成行动。')
                if changes['active_branch'] not in s['branches']: raise GameConflict('路线不存在。')
            for k in ('show_stats','auto_images','active_branch'):
                if k in changes and changes[k] is not None: s[k]=changes[k]
            if changes.get('cancel_pending'):s['pending']=None;s['error']=None
            return self.save(s)
