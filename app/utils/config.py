import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "DriveBackup"
STATE_DIR = APP_DIR / "state"
REPORT_DIR = APP_DIR / "reports"
CONFIG_FILE = APP_DIR / "config.json"

DEFAULTS = {
    "remote": "gdrive",
    "transfers": 4,
    "checkers": 8,
    "gemini_api_key": "",
    "ai_provider": "gemini",
    "ai_model": "",
    "export_formats": "docx,xlsx,pptx,csv,txt,rtf,pdf,png",
    "verify_freshness_hours": 24,
    "theme": "dark",
    "github_owner": "",
    "github_repo": "",
    "auto_update": "prompt",
}

STATE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    def __init__(self):
        self._data = {}
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                self._data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}
        for key, value in DEFAULTS.items():
            self._data.setdefault(key, value)

    def save(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    def get(self, key, default=None):
        return self._data.get(key, DEFAULTS.get(key) if default is None else default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def to_dict(self):
        return dict(self._data)


def state_path(name: str) -> Path:
    return STATE_DIR / name


def report_path(name: str) -> Path:
    return REPORT_DIR / name


def format_bytes(num: float) -> str:
    if num is None:
        return "?"
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} PB"