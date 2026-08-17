import queue
import threading
import traceback


class JobHub:
    """Thread-safe channel between background jobs and the UI thread."""

    def __init__(self):
        self.queue = queue.Queue()

    def log(self, level, message):
        self.queue.put(("log", level, message))

    def progress(self, pct, text):
        self.queue.put(("progress", pct, text))

    def done(self, job, result=None, error=None):
        self.queue.put(("done", job, result, error))

    def ask_auth_url(self, url):
        self.queue.put(("auth_url", url))
        return url

    def ask_code(self):
        event = threading.Event()
        box = {}
        self.queue.put(("ask_code", event, box))
        event.wait(timeout=600)
        return box.get("code")


class JobThread(threading.Thread):
    def __init__(self, job_id, fn, hub):
        super().__init__(daemon=True)
        self.job_id = job_id
        self.fn = fn
        self.hub = hub
        self.error = None
        self.result = None

    def run(self):
        try:
            self.result = self.fn(self.hub)
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            self.hub.log("ERROR", f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        finally:
            self.hub.done(self.job_id, self.result, self.error)


def start_job(job_id, fn, hub):
    t = JobThread(job_id, fn, hub)
    t.start()
    return t