import queue
import threading
import traceback
from typing import Any, Callable, Dict, Optional


class JobHub:
    """Thread-safe channel between background jobs and the UI thread."""

    def __init__(self) -> None:
        self.queue: queue.Queue[tuple] = queue.Queue()

    def log(self, level: str, message: str) -> None:
        self.queue.put(("log", level, message))

    def progress(self, pct: float, text: str) -> None:
        self.queue.put(("progress", pct, text))

    def done(self, job: str, result: Any = None, error: Optional[Exception] = None) -> None:
        self.queue.put(("done", job, result, error))

    def ask_auth_url(self, url: str, cancel_event: Optional[threading.Event] = None) -> str:
        self.queue.put(("auth_url", url, cancel_event))
        return url

    def cancel_auth(self) -> None:
        self.queue.put(("cancel_auth",))

    def ask_code(self, cancel_event: Optional[threading.Event] = None) -> Optional[str]:
        event = threading.Event()
        box: Dict[str, Optional[str]] = {}
        self.queue.put(("ask_code", event, box, cancel_event))
        event.wait(timeout=600)
        return box.get("code")


class JobThread(threading.Thread):
    def __init__(self, job_id: str, fn: Callable[..., Any], hub: JobHub) -> None:
        super().__init__(daemon=True)
        self.job_id = job_id
        self.fn = fn
        self.hub = hub
        self.error: Optional[Exception] = None
        self.result: Any = None

    def run(self) -> None:
        try:
            self.result = self.fn(self.hub)
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            self.hub.log("ERROR", f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            self.hub.done(self.job_id, self.result, self.error)


def start_job(job_id: str, fn: Callable[..., Any], hub: JobHub) -> JobThread:
    t = JobThread(job_id, fn, hub)
    t.start()
    return t
