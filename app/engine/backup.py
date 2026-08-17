import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .rclone_manager import RcloneError, manager
from ..utils.config import format_bytes, state_path
from ..utils.logging_utils import get_logger, now_iso

LOG = get_logger()

STATS_RE = re.compile(
    r"Transferred:\s+([\d.]+)\s*/\s*([\d.]+)\s+([A-Za-z]+),\s+([\d.]+)%"
)
RATE_RE = re.compile(r"(\d+)\s+files?,\s+([\d.]+)\s+([A-Za-z]+)")


def md5_of_file(path: Path, chunk=1024 * 1024):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _walk_local(local_dir: Path, workers: int = 8):
    files = [p for p in local_dir.rglob("*") if p.is_file()]
    result = {}

    def one(path: Path):
        try:
            size = path.stat().st_size
            md5 = md5_of_file(path)
            return str(path.relative_to(local_dir)).replace("\\", "/"), {
                "size": size, "md5": md5,
            }
        except OSError as exc:
            return str(path.relative_to(local_dir)).replace("\\", "/"), {
                "size": -1, "md5": None, "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rel, meta in pool.map(one, files):
            result[rel] = meta
    return result


def load_inventory() -> list:
    path = state_path("inventory.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_manifest() -> dict:
    path = state_path("manifest.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_verify_result() -> dict:
    path = state_path("verify_result.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_manifest() -> list:
    data = load_manifest()
    return data.get("files", [])


EXPORT_EXTS = {
    "application/vnd.google-apps.document": "docx",
    "application/vnd.google-apps.spreadsheet": "xlsx",
    "application/vnd.google-apps.presentation": "pptx",
    "application/vnd.google-apps.drawing": "png",
    "application/vnd.google-apps.script": "json",
    "application/vnd.google-apps.form": "csv",
    "application/vnd.google-apps.fusiontable": "csv",
    "application/vnd.google-apps.jam": "pdf",
    "application/vnd.google-apps.map": "json",
    "application/vnd.google-apps.site": "txt",
    "application/vnd.google-apps.unknown": "txt",
}


def _drive_md5(item):
    hashes = item.get("Hashes") or {}
    return hashes.get("MD5") or hashes.get("md5")


def is_exported(mime: str) -> bool:
    return bool(mime) and mime.startswith("application/vnd.google-apps")


def _match_folders(path: str, prefixes):
    """True if `path` is inside any of the given folder prefixes.

    Prefixes are drive folder names or paths like "Documents" or
    "Photos/2026". Matching is exact-folder aware ("Docs" does not match
    "Documents").
    """
    for prefix in prefixes:
        p = prefix.strip("/")
        if not p:
            continue
        if path == p or path.startswith(p + "/"):
            return True
    return False


def _scope_filters(include_folders=None, exclude_folders=None):
    """rclone filter args that restrict a copy to the chosen folders.

    include-mode: --include "/<folder>/**" for each folder + --exclude "*"
    (only these folders). exclude-mode: --exclude "/<folder>/**" for each
    folder (everything else).
    """
    args = []
    includes = [f.strip("/") for f in (include_folders or []) if f.strip()]
    excludes = [f.strip("/") for f in (exclude_folders or []) if f.strip()]
    for folder in includes:
        args += ["--include", f"/{folder}/**"]
    if includes:
        args += ["--exclude", "*"]
    for folder in excludes:
        args += ["--exclude", f"/{folder}/**"]
    return args


def backup(remote: str, local_dir, transfers=4, checkers=8,
           line_cb=LOG.info, progress_cb=None, root="",
           include_folders=None, exclude_folders=None):
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    if any(local_dir.iterdir()):
        raise RcloneError(
            f"Backup folder is not empty: {local_dir}\n"
            "Choose an empty folder to keep the backup clean."
        )

    if progress_cb:
        progress_cb(0, "Listing Drive contents ...")
    inventory = manager.lsjson(remote, root=root)
    LOG.info(f"Drive inventory: {len(inventory)} files, "
             f"{format_bytes(sum(f.get('Size', 0) for f in inventory))} total")
    if not inventory:
        raise RcloneError("Your Drive appears to be empty - nothing to back up.")

    includes = [f.strip("/") for f in (include_folders or []) if f.strip()]
    excludes = [f.strip("/") for f in (exclude_folders or []) if f.strip()]
    if includes or excludes:
        def in_scope(item):
            path = item.get("Path") or item.get("Name") or ""
            if includes and not _match_folders(path, includes):
                return False
            if excludes and _match_folders(path, excludes):
                return False
            return True
        before = len(inventory)
        inventory = [f for f in inventory if in_scope(f)]
        LOG.info(f"Folder scope kept {len(inventory)} of {before} files")
        if not inventory:
            raise RcloneError(
                "No files match your selected folders. Check the folder "
                "names (they are case-sensitive) and try again.")
    state_path("inventory.json").write_text(
        json.dumps(inventory, indent=1), encoding="utf-8")

    if progress_cb:
        progress_cb(1, "Downloading files ...")
    total = sum(f.get("Size", 0) for f in inventory) or 1
    copied = 0

    def on_line(line):
        m = STATS_RE.search(line)
        if m:
            try:
                done = float(m.group(1))
                total_done = float(m.group(2))
                pct = float(m.group(4))
                if progress_cb:
                    progress_cb(pct / 100.0,
                                f"Downloading ... {done:.0f} of {total_done:.0f} {m.group(3)} ({pct:.1f}%)")
            except ValueError:
                pass
        line_cb(line)

    filters = _scope_filters(includes, excludes)
    manager.copy(remote, local_dir, transfers, checkers, on_line, root=root,
                 extra_args=filters)

    if progress_cb:
        progress_cb(0.95, "Computing local checksums ...")
    local = _walk_local(local_dir)
    LOG.info(f"Local files after copy: {len(local)}")

    files = []
    for item in inventory:
        path = item.get("Path") or item.get("Name")
        size = item.get("Size", 0)
        md5 = _drive_md5(item)
        mime = item.get("MimeType", "")
        exported = is_exported(mime)
        local_meta = None
        if exported:
            stem = os.path.splitext(path)[0]
            ext = EXPORT_EXTS.get(mime, "docx")
            cand = f"{stem}.{ext}"
            for local_path in local:
                if local_path == cand or local_path == path:
                    local_meta = local[local_path]
                    break
        else:
            local_meta = local.get(path)
        files.append({
            "path": path,
            "size": size,
            "md5": md5,
            "modtime": item.get("ModTime", ""),
            "mime": mime,
            "exported": exported,
            "local": local_meta,
        })

    manifest = {
        "created": now_iso(),
        "remote": remote,
        "local_dir": str(local_dir),
        "files": files,
    }
    state_path("manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")

    ok = sum(1 for f in files if f["local"])
    missing = len(files) - ok
    LOG.info(f"Backup manifest: {ok} files present locally, {missing} missing")
    return {
        "files": len(files),
        "bytes": sum(f["size"] for f in files),
        "local_files": len(local),
        "ok": ok,
        "missing": missing,
        "manifest": str(state_path("manifest.json")),
    }