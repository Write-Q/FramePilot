"""Explicit local FFmpeg worker: python -m scripts.editing_worker [--once]."""
import argparse
import time

from app.production.editing_service import EditingService
from app.production.store import ProductionStore


def main():
    parser = argparse.ArgumentParser(description='处理本地成片导出队列，不调用模型API')
    parser.add_argument('--once', action='store_true', help='最多处理一个任务后退出')
    args = parser.parse_args()
    store = ProductionStore()
    try:
        service = EditingService(store)
        while True:
            processed = service.run_once()
            if args.once:
                return
            if not processed:
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


if __name__ == '__main__':
    main()
