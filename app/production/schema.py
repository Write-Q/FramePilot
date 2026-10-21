"""制作底座新增关系；配置版本不包含实际密钥。"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_production(metadata):
    profiles = sa.Table('fp_model_profiles', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('current_version', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('current_version > 0', name='ck_model_profile_current'))
    versions = sa.Table('fp_model_profile_versions', metadata,
        sa.Column('profile_id', sa.String(64), sa.ForeignKey('fp_model_profiles.id'), primary_key=True),
        sa.Column('version_no', sa.Integer, primary_key=True),
        sa.Column('config', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('version_no > 0', name='ck_model_profile_version'))
    confirmations = sa.Table('fp_storyboard_confirmations', metadata,
        sa.Column('storyboard_version_id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'],
                                ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']))
    runs = sa.Table('fp_storyboard_runs', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('source_version_id', sa.String(64), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error_code', sa.String(64)),
        sa.Column('usage', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('storyboard_version_id', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_storyboard_run_request'),
        sa.ForeignKeyConstraint(['project_id', 'source_version_id'], ['fp_script_versions.project_id', 'fp_script_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("status IN ('running','succeeded','failed','abandoned')", name='ck_storyboard_run_status'),
        sa.CheckConstraint("(status = 'running') = (finished_at IS NULL)", name='ck_storyboard_run_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (storyboard_version_id IS NOT NULL)", name='ck_storyboard_run_result'))
    sa.Index('uq_storyboard_run_active', runs.c.project_id, unique=True, postgresql_where=runs.c.status == 'running')
    sa.Index('ix_storyboard_runs_project_created', runs.c.project_id, runs.c.created_at)
    reviews = register_reviews(metadata)
    return {'profiles': profiles, 'profile_versions': versions, 'confirmations': confirmations, 'runs': runs,
            'review_runs': reviews}


def register_reviews(metadata):
    table = sa.Table('fp_storyboard_review_runs', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('source_version_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error_code', sa.String(64)),
        sa.Column('usage', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('report', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_storyboard_review_request'),
        sa.ForeignKeyConstraint(['project_id', 'source_version_id'], ['fp_script_versions.project_id', 'fp_script_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("status IN ('running','succeeded','failed','abandoned')", name='ck_storyboard_review_status'),
        sa.CheckConstraint("(status = 'running') = (finished_at IS NULL)", name='ck_storyboard_review_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (report IS NOT NULL)", name='ck_storyboard_review_result'))
    sa.Index('uq_storyboard_review_active', table.c.project_id, unique=True, postgresql_where=table.c.status == 'running')
    sa.Index('ix_storyboard_reviews_project_created', table.c.project_id, table.c.created_at)
    return table
