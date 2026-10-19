"""Optional real-browser regression: PostgreSQL fixture + deterministic model, no paid calls."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Thread
import time

import pytest
import uvicorn

from app.main import create_app
from tests.test_story import FakeModel, issue


def test_writer_editor_browser(database_url):
    node = shutil.which('node')
    if not node:
        pytest.skip('浏览器回归需要 Node.js 和 playwright 包')
    available = subprocess.run([node, '-e', "require.resolve('playwright')"], capture_output=True)
    if available.returncode:
        pytest.skip('浏览器回归需要 playwright 包，可通过 NODE_PATH 指定已安装目录')
    app = create_app(database_url=database_url, provider=FakeModel([[issue(needs_user=True)]]))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='error'))
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                pytest.fail('浏览器测试服务未能启动')
            time.sleep(0.05)
        environment = dict(os.environ, FRAMEPILOT_UI_URL=f'http://127.0.0.1:{port}')
        result = subprocess.run(
            [node, '--test', '--experimental-test-isolation=none', 'tests/writer-ux.test.cjs'],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, encoding='utf-8', errors='replace', timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), '测试服务未停止，不能清理其测试数据库'
