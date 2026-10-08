"""旧编剧入口持续写入新默认章节，不改原始数据与线程编号。"""
from sqlalchemy import create_engine, text
from app.legacy_domain import domain_id, backfill
from app.storage import Repository


def test_domain_ids_are_stable_and_scoped():
    assert domain_id('p1','chapter') == domain_id('p1','chapter')
    assert domain_id('p1','chapter') != domain_id('p2','chapter')
    assert domain_id('p1','chapter') != domain_id('p1','script')


def test_live_legacy_writes_and_backfill_are_idempotent(database_url):
    state=dict(project_id='bridge-project',original_story='原稿 draft',constraints='一人',draft='第一版',version=1,card={},status='awaiting_confirmation')
    repo=Repository(database_url)
    try:
        repo.create('bridge-project',state,10)
        repo.version(state)
        repo.version(state)
        state={**state,'draft':'第二版', 'version':2}
        repo.version(state)
        repo.save('bridge-project',state,None)
        backfill(database_url)
        backfill(database_url)
        with repo.engine.connect() as conn:
            assert conn.scalar(text("select count(*) from fp_chapters where project_id='bridge-project'"))==1
            assert conn.scalar(text("select count(*) from fp_script_versions where project_id='bridge-project'"))==2
            assert conn.scalar(text("select original_story from fp_chapter_input_versions where project_id='bridge-project'"))=='原稿 draft'
            assert conn.scalar(text("select body from fp_script_versions where project_id='bridge-project' and version_no=2"))=='第二版'
            assert conn.scalar(text("select max_calls from fp_projects where id='bridge-project'"))==10
    finally: repo.close()


def test_bridge_refuses_to_overwrite_original_input(database_url):
    import pytest
    repo=Repository(database_url)
    state=dict(project_id='input-guard',original_story='original',constraints='',draft='original',version=1,card={})
    try:
        repo.create('input-guard',state,10)
        with pytest.raises(ValueError,match='原始输入'):
            repo.save('input-guard',{**state,'original_story':'silently replaced'},None)
        assert repo.get('input-guard')['state']['original_story']=='original'
    finally: repo.close()


def test_concurrent_legacy_save_and_version_use_one_lock_order(database_url):
    from concurrent.futures import ThreadPoolExecutor
    state=dict(project_id='locks',original_story='原稿',constraints='',draft='第一版',version=1,card={})
    repo=Repository(database_url)
    try:
        repo.create('locks',state,10)
        repo.version(state)
        def write(index):
            other=Repository(database_url)
            try:
                if index%2: other.save('locks',state,None)
                else: other.version(state)
            finally: other.close()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(write,range(12)))
        with repo.engine.connect() as conn:
            assert conn.scalar(text("select count(*) from fp_script_versions where project_id='locks'"))==1
    finally: repo.close()


def test_sqlite_import_populates_domain_before_any_resume(database_url,tmp_path):
    from tests.test_sqlite_migration import legacy_fixture
    from scripts.migrate_sqlite import migrate
    source=tmp_path/'legacy-domain'
    legacy_fixture(source)
    migrate(source,database_url)
    engine=create_engine(database_url)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text('select count(*) from fp_script_versions'))==1
            assert conn.scalar(text('select count(*) from fp_project_details'))==1
    finally: engine.dispose()
