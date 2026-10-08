from pathlib import Path
from app.models import Base


def test_normalized_domain_registered_without_replacing_legacy():
    required = {'fp_chapters', 'fp_scripts', 'fp_script_versions', 'fp_assets',
                'fp_asset_versions', 'fp_generation_tasks', 'fp_shots', 'fp_media_files'}
    assert required <= set(Base.metadata.tables)
    assert {'fp_projects', 'fp_versions', 'fp_calls'} <= set(Base.metadata.tables)


def test_migration_is_frozen():
    source = Path('migrations/versions/0002_domain_foundation.py').read_text(encoding='utf-8')
    assert 'from app.' not in source
    assert 'import app.' not in source


def test_version_ownership_constraints():
    table = Base.metadata.tables['fp_script_versions']
    assert any(list(c.column_keys) == ['project_id', 'script_id', 'parent_version_id']
               for c in table.foreign_key_constraints)
    table = Base.metadata.tables['fp_script_asset_refs']
    assert any(list(c.column_keys) == ['project_id', 'asset_id', 'asset_version_id']
               for c in table.foreign_key_constraints)

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone


@pytest.fixture
def domain_db(database_url):
    engine = sa.create_engine(database_url)
    with engine.begin() as conn:
        for project in ('p', 'q'):
            conn.execute(Base.metadata.tables['fp_projects'].insert().values(
                id=project, snapshot={}, max_calls=10, created_at=datetime.now(timezone.utc)))
        for identity, project, position in [('c1', 'p', 1), ('c2', 'p', 2), ('cq', 'q', 1)]:
            conn.execute(Base.metadata.tables['fp_chapters'].insert().values(id=identity, project_id=project, title=identity, position=position))
        for identity, chapter in [('s1', 'c1'), ('s2', 'c2')]:
            conn.execute(Base.metadata.tables['fp_scripts'].insert().values(id=identity, project_id='p', chapter_id=chapter))
            conn.execute(Base.metadata.tables['fp_script_versions'].insert().values(id=identity+'v1', project_id='p', chapter_id=chapter, script_id=identity, version_no=1, body='original'))
        conn.execute(Base.metadata.tables['fp_assets'].insert().values(id='a',project_id='p',asset_type='character',scope_chapter_id='c1',display_name='Name'))
        conn.execute(Base.metadata.tables['fp_asset_versions'].insert().values(id='av1',project_id='p',asset_id='a',version_no=1))
    yield engine
    engine.dispose()


def rejected(engine, statement):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(statement)


def test_cross_project_and_version_owner_rejected(domain_db):
    tables = Base.metadata.tables
    rejected(domain_db, tables['fp_chapter_asset_links'].insert().values(id='bad1',project_id='q',chapter_id='cq',asset_id='a'))
    rejected(domain_db, tables['fp_scripts'].update().where(tables['fp_scripts'].c.id=='s2').values(current_version_id='s1v1'))
    rejected(domain_db, tables['fp_script_versions'].insert().values(id='bad2',project_id='p',chapter_id='c2',script_id='s2',version_no=2,parent_version_id='s1v1',body='wrong owner'))
    rejected(domain_db, tables['fp_script_versions'].insert().values(id='bad3',project_id='p',chapter_id='c1',script_id='s1',version_no=3,parent_version_id='s1v1',body='gap'))


def test_chapter_scope_and_scope_narrowing_rejected(domain_db):
    tables = Base.metadata.tables
    links=tables['fp_chapter_asset_links']
    assets=tables['fp_assets']
    rejected(domain_db, links.insert().values(id='wrong',project_id='p',chapter_id='c2',asset_id='a',selected_version_id='av1'))
    with domain_db.begin() as conn:
        conn.execute(assets.update().where(assets.c.id=='a').values(scope_chapter_id=None))
        conn.execute(links.insert().values(id='ok',project_id='p',chapter_id='c2',asset_id='a',selected_version_id='av1'))
    rejected(domain_db, assets.update().where(assets.c.id=='a').values(scope_chapter_id='c1'))


def test_frozen_reference_requires_approval_and_history_is_immutable(domain_db):
    tables=Base.metadata.tables
    refs=tables['fp_script_asset_refs']
    stmt=refs.insert().values(id='ref',project_id='p',chapter_id='c1',script_version_id='s1v1',asset_id='a',asset_version_id='av1')
    rejected(domain_db, stmt)
    with domain_db.begin() as conn:
        conn.execute(tables['fp_asset_version_decisions'].insert().values(id='decision',project_id='p',asset_version_id='av1',decision='approved'))
        conn.execute(stmt)
        conn.execute(tables['fp_asset_versions'].insert().values(id='av2',project_id='p',asset_id='a',version_no=2,definition={'new':True}))
    for name in ['fp_script_versions', 'fp_asset_versions', 'fp_script_asset_refs', 'fp_asset_version_decisions']:
        rejected(domain_db, tables[name].delete())
    versions=tables['fp_script_versions']
    rejected(domain_db,versions.update().values(body='overwritten'))
    with domain_db.connect() as conn:
        assert conn.execute(sa.select(refs.c.asset_version_id)).scalar_one()=='av1'


