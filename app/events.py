"""请求级进度回调，ContextVar 随 LangGraph 的执行上下文传递。"""
from contextvars import ContextVar

progress_sink = ContextVar('progress_sink', default=None)


# 向本次请求的进度接收器发送事件；没有接收器时不发送。
def emit(event, **data):
    sink = progress_sink.get()
    if sink:
        sink({'event': event, 'data': data})
