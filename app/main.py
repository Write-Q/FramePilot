"""FramePilot 本地故事创作工作台：HTTP 层只做输入、输出与错误映射。"""
import os
import json
import difflib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.domain import CreateProject, ResumeProject
from app.provider import DeepSeekProvider, ROOT
from app.service import StoryService, Conflict
from app.streaming import stream_operation


def create_app(*, data_dir=None, provider=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.stories = StoryService(
            data_dir or os.getenv('FRAMEPILOT_DATA_DIR', str(ROOT / 'data')),
            provider or DeepSeekProvider(),
        )
        yield
        app.state.stories.close()

    app = FastAPI(title='FramePilot · 故事创作', version='0.2.0', docs_url=None,
                  description='本地单用户学习版：故事理解、审核、最多三轮修订与人工确认。', lifespan=lifespan)
    static = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=static), name='static')

    def invoke(operation):
        try:
            return operation()
        except KeyError:
            raise HTTPException(404, '项目不存在') from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get('/', include_in_schema=False)
    def home():
        return FileResponse(static / 'index.html')

    @app.get('/docs', include_in_schema=False)
    def docs():
        return get_swagger_ui_html(openapi_url='/openapi.json', title=app.title,
                                  swagger_js_url='/static/swagger/swagger-ui-bundle.js',
                                  swagger_css_url='/static/swagger/swagger-ui.css',
                                  swagger_favicon_url='/static/swagger/favicon-32x32.png',
                                  swagger_ui_parameters={'validatorUrl': None})

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'provider': 'deepseek',
                'model': os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'),
                'configured': bool(os.getenv('DEEPSEEK_API_KEY')), 'max_revisions': 3, 'max_calls': 10}

    @app.post('/api/projects', status_code=201, summary='创建故事并进行首次审核')
    def create_project(request: CreateProject):
        return invoke(lambda: app.state.stories.create(request))

    @app.get('/api/projects/{project_id}', summary='读取当前故事与等待确认状态')
    def get_project(project_id: str):
        return invoke(lambda: app.state.stories.get(project_id))

    @app.get('/api/projects/{project_id}/versions', summary='读取历史版本')
    def versions(project_id: str):
        return invoke(lambda: app.state.stories.versions(project_id))

    @app.post('/api/projects/{project_id}/resume', summary='提交修改要求或确认当前版本')
    def resume(project_id: str, request: ResumeProject):
        return invoke(lambda: app.state.stories.resume(project_id, request))

    @app.post('/api/projects/stream', summary='流式创建与审核故事')
    def create_stream(request: CreateProject):
        return stream_operation(lambda: app.state.stories.create(request))

    @app.post('/api/projects/{project_id}/resume/stream', summary='流式修订或确认故事')
    def resume_stream(project_id: str, request: ResumeProject):
        return stream_operation(lambda: app.state.stories.resume(project_id, request))

    @app.post('/api/projects/{project_id}/retry', summary='从失败节点手动重试，不重置额度')
    def retry(project_id: str):
        return invoke(lambda: app.state.stories.retry(project_id))

    @app.post('/api/projects/{project_id}/retry/stream', summary='流式重试失败节点')
    def retry_stream(project_id: str):
        return stream_operation(lambda: app.state.stories.retry(project_id))

    @app.get('/api/projects/{project_id}/diff', summary='比较两个已保存的正文版本')
    def diff(project_id: str, from_version: int, to_version: int):
        versions = invoke(lambda: app.state.stories.versions(project_id))
        by_id = {v['version']: v for v in versions}
        if from_version not in by_id or to_version not in by_id:
            raise HTTPException(404, '版本不存在')
        result = '\n'.join(difflib.unified_diff(by_id[from_version]['draft'].splitlines(),
                         by_id[to_version]['draft'].splitlines(), fromfile=f'V{from_version}',
                         tofile=f'V{to_version}', lineterm=''))
        return {'diff': result}

    @app.get('/api/projects/{project_id}/export', summary='导出当前剧本、原稿与决策记录')
    def export(project_id: str):
        project = invoke(lambda: app.state.stories.get(project_id))
        state = project['state']
        review_status = '未经故事审核' if state['mode'] == 'direct' else f"审核版本：{state['reviewed_version']}；当前版本：{state['version']}；状态：{state['status']}"
        text = f"# FramePilot 剧本交接\n\n{review_status}\n\n## 当前剧本\n\n{state['draft']}\n\n## 最初输入\n\n{state['original_story']}\n\n## 用户要求\n\n{state['constraints']}\n\n## 未解决问题与决策记录\n\n"
        text += json.dumps({'issues':state['issues'], 'decisions':state.get('decision_history', [])},ensure_ascii=False,indent=2)
        return PlainTextResponse(text, headers={'Content-Disposition':'attachment; filename="framepilot-story.md"'})

    return app


app = create_app()
