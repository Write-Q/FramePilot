"""SSE 桥接同步图任务。断开只丢弃实时通知，任务继续保存结果。"""
import json
from queue import Queue, Empty, Full
from threading import Thread, Event
from fastapi.responses import StreamingResponse
from app.events import progress_sink
from app.service import Conflict


# 把同步业务操作桥接成 SSE HTTP 响应；事件预览不是最终校验结果。
def stream_operation(operation):
    queue = Queue(maxsize=256)
    disconnected = Event()
    # 向有界队列投递事件；浏览器断开后停止通知，但不会取消业务操作。
    def send(item):
        while not disconnected.is_set():
            try:
                queue.put(item, timeout=0.2)
                return
            except Full:
                pass
    # 后台线程执行业务操作，并把结果或错误写入事件队列。
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
    # HTTP 响应生成器：读取事件、发送心跳，并标记连接结束。
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
