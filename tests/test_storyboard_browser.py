"""真实浏览器与临时 PostgreSQL；只注入确定性规划器，不调用付费模型。"""
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
from tests.test_story import FakeModel
from tests.test_storyboard_generation import Planner
from tests.test_storyboard_reviews import Reviewer


def test_storyboard_workbench_browser(database_url):
    node = shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('playwright')"], capture_output=True).returncode:
        pytest.skip('需要 Node.js 和已安装的 Playwright')
    app = create_app(database_url=database_url, provider=FakeModel(), storyboard_provider=Planner(), review_provider=Reviewer())
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
                pytest.fail('分镜测试服务启动失败')
            time.sleep(.05)
        result = subprocess.run([node, '--test', '--experimental-test-isolation=none', 'tests/storyboard-ux.test.cjs', 'tests/storyboard-review-ux.test.cjs'],
            cwd=Path(__file__).resolve().parents[1], env=dict(os.environ, FRAMEPILOT_UI_URL=f'http://127.0.0.1:{port}'),
            capture_output=True, encoding='utf-8', errors='replace', timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive()
