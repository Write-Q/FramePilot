"""Persistent media queue; media bytes and existing immutable media records stay separate."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_media(metadata):
    runs = sa.Table('fp_shot_media_runs', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('shot_id', sa.String(64), nullable=False),
        sa.Column('shot_key', sa.String(64), nullable=False),
        sa.Column('frame_role', sa.String(16), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('error_code', sa.String(64)),
        sa.Column('media_id', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'id', name='uq_shot_media_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_shot_media_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'shot_id'], ['fp_shots.project_id', 'fp_shots.id']),
        sa.ForeignKeyConstraint(['project_id', 'media_id'], ['fp_media_files.project_id', 'fp_media_files.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("kind = 'image'", name='ck_shot_media_kind'),
        sa.CheckConstraint("frame_role IN ('first','key','last')", name='ck_shot_media_role'),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','unknown','cancelled')", name='ck_shot_media_status'),
        sa.CheckConstraint("(status IN ('queued','running')) = (finished_at IS NULL)", name='ck_shot_media_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (media_id IS NOT NULL)", name='ck_shot_media_result'))
    sa.Index('ix_shot_media_queue', runs.c.status, runs.c.created_at)
    selections = sa.Table('fp_shot_media_selections', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_shot_media_runs.project_id', 'fp_shot_media_runs.id']))
    sa.Index('ix_shot_media_selections_project', selections.c.project_id, selections.c.id)
    return {'media_runs': runs, 'media_selections': selections}
