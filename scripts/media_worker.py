"""Run explicitly: python -m scripts.media_worker [--once]. Never requeues unknown jobs."""
import argparse
import logging
import time
from app.production.media_service import MediaService
from app.production.store import ProductionStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='process at most one queued image')
    args = parser.parse_args()
    store = ProductionStore(None)
    service = MediaService(store)
    try:
        while True:
            processed = service.run_once()
            if args.once:
                print('Processed one job.' if processed else 'No queued jobs.')
                return
            if not processed:
                time.sleep(2)
    except KeyboardInterrupt:
        logging.warning('Worker stopped. Running jobs remain recorded; reconcile before resubmitting.')
    finally:
        store.close()


if __name__ == '__main__':
    main()
