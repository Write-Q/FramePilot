"""SSE 桥接同步图任务。断开只丢弃实时通知，任务继续保存结果。"""
import json
from queue import Queue, Empty, Full
from threading import Thread, Event
from fastapi.responses import StreamingResponse
from app.events import progress_sink
from app.service import Conflict


def stream_operation(operation):
    queue = Queue(maxsize=256)
    disconnected = Event()
    def send(item):
        while not disconnected.is_set():
            try:
                queue.put(item, timeout=0.2)
                return
            except Full:
                pass
    def worker():
        token = progress_sink.set(send)
        try:
            send({'event':'result', 'data':operation()})
        except KeyError:
            send({'event':'error','data':{'message':'项目不存在'}})
        except Conflict as exc:
            send({'event':'error','data':{'message':str(exc)}})
        except Exception:
            send({'event':'error','data':{'message':'执行异常，请载入项目检查已保存状态。'}})
        finally:
            progress_sink.reset(token)
            send(None)
    def body():
        Thread(target=worker, daemon=True).start()
        try:
            yield ': connected\n\n'
            while True:
                try:
                    item = queue.get(timeout=1)
                except Empty:
                    yield ': heartbeat\n\n'
                    continue
                if item is None:
                    break
                yield 'data: '+json.dumps(item, ensure_ascii=False)+'\n\n'
        finally:
            disconnected.set()
    return StreamingResponse(body(), media_type='text/event-stream',
        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
