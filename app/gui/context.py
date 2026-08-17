from ..engine.rclone_manager import manager
from ..gui.workers import JobHub, start_job
from ..utils.config import Config


class AppContext:
    """Shared state between the UI and background jobs."""

    def __init__(self):
        self.hub = JobHub()
        self.config = Config()
        self.manager = manager
        self.console = None
        self.header_status = None
        self.jobs = {}
        self.after_verify = []

    def start_job(self, job_id, fn, on_progress=None, on_done=None):
        self.jobs[job_id] = {
            "on_progress": on_progress or (lambda p, t: None),
            "on_done": on_done or (lambda r, e: None),
            "running": True,
        }
        self.set_status(f"Working: {job_id} ...")
        start_job(job_id, fn, self.hub)

    def finish_job(self, job_id):
        if job_id in self.jobs:
            self.jobs[job_id]["running"] = False
        self.set_status("Ready")

    def set_status(self, text):
        if self.header_status is not None:
            try:
                self.header_status.set_text(text)
            except Exception:
                pass

    def busy(self):
        return any(j["running"] for j in self.jobs.values())

    def notify_verify_done(self):
        for cb in self.after_verify:
            try:
                cb()
            except Exception:
                pass