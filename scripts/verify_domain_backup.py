"""在随机临时数据库恢复 Docker 备份并演练升级，绝不修改源业务库。"""
import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from app.database import database_url, checkpoint_conninfo
from scripts.init_db import initialize

LEGACY_TABLES=('fp_projects','fp_versions','fp_calls','checkpoints','checkpoint_blobs','checkpoint_writes')


def fingerprint(url):
    with psycopg.connect(checkpoint_conninfo(url)) as conn:
        result={}
        for table in LEGACY_TABLES:
            query=sql.SQL("SELECT count(*),md5(coalesce(string_agg(t::text,E'\\n' ORDER BY t::text),'')) FROM {} t").format(sql.Identifier(table))
            count,digest=conn.execute(query).fetchone()
            result[table]={'count':count,'md5':digest}
        return result


def verify(backup):
    base=database_url()
    if base.host not in ('127.0.0.1','localhost','::1'):
        raise ValueError('恢复演练仅支持本地 Docker 数据库。')
    name='fp_test_'+uuid4().hex
    url=base.set(database=name).render_as_string(hide_password=False)
    admin=checkpoint_conninfo(base.render_as_string(hide_password=False))
    with psycopg.connect(admin,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with Path(backup).open('rb') as source:
            subprocess.run(['docker','compose','exec','-T','db','sh','-c',
                'pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error','restore',name],stdin=source,check=True)
        before=fingerprint(url)
        initialize(url)
        after=fingerprint(url)
        if before!=after: raise AssertionError('升级改变了原业务或检查点内容')
        with psycopg.connect(checkpoint_conninfo(url)) as conn:
            projects=conn.execute('SELECT count(*) FROM fp_project_details').fetchone()[0]
            versions=conn.execute('SELECT count(*) FROM fp_script_versions').fetchone()[0]
            assert projects==before['fp_projects']['count']
            assert versions==before['fp_versions']['count']
        return {'restored':True,'legacy_unchanged':True,'projects':projects,'versions':versions}
    finally:
        assert name.startswith('fp_test_') and len(name)==40
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.backup)))
