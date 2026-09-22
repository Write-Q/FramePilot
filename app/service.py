"""应用服务：业务版本、图恢复和接口之间的边界。仅支持单进程部署。"""
import sqlite3
from pathlib import Path
from threading import Lock
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.decisions import resolve_decisions
from app.events import emit
from app.provider import ProviderError
from app.storage import Repository, BudgetExceeded
from app.workflow import build_graph


class Conflict(ValueError):
    pass


class StoryService:
    def __init__(self, data_dir, provider, max_calls=10):
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.repo = Repository(data_dir / 'stories.sqlite3')
        self.graph_conn = sqlite3.connect(data_dir / 'checkpoints.sqlite3', check_same_thread=False)
        self.graph = build_graph(provider, self.repo, SqliteSaver(self.graph_conn))
        self.provider = provider
        self.max_calls = max_calls
        self.operation_lock = Lock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.repo.close()
        self.graph_conn.close()
        if hasattr(self.provider, 'close'):
            self.provider.close()

    @staticmethod
    def config(project_id):
        return {'configurable': {'thread_id': project_id}, 'recursion_limit': 40}

    def _run(self, project_id, input_data):
        emit('project', id=project_id)
        config = self.config(project_id)
        current = self.repo.get(project_id)['state']
        self.repo.save(project_id, {**current, 'status': 'running'}, None)
        error = None
        status = None
        try:
            self.graph.invoke(input_data, config)
        except BudgetExceeded:
            error, status = '累计模型调用额度耗尽，已保留当前结果。', 'budget_exhausted'
        except ProviderError as exc:
            error, status = str(exc), 'failed'
        except Exception:
            # 不把供应商请求内容、环境变量或堆栈暴露到 HTTP 响应。
            error, status = '流程执行异常，已保留检查点；请检查本地服务配置。', 'failed'
        snapshot = self.graph.get_state(config)
        state = dict(snapshot.values) or current
        pending = None
        if error:
            state.update(status=status, error=error)
        else:
            for task in snapshot.tasks:
                for item in task.interrupts:
                    pending = {'id': item.id, **item.value}
        self.repo.save(project_id, state, pending)
        return self.repo.get(project_id)

    def create(self, request):
        if not self.operation_lock.acquire(blocking=False):
            raise Conflict('当前有任务正在执行，请稍后再试。')
        try:
            project_id = uuid4().hex
            state = {'project_id': project_id, 'original_story': request.story, 'draft': request.story,
                     'mode': request.mode, 'constraints': request.constraints, 'version': 1,
                     'reviewed_version': 0, 'revision_count': 0, 'card': {}, 'issues': [],
                     'review_history': [], 'feedback_history': [], 'accepted_issue_ids': [],
                     'status': 'running', 'stop_reason': '', 'error': ''}
            self.repo.create(project_id, state, self.max_calls)
            if request.mode == 'direct':
                state.update(status='ready_for_production', stop_reason='原稿已保留，未进行故事审核。可导出交接文件；视频平台尚未接入。')
                self.repo.version(state)
                self.repo.save(project_id, state, None)
                emit('project', id=project_id)
                return self.repo.get(project_id)
            return self._run(project_id, state)
        finally:
            self.operation_lock.release()

    def resume(self, project_id, request):
        if not self.operation_lock.acquire(blocking=False):
            raise Conflict('当前有任务正在执行，请勿重复提交。')
        try:
            current = self.get(project_id)
            state, pending = current['state'], current['interrupt']
            if not pending or pending['id'] != request.interrupt_id or state['version'] != request.version:
                raise Conflict('当前版本或等待确认编号已变化，请刷新后重试。')
            answer = request.model_dump()
            if state['status'] == 'awaiting_direction':
                if request.action != 'choose' or request.direction_id not in {d['id'] for d in state.get('directions', [])}:
                    raise Conflict('请选择当前列出的故事方向。')
                if current['calls_used'] + 2 > current['max_calls']:
                    raise Conflict('剩余额度不足以编写并审核。')
                return self._run(project_id, Command(resume=answer))
            if request.action == 'choose':
                raise Conflict('当前不在选择故事方向阶段。')
            if request.decisions and state['mode'] != 'collaborative':
                raise Conflict('逐条采用或替换建议仅适用于协作创作。')
            try:
                resolved = resolve_decisions(state, request.decisions)
            except ValueError as exc:
                raise Conflict(str(exc)) from None
            if request.action == 'revise' and resolved and not request.feedback and all(d['choice'] == 'keep' for d in resolved):
                raise Conflict('只有保留理由时，请使用仅澄清并复审。')
            answer['revision_instructions'] = resolved
            selected = {d['issue_id'] for d in resolved}
            answer['protected_issues'] = [i for i in state['issues'] if i['id'] not in selected] if resolved else []
            if resolved:
                answer['feedback'] = request.feedback + '\n' + '\n'.join(f"{d['choice']}：{d['instruction']}" for d in resolved)
            if request.action == 'clarify':
                if current['calls_used'] + 1 > current['max_calls']:
                    raise Conflict('剩余额度不足以重新审核。')
                return self._run(project_id, Command(resume=answer))
            if request.action == 'revise':
                if state['revision_count'] >= 3:
                    raise Conflict('已达到项目累计 3 轮修订上限；请导出草稿后重新规划。')
                if current['calls_used'] + 2 > current['max_calls']:
                    raise Conflict('剩余额度不足以完成修订和审核，恢复不会重置额度。')
                if request.feedback in state['feedback_history']:
                    raise Conflict('这条反馈已提交，请给出新的补充或修改要求。')
            else:
                if state['reviewed_version'] != state['version']:
                    raise Conflict('当前版本尚未完成有效审核，不能确认。')
                if any(i['needs_user'] or i['category'] == 'constraint' for i in state['issues']):
                    raise Conflict('存在必须澄清的问题，请先提交补充信息并重新审核。')
                known = {i['id'] for i in state['issues']}
                if set(request.accepted_issue_ids) != known:
                    raise Conflict('请显式接受当前全部建议性问题，或先修订。')
            return self._run(project_id, Command(resume=answer))
        finally:
            self.operation_lock.release()

    def retry(self, project_id):
        if not self.operation_lock.acquire(blocking=False):
            raise Conflict('当前有任务执行中，请稍后重试。')
        try:
            current = self.get(project_id)
            if current['state']['status'] != 'failed':
                raise Conflict('仅失败的流程可以手动重试。')
            if current['calls_used'] >= current['max_calls']:
                raise Conflict('调用额度已耗尽，重试不会重置额度。')
            if not self.graph.get_state(self.config(project_id)).next:
                raise Conflict('没有可恢复的检查点。')
            return self._run(project_id, None)
        finally:
            self.operation_lock.release()

    def get(self, project_id):
        return self.repo.get(project_id)

    def versions(self, project_id):
        return self.repo.versions(project_id)
