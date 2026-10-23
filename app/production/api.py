"""制作API：配置、版本化分镜与显式单次规划调用。"""
from threading import RLock
from typing import get_args

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from app.production.contracts import (ConfirmStoryboard, Contract, CreateStoryboard, ModelConfig,
                                      Purpose, ReviseStoryboard, UpdateModelConfig, GenerateStoryboard)
from app.production.store import InvalidProduction, ProductionConflict, ProductionStore
from app.production.generation import StoryboardGenerator
from app.production.planning import PlanningUnavailable
from app.production.review_contracts import ReviewRequest
from app.production.reviews import StoryboardReviewer
from app.production.media_api import install_media_routes
from app.production.video_api import install_video_routes
from app.production.inspection_api import install_inspection_routes


def _known_fields():
    fields = {'body', 'path', 'query', '[key]', 'profile_id', 'project_id', 'storyboard_id', 'version'}
    fields.update(get_args(Purpose))
    pending = [Contract]
    while pending:
        model = pending.pop()
        fields.update(model.model_fields)
        pending.extend(model.__subclasses__())
    return fields


KNOWN_FIELDS = _known_fields()


class PrivateValidationRoute(APIRoute):
    """配置填写错误时只返回字段和原因，避免框架回显误填的密钥。"""
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                return JSONResponse(status_code=422, content={'detail': [
                    {'loc': [part if isinstance(part, int) or part in KNOWN_FIELDS else '<unknown-field>'
                             for part in error['loc']],
                     'type': error['type'], 'msg': error['msg']}
                    for error in exc.errors()]})

        return sanitized