def test_migration_roundtrip_preserves_legacy_and_matches_metadata(database_url):
    from alembic.config import Config
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    engine=sa.create_engine(database_url)
    with engine.connect() as conn:
        differences=compare_metadata(MigrationContext.configure(conn, opts={'include_name': lambda name, kind, parents: kind != 'table' or name.startswith('fp_')}),Base.metadata)
        assert differences == []
    config=Config('alembic.ini')
    config.attributes['database_url']=database_url
    command.downgrade(config,'0001_postgres')
    with engine.connect() as conn:
        assert {'fp_projects','fp_versions','fp_calls'} <= set(sa.inspect(conn).get_table_names())
        assert 'fp_chapters' not in sa.inspect(conn).get_table_names()
    command.upgrade(config,'0002_domain_foundation')
    engine.dispose()


def test_execution_sources_cannot_cross_chapters_or_be_rewritten(domain_db):
    tables=Base.metadata.tables
    tasks=tables['fp_generation_tasks']
    with domain_db.begin() as conn:
        conn.execute(tables['fp_revision_requests'].insert().values(id='req', project_id='p', script_id='s1',base_version_id='s1v1',action='revise',idempotency_key='key'))
        conn.execute(tasks.insert().values(id='task',project_id='p',chapter_id='c1',request_id='req',workflow_version='v1'))
    rejected(domain_db,tasks.insert().values(id='wrong-task',project_id='p',chapter_id='c2',request_id='req',workflow_version='v1'))
    rejected(domain_db,tasks.update().where(tasks.c.id=='task').values(input_manifest={'changed': True}))
    rejected(domain_db,tables['fp_review_runs'].insert().values(id='wrong-review',project_id='p',script_version_id='s2v1',task_id='task',rubric_version='v1'))


def test_approval_order_is_append_order_even_when_timestamps_tie(domain_db):
    tables=Base.metadata.tables
    decisions=tables['fp_asset_version_decisions']
    with domain_db.begin() as conn:
        for identity,decision in [('z-approved','approved'),('a-revoked','revoked')]:
            conn.execute(decisions.insert().values(id=identity,project_id='p',asset_version_id='av1',decision=decision))
    rejected(domain_db,tables['fp_script_asset_refs'].insert().values(id='bad',project_id='p',chapter_id='c1',script_version_id='s1v1',asset_id='a',asset_version_id='av1'))


def test_nonempty_domain_downgrade_refused(domain_db, database_url):
    from alembic.config import Config
    from alembic import command
    config=Config('alembic.ini')
    config.attributes['database_url']=database_url
    with pytest.raises(RuntimeError,match='nonempty'):
        command.downgrade(config,'0001_postgres')


def test_production_references_have_explicit_relational_tables():
    assert {'fp_scene_asset_refs','fp_shot_asset_refs','fp_task_media_links','fp_task_shot_links'} <= set(Base.metadata.tables)


def test_scene_shot_and_generation_sources_are_owned(domain_db):
    tables=Base.metadata.tables
    with domain_db.begin() as conn:
        conn.execute(tables['fp_breakdown_versions'].insert().values(id='b2',project_id='p',script_version_id='s2v1',version_no=1))
        conn.execute(tables['fp_scenes'].insert().values(id='scene2',project_id='p',breakdown_version_id='b2',position=1,title='Scene'))
        conn.execute(tables['fp_storyboard_versions'].insert().values(id='board2',project_id='p',breakdown_version_id='b2',version_no=1))
        conn.execute(tables['fp_shots'].insert().values(id='shot2',project_id='p',breakdown_version_id='b2',storyboard_version_id='board2',scene_id='scene2',position=1))
        conn.execute(tables['fp_asset_version_decisions'].insert().values(id='approved',project_id='p',asset_version_id='av1',decision='approved'))
        conn.execute(tables['fp_generation_tasks'].insert().values(id='task1',project_id='p',chapter_id='c1',workflow_version='v1'))
    rejected(domain_db,tables['fp_scene_asset_refs'].insert().values(id='bad-scene',project_id='p',scene_id='scene2',asset_id='a',asset_version_id='av1'))
    rejected(domain_db,tables['fp_shot_asset_refs'].insert().values(id='bad-shot',project_id='p',shot_id='shot2',asset_id='a',asset_version_id='av1'))
    rejected(domain_db,tables['fp_task_shot_links'].insert().values(id='bad-target',project_id='p',task_id='task1',shot_id='shot2'))
    with domain_db.begin() as conn:
        conn.execute(tables['fp_assets'].update().where(tables['fp_assets'].c.id=='a').values(scope_chapter_id=None))
        conn.execute(tables['fp_scene_asset_refs'].insert().values(id='good-scene',project_id='p',scene_id='scene2',asset_id='a',asset_version_id='av1'))
        conn.execute(tables['fp_shot_asset_refs'].insert().values(id='good-shot',project_id='p',shot_id='shot2',asset_id='a',asset_version_id='av1'))
    rejected(domain_db,tables['fp_assets'].update().where(tables['fp_assets'].c.id=='a').values(scope_chapter_id='c1'))
