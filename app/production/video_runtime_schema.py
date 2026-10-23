"""Independent durable video jobs; no default video provider or output validator."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_video_runtime(metadata):
    runs = sa.Table('fp_video_runs', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('shot_id', sa.String(64), nullable=False),
        sa.Column('shot_key', sa.String(64), nullable=False),
        sa.Column('first_frame_run_id', sa.String(64), nullable=False),
        sa.Column('first_frame_media_id', sa.String(64), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('external_id', sa.String(1000)),
        sa.Column('claim_id', sa.String(64)),
        sa.Column('error_code', sa.String(64)),
        sa.Column('output', JSONB(none_as_null=True)),
        sa.Column('next_poll_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'id', name='uq_video_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_video_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'shot_id'], ['fp_shots.project_id', 'fp_shots.id']),
        sa.ForeignKeyConstraint(['project_id', 'first_frame_run_id'], ['fp_shot_media_runs.project_id', 'fp_shot_media_runs.id']),
        sa.ForeignKeyConstraint(['project_id', 'first_frame_media_id'], ['fp_media_files.project_id', 'fp_media_files.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("status IN ('queued','submitting','submitted','polling','succeeded','failed','unknown','cancelled')", name='ck_video_status'),
        sa.CheckConstraint("(status IN ('queued','submitting','submitted','polling')) = (finished_at IS NULL)", name='ck_video_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (output IS NOT NULL)", name='ck_video_output'),
        sa.CheckConstraint("status NOT IN ('submitted','polling','succeeded') OR external_id IS NOT NULL", name='ck_video_external'),
        sa.CheckConstraint("(status IN ('submitting','polling')) = (claim_id IS NOT NULL)", name='ck_video_claim'),
        sa.CheckConstraint("(status = 'submitted') = (next_poll_at IS NOT NULL)", name='ck_video_poll_due'))
    sa.Index('ix_video_queue', runs.c.status, runs.c.next_poll_at, runs.c.created_at)
    sa.Index('uq_video_active_shot', runs.c.project_id, runs.c.storyboard_version_id, runs.c.shot_key,
             unique=True, postgresql_where=runs.c.status.in_(['queued', 'submitting', 'submitted', 'polling']))
    selections = sa.Table('fp_video_selections', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_video_runs.project_id', 'fp_video_runs.id']))
    sa.Index('ix_video_selections_project', selections.c.project_id, selections.c.id)
    return {'video_runs': runs, 'video_selections': selections}