def install_production(app, configured_database_url=None, storyboard_provider=None, review_provider=None):
    router = APIRouter(prefix='/api/production', tags=['制作底座'], route_class=PrivateValidationRoute)
    lock = RLock()

    def store():
        with lock:
            if not hasattr(app.state, 'production'):
                app.state.production = ProductionStore(configured_database_url)
            return app.state.production

    def invoke(operation):
        try:
            return operation(store())
        except KeyError:
            raise HTTPException(404, '项目、分镜或模型配置版本不存在') from None
        except ProductionConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except InvalidProduction as exc:
            raise HTTPException(422, str(exc)) from None
        except PlanningUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except SQLAlchemyError:
            raise HTTPException(503, '制作数据访问失败，请检查数据库与显式迁移状态') from None

    def generator(service):
        return StoryboardGenerator(service, storyboard_provider)

    @router.post('/projects/{project_id}/storyboards/{storyboard_id}/review-runs', status_code=201,
                 summary='显式请求一次文字分镜审核，不改稿、不确认、不代表影像质量通过')
    def run_review(project_id: str, storyboard_id: str, request: ReviewRequest):
        return invoke(lambda service: StoryboardReviewer(service, review_provider).review(project_id, storyboard_id, request))

    @router.get('/projects/{project_id}/storyboards/{storyboard_id}/review-runs')
    def review_runs(project_id: str, storyboard_id: str):
        return invoke(lambda service: StoryboardReviewer(service, review_provider).list_runs(project_id, storyboard_id))

    @router.post('/projects/{project_id}/storyboards/{storyboard_id}/review-runs/{run_id}/abandon')
    def abandon_review(project_id: str, storyboard_id: str, run_id: str):
        return invoke(lambda service: StoryboardReviewer(service, review_provider).abandon(project_id, storyboard_id, run_id))

    @router.post('/projects/{project_id}/storyboard-runs', status_code=201,
                 summary='显式发起一次文本分镜请求；固定配置版本，幂等且不自动重试')
    def generate(project_id: str, request: GenerateStoryboard):
        return invoke(lambda service: generator(service).generate(project_id, request))

    @router.get('/projects/{project_id}/storyboard-runs', summary='恢复运行记录与原始生成结果')
    def runs(project_id: str):
        return invoke(lambda service: generator(service).list_runs(project_id))

    @router.post('/projects/{project_id}/storyboard-runs/{run_id}/abandon',
                 summary='标记中断，不取消外部调用；拒绝稍后返回的结果')
    def abandon(project_id: str, run_id: str):
        return invoke(lambda service: generator(service).abandon(project_id, run_id))

    @router.get('/projects/{project_id}/storyboards/{storyboard_id}/review',
                summary='有限程序规则提醒，不代表语义或影像审核通过')
    def review(project_id: str, storyboard_id: str, version: int | None = None):
        return invoke(lambda service: generator(service).review(project_id, storyboard_id, version))

    @router.get('/adapters', summary='查询适配器预留状态，不代表真实能力验证')
    def adapters():
        return {'capabilities_verified': False, 'adapters': [
            {'id': 'openai_chat', 'purposes': ['text', 'review'], 'executable': True,
             'status': 'implemented_unverified', 'description': '已实现兼容Chat Completions的文本规划；具体网关和模型待验证'},
            {'id': 'openai_images', 'purposes': ['image'], 'executable': True,
             'status': 'implemented_unverified', 'description': '单图文生图、base64输出；具体网关待验证，需独立worker'},
            {'id': 'vendor_native', 'purposes': ['text', 'image', 'video', 'review', 'asr', 'tts'],
             'executable': False, 'status': 'reserved', 'description': '原生协议扩展点，尚未接执行器'}]}

    @router.post('/model-profiles', status_code=201, summary='新建模型配置，只保存密钥环境变量名')
    def create_profile(request: ModelConfig):
        return invoke(lambda service: service.create_profile(request))

    @router.get('/model-profiles', summary='列出当前模型配置')
    def profiles():
        return invoke(lambda service: service.list_profiles())

    @router.get('/model-profiles/{profile_id}', summary='读取模型当前配置')
    def profile(profile_id: str):
        return invoke(lambda service: service.get_profile(profile_id))

    @router.get('/model-profiles/{profile_id}/versions/{version}', summary='读取模型固定配置版本')
    def profile_version(profile_id: str, version: int):
        return invoke(lambda service: service.get_profile(profile_id, version))

    @router.put('/model-profiles/{profile_id}', summary='创建模型配置新版本，拒绝过期提交')
    def update_profile(profile_id: str, request: UpdateModelConfig):
        return invoke(lambda service: service.update_profile(profile_id, request))

    @router.post('/projects/{project_id}/storyboards', status_code=201,
                 summary='从已确认剧本创建手工分镜及固定场戏拆解，不调用模型')
    def create_storyboard(project_id: str, request: CreateStoryboard):
        return invoke(lambda service: service.create_storyboard(project_id, request))

    @router.get('/projects/{project_id}/storyboards', summary='列出项目分镜的最新版本')
    def storyboards(project_id: str):
        return invoke(lambda service: service.list_storyboards(project_id))

    @router.get('/projects/{project_id}/storyboards/{storyboard_id}', summary='读取分镜及来源有效性')
    def storyboard(project_id: str, storyboard_id: str):
        return invoke(lambda service: service.get_storyboard(project_id, storyboard_id))

    @router.get('/projects/{project_id}/storyboards/{storyboard_id}/versions/{version}',
                summary='读取不可覆盖的分镜历史')
    def storyboard_version(project_id: str, storyboard_id: str, version: int):
        return invoke(lambda service: service.get_storyboard(project_id, storyboard_id, version))

    @router.post('/projects/{project_id}/storyboards/{storyboard_id}/versions', status_code=201,
                 summary='保存新分镜版本，镜头稳定编号保留，旧确认不自动继承')
    def revise(project_id: str, storyboard_id: str, request: ReviseStoryboard):
        return invoke(lambda service: service.revise_storyboard(project_id, storyboard_id, request))

    @router.post('/projects/{project_id}/storyboards/{storyboard_id}/confirm',
                 summary='确认确切分镜版本；不授权付费生成')
    def confirm(project_id: str, storyboard_id: str, request: ConfirmStoryboard):
        return invoke(lambda service: service.confirm_storyboard(project_id, storyboard_id, request.expected_version))

    install_media_routes(router, invoke)
    install_video_routes(router, invoke, app)
    install_inspection_routes(router, invoke)
    app.include_router(router)
