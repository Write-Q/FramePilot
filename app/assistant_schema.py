"""Assistant ledger schema. Provider calls never share its transactions."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_assistant(metadata):
    threads = sa.Table('fp_assistant_threads', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), unique=True),
        sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('revision', sa.Integer, nullable=False, server_default='0'),
        sa.Column('active_claim', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('revision >= 0', name='ck_assistant_revision'))
    turns = sa.Table('fp_assistant_turns', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('thread_id', sa.String(64), sa.ForeignKey(threads.c.id), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('claim_id', sa.String(64), nullable=False, unique=True),
        sa.Column('request', JSONB, nullable=False),
        sa.Column('context', JSONB, nullable=False),
        sa.Column('profile', JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reply', sa.Text, nullable=False, server_default=''),
        sa.Column('usage', JSONB, nullable=False, server_default='{}'),
        sa.Column('error', sa.String(200)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('thread_id', 'idempotency_key', name='uq_assistant_turn_request'),
        sa.UniqueConstraint('thread_id', 'id', name='uq_assistant_turn_owned'),
        sa.CheckConstraint("status IN ('running','succeeded','failed','unknown')", name='ck_assistant_turn_status'))
    sa.Index('uq_assistant_active_turn', turns.c.thread_id, unique=True,
             postgresql_where=turns.c.status == 'running')
    proposals = sa.Table('fp_assistant_proposals', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('thread_id', sa.String(64), sa.ForeignKey(threads.c.id), nullable=False),
        sa.Column('turn_id', sa.String(64), nullable=False),
        sa.Column('proposal', JSONB, nullable=False),
        sa.Column('context', JSONB, nullable=False),
        sa.Column('request_context', JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['thread_id', 'turn_id'], [turns.c.thread_id, turns.c.id]),
        sa.UniqueConstraint('thread_id', 'id', name='uq_assistant_proposal_owned'),
        sa.CheckConstraint("status IN ('pending','executing','accepted','rejected','failed','unknown')", name='ck_assistant_proposal_status'))
    executions = sa.Table('fp_assistant_executions', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('thread_id', sa.String(64), sa.ForeignKey(threads.c.id), nullable=False),
        sa.Column('proposal_id', sa.String(64), nullable=False, unique=True),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('request', JSONB, nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reserved_project_id', sa.String(64)),
        sa.Column('result', JSONB),
        sa.Column('error', sa.String(200)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['thread_id', 'proposal_id'], [proposals.c.thread_id, proposals.c.id]),
        sa.UniqueConstraint('thread_id', 'idempotency_key', name='uq_assistant_execution_request'),
        sa.CheckConstraint("status IN ('running','accepted','rejected','failed','unknown')", name='ck_assistant_execution_status'))
    return dict(threads=threads, turns=turns, proposals=proposals, executions=executions)
