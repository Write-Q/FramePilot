"""Frozen additive domain foundation; legacy rows and checkpoints are untouched."""
from alembic import op
revision = '0002_domain_foundation'
down_revision = '0001_postgres'
branch_labels = None
depends_on = None

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_domain(metadata):
    tables = {}

    def string(name, nullable=False, default=None):
        return sa.Column(name, sa.String(64), nullable=nullable, server_default=default)

    def text(name, default=None):
        return sa.Column(name, sa.Text, nullable=False, server_default=default)

    def document(name):
        return sa.Column(name, JSONB, nullable=False, server_default=sa.text("'{}'::jsonb"))

    def timestamp(name, nullable=True):
        return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                         server_default=None if nullable else sa.func.now())

    def positive(name, default=None):
        return sa.Column(name, sa.Integer, nullable=False, server_default=default)

    def unique(*names):
        return sa.UniqueConstraint(*names)

    def fk(columns, parent, target=None, **kwargs):
        target = target or ['project_id', 'id']
        return sa.ForeignKeyConstraint(columns, ['fp_' + parent + '.' + n for n in target], **kwargs)

    def owned(name, *items):
        table = sa.Table('fp_' + name, metadata,
            string('id'), string('project_id'), timestamp('created_at', False),
            sa.PrimaryKeyConstraint('id'), unique('project_id', 'id'),
            sa.ForeignKeyConstraint(['project_id'], ['fp_projects.id']), *items)
        for column in table.columns:
            if column.name in {'version_no', 'position', 'row_version', 'schema_version', 'attempt_no'}:
                table.append_constraint(sa.CheckConstraint(column.name + ' > 0', name='ck_' + name + '_' + column.name))
        tables[name] = table
        return table

    def version(name, owner, owner_table, *items):
        return owned(name, string(owner), positive('version_no'), positive('schema_version', '1'),
            unique('project_id', owner, 'id'), unique(owner, 'version_no'),
            fk(['project_id', owner], owner_table), *items)

    tables['project_details'] = sa.Table('fp_project_details', metadata,
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), primary_key=True),
        text('name'), text('synopsis', ''), positive('row_version', '1'),
        timestamp('updated_at', False), timestamp('last_opened_at'), timestamp('archived_at'),
        sa.CheckConstraint('row_version > 0', name='ck_project_details_row_version'))
    owned('chapters', text('title'), positive('position'), positive('row_version', '1'), timestamp('archived_at'))
    sa.Index('uq_fp_chapters_active_position', tables['chapters'].c.project_id,
             tables['chapters'].c.position, unique=True, postgresql_where=sa.text('archived_at IS NULL'))
    owned('project_brief_versions', positive('version_no'), positive('schema_version', '1'),
          document('content'), unique('project_id', 'version_no'))
    version('chapter_input_versions', 'chapter_id', 'chapters', text('original_story'), text('constraints', ''))
    owned('scripts', string('chapter_id'), string('current_version_id', True), positive('row_version', '1'),
          unique('chapter_id'), unique('project_id', 'chapter_id', 'id'),
          fk(['project_id', 'chapter_id'], 'chapters'),
          fk(['project_id', 'id', 'current_version_id'], 'script_versions', ['project_id', 'script_id', 'id'],
             name='fk_fp_scripts_current_version', use_alter=True))
    version('script_versions', 'script_id', 'scripts', string('chapter_id'), string('parent_version_id', True),
          string('input_version_id', True), string('brief_version_id', True), text('body'), document('card'),
          unique('project_id', 'chapter_id', 'id'),
          fk(['project_id', 'chapter_id', 'script_id'], 'scripts', ['project_id', 'chapter_id', 'id']),
          fk(['project_id', 'script_id', 'parent_version_id'], 'script_versions', ['project_id', 'script_id', 'id']),
          fk(['project_id', 'chapter_id', 'input_version_id'], 'chapter_input_versions', ['project_id', 'chapter_id', 'id']),
          fk(['project_id', 'brief_version_id'], 'project_brief_versions'),
          sa.CheckConstraint('(version_no = 1 AND parent_version_id IS NULL) OR (version_no > 1 AND parent_version_id IS NOT NULL)', name='ck_script_parent_required'))
    owned('assets', string('asset_type'), string('scope_chapter_id', True), text('display_name'),
          positive('row_version', '1'), timestamp('archived_at'),
          fk(['project_id', 'scope_chapter_id'], 'chapters'),
          sa.CheckConstraint("asset_type IN ('character', 'location', 'prop')", name='ck_asset_type'))
    version('asset_versions', 'asset_id', 'assets', document('definition'))
    owned('asset_version_decisions', sa.Column('decision_seq', sa.BigInteger, sa.Identity(), nullable=False, unique=True), string('asset_version_id'), string('decision'), text('reason', ''),
          fk(['project_id', 'asset_version_id'], 'asset_versions'),
          sa.CheckConstraint("decision IN ('approved', 'rejected', 'revoked')", name='ck_asset_decision'))
    owned('chapter_asset_links', string('chapter_id'), string('asset_id'), string('selected_version_id', True),
          unique('chapter_id', 'asset_id'), fk(['project_id', 'chapter_id'], 'chapters'),
          fk(['project_id', 'asset_id'], 'assets'),
          fk(['project_id', 'asset_id', 'selected_version_id'], 'asset_versions', ['project_id', 'asset_id', 'id']))
    owned('script_asset_refs', string('chapter_id'), string('script_version_id'), string('asset_id'), string('asset_version_id'),
          unique('script_version_id', 'asset_id'),
          fk(['project_id', 'chapter_id', 'script_version_id'], 'script_versions', ['project_id', 'chapter_id', 'id']),
          fk(['project_id', 'asset_id', 'asset_version_id'], 'asset_versions', ['project_id', 'asset_id', 'id']))
    owned('asset_origins', string('asset_version_id'), string('source_script_version_id'), text('source_quote', ''),
          fk(['project_id', 'asset_version_id'], 'asset_versions'), fk(['project_id', 'source_script_version_id'], 'script_versions'))
    owned('review_runs', string('script_version_id'), string('task_id', True), string('rubric_version'), document('result'),
          unique('project_id', 'script_version_id', 'id'), fk(['project_id', 'script_version_id'], 'script_versions'),
          fk(['project_id', 'task_id'], 'generation_tasks', name='fk_review_task', use_alter=True))
    owned('review_issues', string('review_run_id'), string('category'), text('description'), text('suggestion', ''),
          document('evidence'), sa.Column('needs_user', sa.Boolean, nullable=False, server_default=sa.false()),
          string('fingerprint', True), unique('project_id', 'review_run_id', 'id'), fk(['project_id', 'review_run_id'], 'review_runs'))
    owned('review_issue_assets', string('review_issue_id'), string('asset_version_id'),
          unique('review_issue_id', 'asset_version_id'), fk(['project_id', 'review_issue_id'], 'review_issues'),
          fk(['project_id', 'asset_version_id'], 'asset_versions'))
    owned('revision_requests', string('script_id'), string('base_version_id'), string('review_run_id', True),
          string('action'), text('feedback', ''), string('idempotency_key'),
          unique('project_id', 'idempotency_key'), unique('project_id', 'review_run_id', 'id'),
          fk(['project_id', 'script_id', 'base_version_id'], 'script_versions', ['project_id', 'script_id', 'id']),
          fk(['project_id', 'base_version_id', 'review_run_id'], 'review_runs', ['project_id', 'script_version_id', 'id']),
          sa.CheckConstraint("action IN ('revise', 'clarify', 'confirm')", name='ck_revision_action'))
    owned('issue_decisions', string('request_id'), string('review_run_id'), string('issue_id'), string('choice'), text('instruction', ''),
          unique('request_id', 'issue_id'),
          fk(['project_id', 'review_run_id', 'request_id'], 'revision_requests', ['project_id', 'review_run_id', 'id']),
          fk(['project_id', 'review_run_id', 'issue_id'], 'review_issues', ['project_id', 'review_run_id', 'id']),
          sa.CheckConstraint("choice IN ('adopt', 'replace', 'preserve', 'accept')", name='ck_issue_choice'))
    owned('generation_tasks', string('chapter_id'), string('request_id', True), string('input_version_id', True),
          string('brief_version_id', True), string('source_version_id', True), string('result_version_id', True),
          document('input_manifest'), string('workflow_version'), string('status', default='pending'),
          positive('row_version', '1'), timestamp('finished_at'),
          fk(['project_id', 'chapter_id'], 'chapters'), fk(['project_id', 'request_id'], 'revision_requests'),
          fk(['project_id', 'chapter_id', 'input_version_id'], 'chapter_input_versions', ['project_id', 'chapter_id', 'id']),
          fk(['project_id', 'brief_version_id'], 'project_brief_versions'),
          fk(['project_id', 'chapter_id', 'source_version_id'], 'script_versions', ['project_id', 'chapter_id', 'id']),
          fk(['project_id', 'chapter_id', 'result_version_id'], 'script_versions', ['project_id', 'chapter_id', 'id']),
          unique('project_id', 'chapter_id', 'id'),
          sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')", name='ck_generation_status'))
    owned('task_attempts', string('task_id'), positive('attempt_no'), string('status', default='running'),
          timestamp('started_at', False), timestamp('finished_at'), string('error_code', True),
          unique('task_id', 'attempt_no'), fk(['project_id', 'task_id'], 'generation_tasks'))
    owned('call_links', sa.Column('call_id', sa.Integer, nullable=False), string('task_attempt_id'),
          string('provider', True), string('model', True), document('parameters'),
          unique('call_id'), fk(['project_id', 'call_id'], 'calls'), fk(['project_id', 'task_attempt_id'], 'task_attempts'))
    owned('workflow_sessions', string('chapter_id'), string('task_id'), string('thread_id'), string('workflow_version'),
          unique('thread_id'), fk(['project_id', 'chapter_id', 'task_id'], 'generation_tasks', ['project_id', 'chapter_id', 'id']))
    version('breakdown_versions', 'script_version_id', 'script_versions', document('content'))
    owned('scenes', string('breakdown_version_id'), positive('position'), text('title'), document('content'), document('continuity'),
          unique('breakdown_version_id', 'position'), unique('project_id', 'breakdown_version_id', 'id'),
          fk(['project_id', 'breakdown_version_id'], 'breakdown_versions'))
    version('storyboard_versions', 'breakdown_version_id', 'breakdown_versions', document('content'),
          unique('project_id', 'breakdown_version_id', 'id'))
    owned('shots', string('storyboard_version_id'), string('breakdown_version_id'), string('scene_id'), positive('position'),
          document('content'), document('continuity'), unique('storyboard_version_id', 'position'),
          fk(['project_id', 'breakdown_version_id', 'storyboard_version_id'], 'storyboard_versions', ['project_id', 'breakdown_version_id', 'id']),
          fk(['project_id', 'breakdown_version_id', 'scene_id'], 'scenes', ['project_id', 'breakdown_version_id', 'id']))
    owned('media_files', text('storage_key'), string('media_type'), string('checksum', True),
          sa.Column('size_bytes', sa.BigInteger, nullable=False), document('metadata'),
          unique('storage_key'), sa.CheckConstraint('size_bytes >= 0', name='ck_media_size'))
    owned('asset_media_links', string('asset_version_id'), string('media_file_id'), string('role', default='reference'),
          unique('asset_version_id', 'media_file_id', 'role'), fk(['project_id', 'asset_version_id'], 'asset_versions'),
          fk(['project_id', 'media_file_id'], 'media_files'))
    owned('shot_media_links', string('shot_id'), string('media_file_id'), string('role', default='output'),
          unique('shot_id', 'media_file_id', 'role'), fk(['project_id', 'shot_id'], 'shots'), fk(['project_id', 'media_file_id'], 'media_files'))
    owned('scene_asset_refs', string('scene_id'), string('asset_id'), string('asset_version_id'),
          unique('scene_id', 'asset_id'), fk(['project_id', 'scene_id'], 'scenes'),
          fk(['project_id', 'asset_id', 'asset_version_id'], 'asset_versions', ['project_id', 'asset_id', 'id']))
    owned('shot_asset_refs', string('shot_id'), string('asset_id'), string('asset_version_id'),
          unique('shot_id', 'asset_id'), fk(['project_id', 'shot_id'], 'shots'),
          fk(['project_id', 'asset_id', 'asset_version_id'], 'asset_versions', ['project_id', 'asset_id', 'id']))
    owned('task_media_links', string('task_id'), string('media_file_id'), string('role'),
          unique('task_id', 'media_file_id', 'role'), fk(['project_id', 'task_id'], 'generation_tasks'),
          fk(['project_id', 'media_file_id'], 'media_files'),
          sa.CheckConstraint("role IN ('input', 'output')", name='ck_task_media_role'))
    owned('task_shot_links', string('task_id'), string('shot_id'),
          unique('task_id', 'shot_id'), fk(['project_id', 'task_id'], 'generation_tasks'), fk(['project_id', 'shot_id'], 'shots'))
    sa.Index('ix_fp_project_details_updated', tables['project_details'].c.updated_at)
    sa.Index('ix_fp_assets_scope', tables['assets'].c.project_id, tables['assets'].c.asset_type, tables['assets'].c.scope_chapter_id)
    sa.Index('ix_fp_tasks_status', tables['generation_tasks'].c.project_id, tables['generation_tasks'].c.status)
    # Every ownership path is indexed for project listing and FK checks.
    for name, table in tables.items():
        if 'id' in table.c:
            sa.Index('ix_fp_' + name + '_project', table.c.project_id)
    return tables


IMMUTABLE_TABLES = (
    'project_brief_versions', 'chapter_input_versions', 'script_versions',
    'asset_versions', 'asset_version_decisions', 'script_asset_refs', 'asset_origins',
    'review_runs', 'review_issues', 'review_issue_assets', 'revision_requests',
    'issue_decisions', 'breakdown_versions', 'scenes', 'storyboard_versions',
    'scene_asset_refs', 'shot_asset_refs', 'task_media_links', 'task_shot_links', 'shots', 'media_files', 'asset_media_links', 'shot_media_links', 'call_links',
)


def _schema():
    metadata = sa.MetaData()
    sa.Table('fp_projects', metadata, sa.Column('id', sa.String(64), primary_key=True))
    sa.Table('fp_calls', metadata, sa.Column('id', sa.Integer, primary_key=True),
             sa.Column('project_id', sa.String(64)), sa.UniqueConstraint('project_id', 'id'))
    return metadata, register_domain(metadata)


def upgrade():
    op.create_unique_constraint('uq_fp_calls_project_id_id', 'fp_calls', ['project_id', 'id'])
    metadata, tables = _schema()
    metadata.create_all(op.get_bind(), tables=list(tables.values()), checkfirst=False)
    op.execute("""
    CREATE FUNCTION fp_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'immutable history: %', TG_TABLE_NAME USING ERRCODE = '23514';
    END $$
    """)
    for name in IMMUTABLE_TABLES:
        op.execute(f'CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_{name} '
                   'FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change()')
    op.execute("""
    CREATE FUNCTION fp_check_asset_scope() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE scope_id varchar(64); chapter varchar(64); latest_decision varchar(64);
    BEGIN
      SELECT scope_chapter_id INTO scope_id FROM fp_assets
       WHERE project_id = NEW.project_id AND id = NEW.asset_id FOR UPDATE;
      IF TG_TABLE_NAME = 'fp_scene_asset_refs' THEN
        SELECT v.chapter_id INTO chapter FROM fp_scenes s
          JOIN fp_breakdown_versions b ON b.id = s.breakdown_version_id
          JOIN fp_script_versions v ON v.id = b.script_version_id WHERE s.id = NEW.scene_id;
      ELSIF TG_TABLE_NAME = 'fp_shot_asset_refs' THEN
        SELECT v.chapter_id INTO chapter FROM fp_shots s
          JOIN fp_breakdown_versions b ON b.id = s.breakdown_version_id
          JOIN fp_script_versions v ON v.id = b.script_version_id WHERE s.id = NEW.shot_id;
      ELSE
        chapter := NEW.chapter_id;
      END IF;
      IF scope_id IS NOT NULL AND scope_id <> chapter THEN
        RAISE EXCEPTION 'asset belongs to another chapter' USING ERRCODE = '23514';
      END IF;
      IF TG_TABLE_NAME <> 'fp_chapter_asset_links' THEN
        SELECT decision INTO latest_decision FROM fp_asset_version_decisions
         WHERE project_id = NEW.project_id AND asset_version_id = NEW.asset_version_id
         ORDER BY decision_seq DESC LIMIT 1;
        IF latest_decision IS DISTINCT FROM 'approved' THEN
          RAISE EXCEPTION 'script asset version must be approved' USING ERRCODE = '23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    for name in ('chapter_asset_links', 'script_asset_refs', 'scene_asset_refs', 'shot_asset_refs'):
        op.execute(f'CREATE TRIGGER asset_scope BEFORE INSERT OR UPDATE ON fp_{name} '
                   'FOR EACH ROW EXECUTE FUNCTION fp_check_asset_scope()')
    op.execute("""
    CREATE FUNCTION fp_check_asset_scope_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.scope_chapter_id IS NOT NULL AND (
        EXISTS (SELECT 1 FROM fp_chapter_asset_links WHERE asset_id = OLD.id AND chapter_id <> NEW.scope_chapter_id)
        OR EXISTS (SELECT 1 FROM fp_script_asset_refs WHERE asset_id = OLD.id AND chapter_id <> NEW.scope_chapter_id)
        OR EXISTS (SELECT 1 FROM fp_scene_asset_refs r JOIN fp_scenes s ON s.id = r.scene_id
          JOIN fp_breakdown_versions b ON b.id = s.breakdown_version_id JOIN fp_script_versions v ON v.id = b.script_version_id
          WHERE r.asset_id = OLD.id AND v.chapter_id <> NEW.scope_chapter_id)
        OR EXISTS (SELECT 1 FROM fp_shot_asset_refs r JOIN fp_shots s ON s.id = r.shot_id
          JOIN fp_breakdown_versions b ON b.id = s.breakdown_version_id JOIN fp_script_versions v ON v.id = b.script_version_id
          WHERE r.asset_id = OLD.id AND v.chapter_id <> NEW.scope_chapter_id)
      ) THEN
        RAISE EXCEPTION 'asset has references in another chapter' USING ERRCODE = '23514';
      END IF;
      IF NEW.asset_type <> OLD.asset_type AND EXISTS (SELECT 1 FROM fp_asset_versions WHERE asset_id = OLD.id) THEN
        RAISE EXCEPTION 'versioned asset type is immutable' USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute('CREATE TRIGGER asset_scope_change BEFORE UPDATE ON fp_assets '
               'FOR EACH ROW EXECUTE FUNCTION fp_check_asset_scope_change()')
    op.execute("""
    CREATE FUNCTION fp_check_script_parent() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent_number integer;
    BEGIN
      IF NEW.parent_version_id IS NOT NULL THEN
        SELECT version_no INTO parent_number FROM fp_script_versions
          WHERE project_id = NEW.project_id AND script_id = NEW.script_id AND id = NEW.parent_version_id;
        IF parent_number IS NULL OR parent_number <> NEW.version_no - 1 THEN
          RAISE EXCEPTION 'script parent must be the preceding version' USING ERRCODE = '23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute('CREATE TRIGGER script_parent BEFORE INSERT ON fp_script_versions '
               'FOR EACH ROW EXECUTE FUNCTION fp_check_script_parent()')

    op.execute("""
    CREATE FUNCTION fp_check_task_sources() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE source_chapter varchar(64);
    BEGIN
      IF TG_OP = 'UPDATE' AND (
        ROW(NEW.project_id,NEW.chapter_id,NEW.request_id,NEW.input_version_id,NEW.brief_version_id,
            NEW.source_version_id,NEW.workflow_version,NEW.input_manifest)
        IS DISTINCT FROM
        ROW(OLD.project_id,OLD.chapter_id,OLD.request_id,OLD.input_version_id,OLD.brief_version_id,
            OLD.source_version_id,OLD.workflow_version,OLD.input_manifest)
      ) THEN
        RAISE EXCEPTION 'task inputs are immutable' USING ERRCODE = '23514';
      END IF;
      IF NEW.request_id IS NOT NULL THEN
        SELECT s.chapter_id INTO source_chapter FROM fp_revision_requests r
          JOIN fp_scripts s ON s.id = r.script_id AND s.project_id = r.project_id
          WHERE r.project_id = NEW.project_id AND r.id = NEW.request_id;
        IF source_chapter IS DISTINCT FROM NEW.chapter_id THEN
          RAISE EXCEPTION 'request belongs to another chapter' USING ERRCODE = '23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute('CREATE TRIGGER task_sources BEFORE INSERT OR UPDATE ON fp_generation_tasks '
               'FOR EACH ROW EXECUTE FUNCTION fp_check_task_sources()')
    op.execute("""
    CREATE FUNCTION fp_check_review_task() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.task_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM fp_generation_tasks t JOIN fp_script_versions v
          ON t.project_id = v.project_id AND t.chapter_id = v.chapter_id
          WHERE t.id = NEW.task_id AND v.id = NEW.script_version_id AND t.project_id = NEW.project_id
      ) THEN
        RAISE EXCEPTION 'review task belongs to another chapter' USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute('CREATE TRIGGER review_task BEFORE INSERT ON fp_review_runs '
               'FOR EACH ROW EXECUTE FUNCTION fp_check_review_task()')

    op.execute("""
    CREATE FUNCTION fp_lock_asset_decision() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM a.id FROM fp_assets a JOIN fp_asset_versions v ON v.asset_id = a.id
        WHERE v.id = NEW.asset_version_id AND v.project_id = NEW.project_id FOR UPDATE OF a;
      -- Identity allocation happens before a BEFORE trigger can acquire the lock.
      -- Allocate again under that lock so committed decisions follow serialization order.
      NEW.decision_seq := nextval(pg_get_serial_sequence('fp_asset_version_decisions', 'decision_seq'));
      RETURN NEW;
    END $$
    """)
    op.execute('CREATE TRIGGER asset_decision_lock BEFORE INSERT ON fp_asset_version_decisions '
               'FOR EACH ROW EXECUTE FUNCTION fp_lock_asset_decision()')

    op.execute("""
    CREATE FUNCTION fp_check_task_shot() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM fp_generation_tasks t JOIN fp_script_versions v
          ON t.project_id = v.project_id AND t.chapter_id = v.chapter_id
          JOIN fp_breakdown_versions b ON b.script_version_id = v.id
          JOIN fp_shots s ON s.breakdown_version_id = b.id
          WHERE t.id = NEW.task_id AND s.id = NEW.shot_id AND t.project_id = NEW.project_id
      ) THEN
        RAISE EXCEPTION 'shot target belongs to another chapter' USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END $$
    """)
    op.execute('CREATE TRIGGER task_shot BEFORE INSERT ON fp_task_shot_links '
               'FOR EACH ROW EXECUTE FUNCTION fp_check_task_shot()')


def downgrade():
    metadata, tables = _schema()
    for table in tables.values():
        if op.get_bind().execute(sa.select(sa.exists().where(table.c.project_id.is_not(None)))).scalar():
            raise RuntimeError('Refusing downgrade of nonempty domain tables; restore a verified backup instead')
    metadata.drop_all(op.get_bind(), tables=list(tables.values()), checkfirst=False)
    for name in ('fp_check_task_shot', 'fp_lock_asset_decision', 'fp_check_task_sources', 'fp_check_review_task', 'fp_check_script_parent', 'fp_check_asset_scope_change', 'fp_check_asset_scope', 'fp_reject_history_change'):
        op.execute(f'DROP FUNCTION {name}()')
    op.drop_constraint('uq_fp_calls_project_id_id', 'fp_calls', type_='unique')
