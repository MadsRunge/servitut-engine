from queue import Empty, Queue
from typing import Any, Callable, Optional

ProgressCallback = Callable[[dict[str, Any]], None]


def _emit_progress(
    callback: Optional[ProgressCallback],
    *,
    doc_id: str,
    source_type: str,
    stage: str,
    progress: float,
    message: str,
    worker: Optional[str] = None,
    servitut_count: Optional[int] = None,
    **extra: Any,
) -> None:
    if not callback:
        return
    event: dict[str, Any] = {
        "doc_id": doc_id,
        "source_type": source_type,
        "stage": stage,
        "progress": progress,
        "message": message,
        "worker": worker,
        "servitut_count": servitut_count,
    }
    event.update(extra)
    callback(event)


def _drain_progress_queue(
    progress_queue: Optional[Queue],
    progress_callback: Optional[ProgressCallback],
) -> None:
    if not progress_queue or not progress_callback:
        return
    while True:
        try:
            event = progress_queue.get_nowait()
        except Empty:
            break
        progress_callback(event)
