import logging
import sys
from datetime import datetime

from .config import APP_DIR

APP_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = APP_DIR / "app.log"


class ConsoleHandler(logging.Handler):
    def __init__(self, callback=None):
        super().__init__()
        self._callback = callback

    def set_callback(self, callback):
        self._callback = callback

    def emit(self, record):
        msg = self.format(record)
        if self._callback:
            try:
                self._callback(msg, record.levelname)
            except Exception:
                pass
        else:
            print(msg, file=sys.stderr)


_logger = logging.getLogger("drivebackup")
_logger.setLevel(logging.INFO)
_logger.propagate = False

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
)
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_logger.addHandler(_file_handler)

_console = ConsoleHandler()
_console.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_console)


def set_console_callback(callback):
    _console.set_callback(callback)


def get_logger():
    return _logger


def log(line: str, level: str = "INFO"):
    getattr(_logger, level.lower(), _logger.info)(line)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")