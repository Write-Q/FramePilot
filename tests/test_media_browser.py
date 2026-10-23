"""Full browser/API/temporary PostgreSQL flow; only image provider is deterministic."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Event, Thread
import time

import pytest
import uvicorn

from app.main import create_app
from app.production.media_service import MediaService
from app.production.store import ProductionStore
from tests.test_shot_media import Images
from tests.test_story import FakeModel


def test_media_workbench_browser(database_url, tmp_path, monkeypatch):
    node = shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('playwright')"], capture_output=True).returncode:
        pytest.skip('需要 Node.js 和已安装的 Playwright')
    monkeypatch.setenv('FRAMEPILOT_MEDIA_ROOT', str(tmp_path / 'media'))
    app = create_app(database_url=database_url, provider=FakeModel())
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='error'))
    web = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    stopped = Event()
    worker = None
    store = None
    errors = []
    images = Images()
    web.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not web.is_alive() or time.monotonic() >= deadline:
                pytest.fail('媒体浏览器测试服务启动失败')
            time.sleep(.05)
        store = ProductionStore(database_url)
        service = MediaService(store)

        def work():
            try:
                while not stopped.is_set():
                    service.run_once(adapter=images)
                    stopped.wait(.05)
            except Exception as error:
                errors.append(error)

        worker = Thread(target=work, daemon=True)
        worker.start()
        result = subprocess.run([node, '--test', 'tests/storyboard-media-integration.test.cjs'],
            cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ, FRAMEPILOT_UI_URL=f'http://127.0.0.1:{port}'),
            capture_output=True, encoding='utf-8', errors='replace', timeout=120)
        assert not errors, errors
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(images.calls) == 1
    finally:
        stopped.set()
        if worker:
            worker.join(timeout=15)
            assert not worker.is_alive()
        if store:
            store.close()
        server.should_exit = True
        web.join(timeout=15)
        listener.close()
        assert not web.is_alive()
