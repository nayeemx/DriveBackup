import hashlib
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .rclone_manager import RcloneError, manager
from ..utils.config import format_bytes, state_path
from ..utils.logging_utils import get_logger, now_iso

LOG = get_logger()

STATS_RE: re.Pattern[str] = re.compile(
    r"Transferred:\s+([\d.]+)\s*/\s*([\d.]+)\s+([A-Za-z]+),\s+([\d.]+)%"
)
RATE_RE: re.Pattern[str] = re.compile(r"(\d+)\s+files?,\s+([\d.]+)\s+([A-Za-z]+)")


def md5_of_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _walk_local(local_dir: Path, workers: int = 8) -> Dict[str, Any]:
    files = [p for p in local_dir.rglob("*") if p.is_file()]
    result: Dict[str, Any] = {}

    def one(path: Path) -> tuple[str, dict[str, Any]]:
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


def load_inventory() -> List[dict[str, Any]]:
    path = state_path("inventory.json")
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def load_manifest() -> dict[str, Any]:
    path = state_path("manifest.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_verify_result() -> dict[str, Any]:
    path = state_path("verify_result.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_manifest() -> List[dict[str, Any]]:
    data = load_manifest()
    return data.get("files", [])


EXPORT_EXTS: Dict[str, str] = {
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


def _drive_md5(item: dict[str, Any]) -> Optional[str]:
    hashes = item.get("Hashes") or {}
    return hashes.get("MD5") or hashes.get("md5")


def is_exported(mime: str) -> bool:
    return bool(mime) and mime.startswith("application/vnd.google-apps")


def _match_folders(path: str, prefixes: List[str]) -> bool:
    for prefix in prefixes:
        p = prefix.strip("/")
        if not p:
            continue
        if path == p or path.startswith(p + "/"):
            return True
    return False


def _scope_filters(include_folders: Optional[List[str]] = None,
                   exclude_folders: Optional[List[str]] = None,
                   include_files: Optional[List[str]] = None,
                   tmp_list_path: Optional[str] = None) -> List[str]:
    args: List[str] = []
    if include_files:
        if not tmp_list_path:
            raise ValueError("include_files needs a temp list file")
        args += ["--files-from-raw", tmp_list_path]
        return args
    includes = [f.strip("/") for f in (include_folders or []) if f.strip()]
    excludes = [f.strip("/") for f in (exclude_folders or []) if f.strip()]
    for folder in includes:
        args += ["--include", f"/{folder}/**"]
    if includes:
        args += ["--exclude", "*"]
    for folder in excludes:
        args += ["--exclude", f"/{folder}/**"]
    return args


def _write_files_list(files: List[str], tmp_dir: Path) -> str:
    fd, path = tempfile.mkstemp(suffix=".txt", dir=str(tmp_dir))
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        for p in files:
            fh.write(str(p).replace("\\", "/") + "\n")
    return path


def _scan_inventory(inventory: List[dict[str, Any]]) -> tuple[List[dict], List[dict], List[str]]:
    """Categorize files into safe-to-download and problematic.

    Returns (safe_files, problematic_files, warnings).
    """
    WIN_ILLEGAL = set(':*?"<>|')
    safe = []
    problematic = []
    warnings = []

    path_count: Dict[str, int] = {}
    for item in inventory:
        path = item.get("Path") or item.get("Name") or ""
        path_count[path] = path_count.get(path, 0) + 1

    for item in inventory:
        path = item.get("Path") or item.get("Name") or ""
        parts = path.split("/")
        reasons = []
        for part in parts:
            for ch in WIN_ILLEGAL:
                if ch in part:
                    reasons.append(f"illegal char '{ch}' in '{part}'")
                    break
        if path_count.get(path, 0) > 1:
            reasons.append("duplicate path")
        if reasons:
            item["_skip_reason"] = "; ".join(reasons)
            problematic.append(item)
        else:
            safe.append(item)

    if problematic:
        warnings.append(
            f"{len(problematic)} file(s) need special handling "
            f"({len(safe)} safe to download first)")
    return safe, problematic, warnings


def backup(remote: str, local_dir: Union[str, Path], transfers: int = 4,
           checkers: int = 8,
           line_cb: Callable[[str], None] = LOG.info,
           progress_cb: Optional[Callable[[float, str], None]] = None,
           root: str = "",
           include_folders: Optional[List[str]] = None,
           exclude_folders: Optional[List[str]] = None,
           include_files: Optional[List[str]] = None,
           gphotos_proxy: str = "") -> dict[str, Any]:
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    resuming = False
    if any(local_dir.iterdir()):
        resuming = True
        inv_path = state_path("inventory.json")
        LOG.info(f"Resuming backup into non-empty folder: {local_dir} "
                 f"(inventory: {'yes' if inv_path.exists() else 'no'})")

    if progress_cb:
        progress_cb(0, "Listing Drive contents ...")
    inventory = manager.lsjson(remote, root=root)
    LOG.info(f"Drive inventory: {len(inventory)} files, "
             f"{format_bytes(sum(f.get('Size', 0) for f in inventory))} total")
    if not inventory:
        raise RcloneError("Your Drive appears to be empty - nothing to back up.")

    includes = [f.strip("/") for f in (include_folders or []) if f.strip()]
    excludes = [f.strip("/") for f in (exclude_folders or []) if f.strip()]
    files_only = [str(f).replace("\\", "/").strip("/")
                  for f in (include_files or []) if str(f).strip()]
    if files_only:
        wanted = set(files_only)
        before = len(inventory)
        inventory = [f for f in inventory
                     if (f.get("Path") or f.get("Name")) in wanted]
        LOG.info(f"File scope kept {len(inventory)} of {before} files")
        if not inventory:
            raise RcloneError(
                "No files match your selection. The Drive listing may be "
                "outdated - refresh it and try again.")
    elif includes or excludes:
        def in_scope(item: dict[str, Any]) -> bool:
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

    safe_files, problem_files, scan_warnings = _scan_inventory(inventory)
    for w in scan_warnings:
        LOG.info(w)
    if progress_cb and scan_warnings:
        progress_cb(0.01, scan_warnings[0])

    if progress_cb:
        progress_cb(0.02, f"Downloading {len(safe_files)} safe files ...")
    total = sum(f.get("Size", 0) for f in inventory) or 1

    def on_line(line: str) -> None:
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

    tmp_list: Optional[str] = None
    in_progress_flag = state_path("backup_in_progress")
    failed_files: List[dict[str, str]] = []

    try:
        in_progress_flag.write_text(now_iso(), encoding="utf-8")

        safe_paths = [f.get("Path") or f.get("Name") for f in safe_files]
        if safe_paths:
            tmp_safe = _write_files_list(safe_paths, Path(tempfile.gettempdir()))
            try:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        manager.copy(remote, local_dir, transfers, checkers,
                                     on_line, root=root,
                                     extra_args=["--files-from-raw", tmp_safe],
                                     gphotos_proxy=gphotos_proxy)
                        break
                    except RcloneError as exc:
                        if attempt < max_retries - 1:
                            wait = 5 * (2 ** attempt)
                            LOG.warning(f"Safe batch failed (attempt {attempt + 1}/{max_retries}): {exc}")
                            if progress_cb:
                                progress_cb(None, f"Connection lost. Retrying in {wait}s ... ({attempt + 1}/{max_retries})")
                            time.sleep(wait)
                        else:
                            LOG.error(f"Safe batch failed after {max_retries} attempts: {exc}")
            finally:
                try:
                    os.unlink(tmp_safe)
                except OSError:
                    pass

        if problem_files:
            if progress_cb:
                progress_cb(0.5, f"Attempting {len(problem_files)} problematic files ...")
            for i, item in enumerate(problem_files):
                path = item.get("Path") or item.get("Name")
                reason = item.get("_skip_reason", "unknown")
                if progress_cb:
                    progress_cb(0.5 + 0.45 * (i / len(problem_files)),
                                f"Trying problematic file {i+1}/{len(problem_files)}: {path}")
                tmp_prob = _write_files_list([path], Path(tempfile.gettempdir()))
                try:
                    manager.copy(remote, local_dir, transfers, checkers,
                                 on_line, root=root,
                                 extra_args=["--files-from-raw", tmp_prob],
                                 gphotos_proxy=gphotos_proxy)
                except RcloneError as exc:
                    LOG.warning(f"Skipping {path}: {reason} - {exc}")
                    failed_files.append({"path": path, "reason": reason, "error": str(exc)})
                finally:
                    try:
                        os.unlink(tmp_prob)
                    except OSError:
                        pass

    finally:
        try:
            in_progress_flag.unlink(missing_ok=True)
        except OSError:
            pass
        if tmp_list:
            try:
                os.unlink(tmp_list)
            except OSError:
                pass

    if progress_cb:
        progress_cb(0.95, "Computing local checksums ...")
    local = _walk_local(local_dir)
    LOG.info(f"Local files after copy: {len(local)}")

    result_files: List[dict[str, Any]] = []
    for item in inventory:
        path = item.get("Path") or item.get("Name")
        size = item.get("Size", 0)
        md5 = _drive_md5(item)
        mime = item.get("MimeType", "")
        exported = is_exported(mime)
        local_meta: Optional[dict[str, Any]] = None
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
        result_files.append({
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
        "files": result_files,
    }
    state_path("manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")

    ok = sum(1 for f in result_files if f["local"])
    missing = len(result_files) - ok
    LOG.info(f"Backup manifest: {ok} files present locally, {missing} missing")

    if failed_files:
        report_path = state_path("failed_files.json")
        report_path.write_text(json.dumps(failed_files, indent=1), encoding="utf-8")
        LOG.warning(f"{len(failed_files)} file(s) could not be downloaded. See {report_path}")

    return {
        "files": len(result_files),
        "bytes": sum(f["size"] for f in result_files),
        "local_files": len(local),
        "ok": ok,
        "missing": missing,
        "failed": len(failed_files),
        "failed_files": failed_files,
        "manifest": str(state_path("manifest.json")),
    }
