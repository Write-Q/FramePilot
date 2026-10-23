"""Conversation endpoints; business changes remain behind explicit proposal acceptance."""
from threading import RLock

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.assistant_contracts import CreateThread, Message, Decision
from app.assistant_actions import AssistantActions
from app.assistant_service import AssistantService
from app.production.api import PrivateValidationRoute, KNOWN_FIELDS, _known_fields
from app.production.store import ProductionStore, ProductionConflict, InvalidProduction
from app.production.planning import PlanningUnavailable


def install_assistant(app, database_url=None, planner=None, storyboard_provider=None, review_provider=None):
    # Include these additive contracts in the privacy-preserving validation response.
    KNOWN_FIELDS.update(_known_fields())
    router = APIRouter(prefix='/api/assistant', tags=['创作对话'], route_class=PrivateValidationRoute)
    lock = RLock()

    def service():
        with lock:
            if not hasattr(app.state, 'assistant'):
                store = ProductionStore(database_url)
                app.state.assistant_store = store
                actions = AssistantActions(store, app.state.stories, storyboard_provider, review_provider)
                app.state.assistant = AssistantService(store, actions, planner)
            return app.state.assistant

    def invoke(operation):
        try:
            return operation(service())
        except KeyError:
            raise HTTPException(404, '会话、项目或引用对象不存在') from None
        except ProductionConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except InvalidProduction as exc:
            raise HTTPException(422, str(exc)) from None
        except PlanningUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except ValueError:
            raise HTTPException(422, '当前上下文或操作参数无效，请重新读取工作区') from None
        except SQLAlchemyError:
            raise HTTPException(503, '对话数据访问失败，请检查数据库迁移状态') from None

    @router.post('/threads', status_code=201)
    def create(request: CreateThread):
        return invoke(lambda s: s.create(request))

    @router.get('/threads/{thread_id}')
    def read(thread_id: str):
        return invoke(lambda s: s.read(thread_id))

    @router.post('/threads/{thread_id}/messages')
    def message(thread_id: str, request: Message):
        return invoke(lambda s: s.message(thread_id, request))

    @router.post('/threads/{thread_id}/proposals/{proposal_id}/decision')
    def decide(thread_id: str, proposal_id: str, request: Decision):
        return invoke(lambda s: s.decide(thread_id, proposal_id, request))

    @router.post('/threads/{thread_id}/proposals/{proposal_id}/abandon')
    def abandon_execution(thread_id: str, proposal_id: str):
        return invoke(lambda s: s.abandon_execution(thread_id, proposal_id))

    @router.post('/threads/{thread_id}/messages/{turn_id}/abandon')
    def abandon(thread_id: str, turn_id: str):
        return invoke(lambda s: s.abandon(thread_id, turn_id))

    app.include_router(router)
