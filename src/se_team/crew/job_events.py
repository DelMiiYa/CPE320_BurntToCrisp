"""Optional per-job events and cancellation, shared with the local Office."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event
from typing import Callable


class JobCancelled(RuntimeError):
    pass


@dataclass
class JobContext:
    callback: Callable[[str, dict], None]
    cancelled: Event


current_job: ContextVar[JobContext | None] = ContextVar('current_job', default=None)


def emit(kind: str, **data):
    context = current_job.get()
    if context:
        context.callback(kind, data)


def check_cancelled():
    context = current_job.get()
    if context and context.cancelled.is_set():
        raise JobCancelled('งานถูกหยุดตามคำขอ ไฟล์เวอร์ชันก่อนหน้ายังอยู่')


@contextmanager
def bind_job(callback, cancelled):
    token = current_job.set(JobContext(callback, cancelled))
    try:
        check_cancelled()
        yield
    finally:
        current_job.reset(token)
