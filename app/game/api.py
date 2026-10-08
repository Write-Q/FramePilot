"""游戏HTTP接口，独立于旧编剧接口。"""
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, ConfigDict
from threading import RLock
from app.game.service import GameConflict, GameService
from app.game.store import PostgresStore
from app.game.images import GameImages, HttpImageProvider


class Request(BaseModel):
    """拒绝未声明字段，避免把用户输入当状态写入。"""
    model_config=ConfigDict(extra='forbid')


class Opening(Request):
    background:str=Field(min_length=1,max_length=5000)
    death:Literal['story','adventure','hardcore']='adventure'
    show_stats:bool=True
    auto_images:bool=True


class Background(Request):
    requirements:str=Field(max_length=4000,default='')
    feedback:str=Field(max_length=6000,default='')


class Action(Request):
    action:str=Field(min_length=1,max_length=2000)
    operation_id:str=Field(min_length=1,max_length=64)
    branch:str=Field(min_length=1,max_length=64)
    revision:int=Field(ge=1)


class Fork(Request):
    turn_id:str
    revision:int=Field(ge=1)


class Settings(Request):
    revision:int=Field(ge=1)
    show_stats:bool|None=None
    auto_images:bool|None=None
    active_branch:str|None=None
    cancel_pending:bool=False


class Image(Request):
    turn_id:str


def install_game(app, configured_database_url=None):
    """首次访问时创建服务；未执行迁移时明确提示，绝不自动建表。"""
    router=APIRouter(prefix='/api/game',tags=['互动故事'])
    initialization_lock=RLock()
    def services():
        with initialization_lock:
            return initialize_services()

    def initialize_services():
        if not hasattr(app.state,'game'):
            from app.database import database_url, ROOT
            # 复用现有文本provider；供应商生命周期由主应用负责。
            game=GameService(PostgresStore(database_url(configured_database_url).render_as_string(hide_password=False)),app.state.stories.provider)
            app.state.game=game;app.state.game_images=GameImages(game,HttpImageProvider(),ROOT/'data'/'game-images')
            try:app.state.game_images.recover()
            except Exception:
                del app.state.game;del app.state.game_images;game.store.close()
                raise HTTPException(503,'游戏表尚未就绪，请执行数据库升级后重试。') from None
        return app.state.game,app.state.game_images

    def invoke(fn):
        try:return fn()
        except GameConflict as exc:raise HTTPException(409,str(exc)) from None
        except KeyError:raise HTTPException(404,'存档或回合不存在。') from None
        except HTTPException:raise
        except Exception:raise HTTPException(502,'模型或存储请求未完成，请检查配置并刷新存档。') from None

    def auto(game,images,s,tasks):
        if s['turns'] and s['auto_images'] and not s['error'] and images.provider.configured:
            turn=game.current(s)
            if turn['visual_change'] and not any(i['turn_id']==turn['id'] for i in s['images']):
                try:
                    job=images.reserve(s['id'],turn['id']);tasks.add_task(images.run,s['id'],job)
                except GameConflict:pass
        result=game.get(s['id']);result['image_configured']=images.provider.configured
        return result

    @router.get('/sessions')
    def listing():
        def operation():
            game,images=services()
            return {'image_configured':images.provider.configured,'sessions':[{'id':s['id'],'background':s['background'][:80],'created_at':s['created_at']} for s in game.store.list()]}
        return invoke(operation)

    @router.post('/backgrounds')
    def backgrounds(request:Background):
        return invoke(lambda:services()[0].backgrounds(request.requirements,request.feedback))

    @router.post('/sessions',status_code=201)
    def create(request:Opening,tasks:BackgroundTasks):
        def operation():
            game,images=services();s=game.create(**request.model_dump());return auto(game,images,s,tasks)
        return invoke(operation)

    @router.get('/sessions/{identifier}')
    def get(identifier:str):
        def operation():
            game,images=services();s=game.get(identifier);s['image_configured']=images.provider.configured;return s
        return invoke(operation)

    @router.post('/sessions/{identifier}/open/retry')
    def retry_open(identifier:str,tasks:BackgroundTasks):
        def operation():
            game,images=services();return auto(game,images,game.resume_open(identifier),tasks)
        return invoke(operation)

    @router.post('/sessions/{identifier}/actions')
    def act(identifier:str,request:Action,tasks:BackgroundTasks):
        def operation():
            game,images=services();s=game.act(identifier,request.branch,request.action,request.operation_id,request.revision)
            return auto(game,images,s,tasks)
        return invoke(operation)

    @router.post('/sessions/{identifier}/branches')
    def fork(identifier:str,request:Fork):
        return invoke(lambda:services()[0].fork(identifier,request.turn_id,request.revision))

    @router.patch('/sessions/{identifier}')
    def settings(identifier:str,request:Settings):
        return invoke(lambda:services()[0].settings(identifier,**request.model_dump(exclude_none=True)))

    @router.post('/sessions/{identifier}/images',status_code=202)
    def image(identifier:str,request:Image,tasks:BackgroundTasks):
        def operation():
            _,images=services();job=images.reserve(identifier,request.turn_id);tasks.add_task(images.run,identifier,job)
            return {'job_id':job}
        return invoke(operation)

    @router.get('/sessions/{identifier}/images/{image_id}')
    def image_file(identifier:str,image_id:str):
        def operation():
            game,images=services();entry=next((i for i in game.get(identifier)['images'] if i['id']==image_id and i['status']=='ready'),None)
            if not entry:raise KeyError(image_id)
            return FileResponse(images.path(identifier,entry['file']),media_type=entry['mime_type'])
        return invoke(operation)

    @router.get('/sessions/{identifier}/export')
    def export(identifier:str):
        def operation():
            game,_=services();s=game.get(identifier)
            lines=['# 互动故事记录',s['background']]
            if s['turns']:
                for t in game.lineage(s,game.current(s)['id']):lines.extend(['\n## '+t['action'],t['text']])
            return PlainTextResponse('\n\n'.join(lines),headers={'Content-Disposition':'attachment; filename="story.md"'})
        return invoke(operation)

    @app.get('/play',include_in_schema=False)
    def play():return FileResponse(Path(__file__).parent.parent/'static'/'game.html')

    app.include_router(router)
