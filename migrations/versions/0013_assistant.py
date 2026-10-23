"""Frozen assistant conversation and explicit execution ledgers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0013_assistant'
down_revision = '0012_local_clips'
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(bind=op.get_bind())
    tables = _frozen_tables(metadata)
    for table in tables.values():
        table.create(op.get_bind())
    op.execute("""
    CREATE FUNCTION fp_assistant_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'assistant ledger cannot be deleted';
      END IF;
      IF TG_TABLE_NAME = 'fp_assistant_threads' THEN
        IF (OLD.project_id IS NOT NULL AND NEW.project_id IS DISTINCT FROM OLD.project_id)
          OR NEW.id IS DISTINCT FROM OLD.id OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
          OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256 OR NEW.created_at IS DISTINCT FROM OLD.created_at
          OR NEW.revision < OLD.revision OR NEW.revision > OLD.revision + 1 THEN
          RAISE EXCEPTION 'assistant thread identity is immutable';
        END IF;
      ELSIF TG_TABLE_NAME = 'fp_assistant_turns' THEN
        IF OLD.status <> 'running' OR
          (to_jsonb(NEW) - ARRAY['status','reply','usage','error']) IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status','reply','usage','error']) THEN
          RAISE EXCEPTION 'assistant terminal turn is immutable';
        END IF;
      ELSIF TG_TABLE_NAME = 'fp_assistant_proposals' THEN
        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
          OR NOT ((OLD.status = 'pending' AND NEW.status IN ('executing','rejected'))
            OR (OLD.status = 'executing' AND NEW.status IN ('accepted','failed','unknown'))) THEN
          RAISE EXCEPTION 'assistant proposal history is immutable';
        END IF;
      ELSIF TG_TABLE_NAME = 'fp_assistant_executions' THEN
        IF OLD.status <> 'running' OR NEW.status = 'running' OR
          (to_jsonb(NEW) - ARRAY['status','result','error']) IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status','result','error']) THEN
          RAISE EXCEPTION 'assistant terminal execution is immutable';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER assistant_guard BEFORE UPDATE OR DELETE ON fp_assistant_threads
      FOR EACH ROW EXECUTE FUNCTION fp_assistant_guard();
    CREATE TRIGGER assistant_guard BEFORE UPDATE OR DELETE ON fp_assistant_turns
      FOR EACH ROW EXECUTE FUNCTION fp_assistant_guard();
    CREATE TRIGGER assistant_guard BEFORE UPDATE OR DELETE ON fp_assistant_proposals
      FOR EACH ROW EXECUTE FUNCTION fp_assistant_guard();
    CREATE TRIGGER assistant_guard BEFORE UPDATE OR DELETE ON fp_assistant_executions
      FOR EACH ROW EXECUTE FUNCTION fp_assistant_guard();
    """)


def downgrade():
    for name in ('fp_assistant_executions', 'fp_assistant_proposals', 'fp_assistant_turns', 'fp_assistant_threads'):
        if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM ' + name + ')')).scalar():
            raise RuntimeError('Assistant history is not empty; forward migration required.')
    for name in ('fp_assistant_executions', 'fp_assistant_proposals', 'fp_assistant_turns', 'fp_assistant_threads'):
        op.drop_table(name)
    op.execute('DROP FUNCTION fp_assistant_guard()')


def _frozen_tables(metadata):
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
