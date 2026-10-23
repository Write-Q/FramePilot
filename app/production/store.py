"""制作配置与不可变分镜。网络执行不在本模块事务内发生。"""
from uuid import uuid4

import sqlalchemy as sa

from app.database import database_url
from app.legacy_domain import domain_id
from app.models import Base, domain_tables as domain, production_tables as tables
from app.production.contracts import ModelConfig, StoryboardContent


class ProductionConflict(ValueError):
    pass


class InvalidProduction(ValueError):
    pass


class ProductionStore:
    def __init__(self, url):
        self.engine = sa.create_engine(database_url(url), pool_pre_ping=True,
                                      connect_args={'connect_timeout': 10})

    def close(self):
        self.engine.dispose()

    @staticmethod
    def _profile(conn, profile_id, version=None):
        head, history = tables['profiles'], tables['profile_versions']
        current = conn.execute(sa.select(head.c.current_version).where(head.c.id == profile_id)).scalar_one_or_none()
        if current is None:
            raise KeyError(profile_id)
        row = conn.execute(sa.select(history).where(history.c.profile_id == profile_id,
                          history.c.version_no == (current if version is None else version))).mappings().first()
        if row is None:
            raise KeyError(profile_id)
        config = ModelConfig.model_validate(row['config'])
        from app.production.reasoning import options
        return {'id': profile_id, 'version': row['version_no'], 'current_version': current,
                'config': config.model_dump(mode='json'),
                'executable': ((config.adapter == 'openai_chat' and config.purpose in ('text', 'review'))
                    or (config.adapter == 'openai_images' and config.purpose == 'image')),
                'capabilities_verified': False,
                'reasoning_options': options(config),
                'created_at': row['created_at'].isoformat()}

    def create_profile(self, config):
        identity = uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(tables['profiles'].insert().values(id=identity, current_version=1))
            conn.execute(tables['profile_versions'].insert().values(
                profile_id=identity, version_no=1, config=config.model_dump(mode='json')))
            return self._profile(conn, identity)

    def update_profile(self, identity, request):
        head = tables['profiles']
        with self.engine.begin() as conn:
            current = conn.execute(sa.select(head.c.current_version).where(head.c.id == identity)
                                   .with_for_update()).scalar_one_or_none()
            if current is None:
                raise KeyError(identity)
            if current != request.expected_version:
                raise ProductionConflict('模型配置已更新，请重新读取后提交')
            # 配置身份的用途不变；如需改变用途，新建另一配置避免旧任务身份混淆。
            old = self._profile(conn, identity, current)
            if old['config']['purpose'] != request.config.purpose:
                raise ProductionConflict('配置用途不能变更，请为新用途创建配置')
            conn.execute(tables['profile_versions'].insert().values(profile_id=identity,
                version_no=current + 1, config=request.config.model_dump(mode='json')))
            conn.execute(head.update().where(head.c.id == identity).values(current_version=current + 1))
            return self._profile(conn, identity, current + 1)

    def get_profile(self, identity, version=None):
        with self.engine.connect() as conn:
            return self._profile(conn, identity, version)

    def list_profiles(self):
        with self.engine.connect() as conn:
            identities = conn.execute(sa.select(tables['profiles'].c.id).order_by(
                tables['profiles'].c.created_at, tables['profiles'].c.id)).scalars().all()
            return [self._profile(conn, identity) for identity in identities]

    @staticmethod
    def _project(conn, project_id, *, lock=False):
        table = Base.metadata.tables['fp_projects']
        query = sa.select(table).where(table.c.id == project_id)
        row = conn.execute(query.with_for_update() if lock else query).mappings().first()
        if row is None:
            raise KeyError(project_id)
        return row['snapshot'].get('state', {})

    @staticmethod
    def _require_source(state, version):
        if (state.get('mode') == 'direct' or state.get('status') != 'confirmed'
                or state.get('version') != version or state.get('reviewed_version') != version):
            raise ProductionConflict('需要当前已审核并确认的剧本版本；原稿直送不等于审核确认')

    def _validate_content(self, conn, content, body):
        scenes = {scene.key: scene for scene in content.scenes}
        for scene in content.scenes:
            if scene.source_quote not in body:
                raise InvalidProduction(f'场戏 {scene.key} 的来源引用不在固定剧本中')
        for shot in content.shots:
            if shot.source_quote not in scenes[shot.scene_key].source_quote:
                raise InvalidProduction(f'镜头 {shot.key} 的来源引用不在对应场戏原文中')
        for purpose, binding in content.bindings.items():
            try:
                profile = self._profile(conn, binding.profile_id, binding.version)
            except KeyError:
                raise InvalidProduction('绑定的模型配置版本不存在') from None
            if profile['config']['purpose'] != purpose:
                raise InvalidProduction('模型配置用途与绑定用途不一致')

    @staticmethod
    def _latest(conn, project_id, identity):
        table = domain['storyboard_versions']
        row = conn.execute(sa.select(table).where(table.c.project_id == project_id,
                table.c.breakdown_version_id == identity).order_by(table.c.version_no.desc()).limit(1)).mappings().first()
        if row is None:
            raise KeyError(identity)
        return row

    def _read(self, conn, project_id, identity, version=None):
        latest = self._latest(conn, project_id, identity)
        row = latest
        if version is not None and version != latest['version_no']:
            table = domain['storyboard_versions']
            row = conn.execute(sa.select(table).where(table.c.project_id == project_id,
                table.c.breakdown_version_id == identity, table.c.version_no == version)).mappings().first()
            if row is None:
                raise KeyError(identity)
        breakdown = domain['breakdown_versions']
        script = domain['script_versions']
        source = conn.execute(sa.select(script).join(breakdown,
            sa.and_(breakdown.c.script_version_id == script.c.id, breakdown.c.project_id == script.c.project_id))
            .where(breakdown.c.project_id == project_id, breakdown.c.id == identity)).mappings().one()
        state = self._project(conn, project_id)
        active = conn.execute(sa.select(domain['scripts'].c.current_version_id)
            .where(domain['scripts'].c.project_id == project_id,
                   domain['scripts'].c.id == source['script_id'])).scalar_one()
        current = active == source['id'] and state.get('version') == source['version_no']
        source_confirmed = (current and state.get('mode') != 'direct' and state.get('status') == 'confirmed'
                            and state.get('reviewed_version') == source['version_no'])
        confirmation = conn.execute(sa.select(tables['confirmations'].c.confirmed_at).where(
            tables['confirmations'].c.project_id == project_id,
            tables['confirmations'].c.storyboard_version_id == row['id'])).scalar_one_or_none()
        content = StoryboardContent.model_validate(row['content'])
        origin = conn.execute(sa.select(breakdown.c.content).where(breakdown.c.project_id == project_id,
                              breakdown.c.id == identity)).scalar_one()
        return {'id': identity, 'version_id': row['id'], 'version': row['version_no'],
                'current_version': latest['version_no'], 'project_id': project_id,
                'source_version': source['version_no'], 'source_version_id': source['id'],
                'source_current': current, 'source_confirmed': source_confirmed,
                'confirmed': confirmation is not None,
                'confirmation_effective': confirmation is not None and source_confirmed,
                'confirmed_at': confirmation.isoformat() if confirmation else None,
                'content': content.model_dump(mode='json'),
                'total_duration_ms': sum(shot.duration_ms for shot in content.shots),
                'created_at': row['created_at'].isoformat(), 'creation_method': origin.get('creation_method', 'manual'),
                'provenance': origin.get('provenance')}

    @staticmethod
    def _insert_board(conn, project_id, identity, version, content):
        board_id = uuid4().hex
        conn.execute(domain['storyboard_versions'].insert().values(id=board_id, project_id=project_id,
            breakdown_version_id=identity, version_no=version, schema_version=1,
            content=content.model_dump(mode='json')))
        scene_rows = conn.execute(sa.select(domain['scenes'].c.id, domain['scenes'].c.content).where(
            domain['scenes'].c.project_id == project_id,
            domain['scenes'].c.breakdown_version_id == identity)).mappings().all()
        scene_ids = {row['content']['key']: row['id'] for row in scene_rows}
        conn.execute(domain['shots'].insert(), [dict(id=uuid4().hex, project_id=project_id,
            storyboard_version_id=board_id, breakdown_version_id=identity,
            scene_id=scene_ids[shot.scene_key], position=position, content=shot.model_dump(mode='json'),
            continuity={'state_start': shot.state_start, 'state_end': shot.state_end})
            for position, shot in enumerate(content.shots, 1)])

    def create_storyboard(self, project_id, request):
        with self.engine.begin() as conn:
            return self._create_storyboard(conn, project_id, request)

    def _source(self, conn, project_id, version):
        state = self._project(conn, project_id, lock=True)
        self._require_source(state, version)
        script = domain['script_versions']
        source = conn.execute(sa.select(script).where(script.c.project_id == project_id,
            script.c.id == domain_id(project_id, 'version:' + str(version)))).mappings().first()
        if source is None:
            raise ProductionConflict('剧本领域交接版本不存在，请检查兼容桥记录')
        active = conn.execute(sa.select(domain['scripts'].c.current_version_id).where(
            domain['scripts'].c.project_id == project_id,
            domain['scripts'].c.id == source['script_id'])).scalar_one()
        if active != source['id']:
            raise ProductionConflict('领域剧本已切换版本，不能从旧入口交接')
        return source, state

    def _create_storyboard(self, conn, project_id, request, provenance=None):
        source, _ = self._source(conn, project_id, request.source_version)
        self._validate_content(conn, request.content, source['body'])
        breakdown = domain['breakdown_versions']
        number = conn.execute(sa.select(sa.func.max(breakdown.c.version_no)).where(
            breakdown.c.script_version_id == source['id'])).scalar_one() or 0
        identity = uuid4().hex
        conn.execute(breakdown.insert().values(id=identity, project_id=project_id,
            script_version_id=source['id'], version_no=number + 1, schema_version=1,
            content={'schema_version': 1, 'creation_method': 'ai' if provenance else 'manual',
                     'provenance': provenance,
                     'scenes': [scene.model_dump(mode='json') for scene in request.content.scenes]}))
        conn.execute(domain['scenes'].insert(), [dict(id=uuid4().hex, project_id=project_id,
            breakdown_version_id=identity, position=position, title=scene.title,
            content=scene.model_dump(mode='json'), continuity={})
            for position, scene in enumerate(request.content.scenes, 1)])
        self._insert_board(conn, project_id, identity, 1, request.content)
        return self._read(conn, project_id, identity)

    def revise_storyboard(self, project_id, identity, request):
        with self.engine.begin() as conn:
            state = self._project(conn, project_id, lock=True)
            old = self._read(conn, project_id, identity)
            if old['version'] != request.expected_version:
                raise ProductionConflict('分镜已更新，请重新读取后提交')
            self._require_source(state, old['source_version'])
            if not old['source_current']:
                raise ProductionConflict('来源剧本已切换，请从新剧本重新交接')
            if [s.model_dump(mode='json') for s in request.content.scenes] != old['content']['scenes']:
                raise ProductionConflict('场戏拆解已固定；调整场戏须新建一份分镜')
            body = conn.execute(sa.select(domain['script_versions'].c.body).where(
                domain['script_versions'].c.id == old['source_version_id'],
                domain['script_versions'].c.project_id == project_id)).scalar_one()
            self._validate_content(conn, request.content, body)
            self._insert_board(conn, project_id, identity, old['version'] + 1, request.content)
            return self._read(conn, project_id, identity)

    def confirm_storyboard(self, project_id, identity, expected_version):
        with self.engine.begin() as conn:
            state = self._project(conn, project_id, lock=True)
            board = self._read(conn, project_id, identity)
            if board['version'] != expected_version:
                raise ProductionConflict('只能确认当前分镜版本')
            self._require_source(state, board['source_version'])
            if not board['source_current']:
                raise ProductionConflict('来源剧本已切换，不能确认旧交接分镜')
            if not board['confirmed']:
                conn.execute(tables['confirmations'].insert().values(
                    project_id=project_id, storyboard_version_id=board['version_id']))
            return self._read(conn, project_id, identity)

    def get_storyboard(self, project_id, identity, version=None):
        # 单个读取使用一致快照，避免并发修订时版本与确认信息来自不同时间点。
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            return self._read(conn, project_id, identity, version)

    def list_storyboards(self, project_id):
        table = domain['breakdown_versions']
        with self.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            self._project(conn, project_id)
            identities = conn.execute(sa.select(table.c.id).where(table.c.project_id == project_id,
                sa.exists(sa.select(domain['storyboard_versions'].c.id).where(
                    domain['storyboard_versions'].c.breakdown_version_id == table.c.id)))
                .order_by(table.c.created_at, table.c.id)).scalars().all()
            return [self._read(conn, project_id, identity) for identity in identities]
