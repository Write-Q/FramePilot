"""Source-neutral local clip history, independent of supplier jobs and profiles."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_local_clips(metadata):
    table = sa.Table('fp_local_clips', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('storyboard_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('version_no', sa.Integer, nullable=False),
        sa.Column('filename', sa.String(180), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('output', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'id', name='uq_local_clip_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_local_clip_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_id'], ['fp_breakdown_versions.project_id', 'fp_breakdown_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.CheckConstraint("id ~ '^local_[a-f0-9]{32}$'", name='ck_local_clip_id'),
        sa.CheckConstraint('version_no >= 1', name='ck_local_clip_version'),
        sa.CheckConstraint('length(filename) BETWEEN 1 AND 180', name='ck_local_clip_filename'),
        sa.CheckConstraint("idempotency_key ~ '^[A-Za-z0-9_-]{16,64}$' AND request_sha256 ~ '^[a-f0-9]{64}$'", name='ck_local_clip_request'),
        sa.CheckConstraint("jsonb_typeof(output) = 'object' AND output->>'mime_type' IN ('video/mp4','video/webm') "
            "AND (output->>'size_bytes')::bigint BETWEEN 1 AND 268435456 "
            "AND (output->'metadata'->>'duration_ms')::integer BETWEEN 1 AND 600000", name='ck_local_clip_output'))
    sa.Index('ix_local_clip_series', table.c.project_id, table.c.storyboard_id, table.c.created_at)
    return {'local_clips': table}
