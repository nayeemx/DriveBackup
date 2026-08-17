from pathlib import Path


def _version_file() -> Path:
    try:
        import sys
        exe_dir = Path(sys.executable).parent
        for f in (exe_dir / "version.txt", exe_dir / "_internal" / "version.txt"):
            if f.exists():
                return f
    except Exception:
        pass
    return Path(__file__).resolve().parents[2] / "version.txt"


def current_version() -> str:
    try:
        return _version_file().read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:
        return "0.0.0"


APP_VERSION = current_version()


def version_key(version: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3) for comparison."""
    parts = []
    for p in str(version).lstrip("vV").split("."):
        num = ""
        for ch in p:
            if ch.isdigit():
                num += ch
            else:
                break
        try:
            parts.append(int(num))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)