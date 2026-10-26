"""Run explicitly: python -m scripts.video_worker [--once]. No automatic POST retries."""
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
    import argparse
    from app.production.store import ProductionStore
    from app.production.video_runtime import VideoRuntime
    parser = argparse.ArgumentParser(description='执行已由用户排队的视频任务；可能调用付费供应商')
    parser.add_argument('--once', action='store_true', help='只处理一个可执行任务后退出')
    args = parser.parse_args()
    store = ProductionStore(None)
    try:
        work(VideoRuntime(store), once=args.once)
    finally:
        store.close()
