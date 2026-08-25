import json
import os
from pathlib import Path
from typing import Any, Callable, Optional, Union

APP_DIR: Path = Path(os.environ.get("APPDATA", str(Path.home()))) / "DriveBackup"
STATE_DIR: Path = APP_DIR / "state"
REPORT_DIR: Path = APP_DIR / "reports"
CONFIG_FILE: Path = APP_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "active_service": "drive",
    "remote_drive": "gdrive",
    "remote_photos": "gphotos",
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
    "gphotos_proxy": "",
}

STATE_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    _VALIDATORS: dict[str, Callable[[Any], Any]] = {
        "transfers": lambda v: max(1, min(16, int(v))),
        "checkers": lambda v: max(1, min(32, int(v))),
        "verify_freshness_hours": lambda v: max(1, min(720, int(v))),
        "auto_update": lambda v: v if v in ("prompt", "silent", "off") else "prompt",
        "active_service": lambda v: v if v in ("drive", "photos") else "drive",
        "ai_provider": lambda v: v if v in ("gemini", "openrouter") else "gemini",
    }

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if CONFIG_FILE.exists():
            try:
                self._data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        for key, value in DEFAULTS.items():
            self._data.setdefault(key, value)

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key) if default is None else default)

    def set(self, key: str, value: Any) -> None:
        validator = self._VALIDATORS.get(key)
        if validator:
            try:
                value = validator(value)
            except (TypeError, ValueError):
                pass
        self._data[key] = value
        self.save()

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    @property
    def active_remote(self) -> str:
        service = self.get("active_service", "drive")
        return self.get(f"remote_{service}")


def state_path(name: str) -> Path:
    return STATE_DIR / name


def report_path(name: str) -> Path:
    return REPORT_DIR / name


def format_bytes(num: Union[float, int, None]) -> str:
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
