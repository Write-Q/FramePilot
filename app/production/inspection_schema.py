"""Immutable decoded-video evidence and append-only manual review history."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_inspections(metadata):
    reports = sa.Table('fp_video_inspections', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('video_checksum', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('technical', JSONB, nullable=False),
        sa.Column('frames', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'id', name='uq_video_inspection_owned'),
        sa.UniqueConstraint('project_id', 'run_id', 'id', name='uq_video_inspection_run_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_video_inspection_request'),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_video_runs.project_id', 'fp_video_runs.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.CheckConstraint("jsonb_typeof(frames) = 'array' AND jsonb_array_length(frames) BETWEEN 1 AND 12", name='ck_video_inspection_frames'))
    sa.Index('ix_video_inspection_run', reports.c.project_id, reports.c.run_id, reports.c.created_at)
    notes = sa.Table('fp_video_inspection_notes', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('inspection_id', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('expected_version', sa.Integer, nullable=False),
        sa.Column('decision', sa.String(16), nullable=False),
        sa.Column('findings', JSONB, nullable=False),
        sa.Column('comment', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_video_inspection_note_request'),
        sa.ForeignKeyConstraint(['project_id', 'run_id', 'inspection_id'],
            ['fp_video_inspections.project_id', 'fp_video_inspections.run_id', 'fp_video_inspections.id']),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_video_runs.project_id', 'fp_video_runs.id']),
        sa.CheckConstraint("decision IN ('reviewed','needs_revision')", name='ck_video_inspection_decision'),
        sa.CheckConstraint('expected_version >= 1', name='ck_video_inspection_note_version'),
        sa.CheckConstraint('length(comment) <= 2000', name='ck_video_inspection_comment'),
        sa.CheckConstraint("jsonb_typeof(findings) = 'array' AND jsonb_array_length(findings) <= 20", name='ck_video_inspection_findings'),
        sa.CheckConstraint("decision <> 'needs_revision' OR jsonb_array_length(findings) > 0", name='ck_video_inspection_revision'))
    sa.Index('ix_video_inspection_notes', notes.c.project_id, notes.c.inspection_id, notes.c.id)
    return {'video_inspections': reports, 'video_inspection_notes': notes}
