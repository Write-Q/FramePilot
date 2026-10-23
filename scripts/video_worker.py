"""Embedding entrypoint for hosts with explicit video adapters and a validated sink."""
import time


def work(runtime, *, once=False, stop=None):
    """A concrete host passes VideoRuntime; no vendor protocol is inferred here."""
    if not runtime.adapters:
        raise ValueError('尚未注册视频供应商适配器，不能启动外部视频任务')
    while stop is None or not stop.is_set():
        processed = runtime.run_once()
        if once:
            return processed
        if not processed:
            if stop is not None:
                stop.wait(2)
            else:
                time.sleep(2)


if __name__ == '__main__':
    raise SystemExit('视频供应商尚未选定。请在宿主注册适配器和媒体验证存储后调用work(runtime)。')
