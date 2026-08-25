from typing import Any, Callable, Dict, List, Optional

from ..engine.rclone_manager import manager
from ..gui.workers import JobHub, start_job
from ..utils.config import Config


class AppContext:
    """Shared state between the UI and background jobs."""

    def __init__(self) -> None:
        self.hub: JobHub = JobHub()
        self.config: Config = Config()
        self.manager = manager
        self.console: Optional[Any] = None
        self.header_status: Optional[Any] = None
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.after_verify: List[Callable[[], None]] = []

    def start_job(self, job_id: str, fn: Callable[..., Any],
                  on_progress: Optional[Callable[[float, str], None]] = None,
                  on_done: Optional[Callable[[Any, Optional[Exception]], None]] = None) -> None:
        self.jobs[job_id] = {
            "on_progress": on_progress or (lambda p, t: None),
            "on_done": on_done or (lambda r, e: None),
            "running": True,
        }
        self.set_status(f"Working: {job_id} ...")
        start_job(job_id, fn, self.hub)

    def finish_job(self, job_id: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id]["running"] = False
        self.set_status("Ready")

    def set_status(self, text: str) -> None:
        if self.header_status is not None:
            try:
                self.header_status.set_text(text)
            except (AttributeError, ValueError):
                pass

    def busy(self) -> bool:
        return any(j["running"] for j in self.jobs.values())

    def notify_verify_done(self) -> None:
        for cb in self.after_verify:
            try:
                cb()
            except (RuntimeError, ValueError):
                pass
