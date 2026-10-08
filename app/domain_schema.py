"""Normalized domain tables. Legacy workflow tables remain authoritative for legacy runs.

All new references carry project ownership. JSON documents contain content, never
stand in for relational ownership. DDL triggers are installed by migration 0002.
"""
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
