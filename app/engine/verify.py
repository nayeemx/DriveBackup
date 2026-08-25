import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .backup import EXPORT_EXTS, get_manifest, load_verify_result, md5_of_file
from .rclone_manager import manager
from ..utils.config import format_bytes, state_path
from ..utils.logging_utils import get_logger, now_iso

LOG = get_logger()

STATUS_OK: str = "OK"
STATUS_EXPORTED: str = "OK (exported)"
STATUS_MISSING: str = "MISSING"
STATUS_SIZE: str = "SIZE MISMATCH"
STATUS_HASH: str = "HASH MISMATCH"
STATUS_EXTRA: str = "EXTRA (not in Drive)"


def verify_local(workers: int = 8,
                 progress_cb: Optional[Callable[[float, str], None]] = None,
                 line_cb: Callable[[str], None] = LOG.info) -> dict[str, Any]:
    manifest = load_manifest_for_verify()
    if not manifest:
        raise RuntimeError("No manifest found - run a backup first.")
    files = manifest["files"]
    local_dir = Path(manifest["local_dir"])
    if not local_dir.exists():
        raise RuntimeError(f"Backup folder not found: {local_dir}")

    line_cb(f"Verifying {len(files)} files against manifest ...")
    if progress_cb:
        progress_cb(0, "Computing local checksums ...")

    local_files: Dict[str, dict[str, Any]] = {}

    def hash_one(rel: str) -> Tuple[str, Optional[dict[str, Any]]]:
        p = local_dir / rel
        try:
            return rel, {"size": p.stat().st_size, "md5": md5_of_file(p)}
        except OSError:
            return rel, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rel, meta in pool.map(
            hash_one, [f["path"] for f in files if not f.get("exported")]
        ):
            if meta:
                local_files[rel] = meta

    results: List[dict[str, str]] = []
    matched = missing = mismatch = extra = 0
    for item in files:
        path = item["path"]
        drive_md5 = item.get("md5")
        if item.get("exported"):
            stem = os.path.splitext(path)[0]
            ext = EXPORT_EXTS.get(item.get("mime", ""), "docx")
            if (local_dir / f"{stem}.{ext}").is_file():
                matched += 1
                results.append({"path": path, "status": STATUS_EXPORTED})
            else:
                missing += 1
                results.append({"path": path, "status": STATUS_MISSING})
            continue
        meta = local_files.get(path)
        if meta is None:
            missing += 1
            results.append({"path": path, "status": STATUS_MISSING})
            continue
        if drive_md5 is None:
            if meta["size"] == item.get("size"):
                matched += 1
                results.append({"path": path, "status": STATUS_OK})
            else:
                mismatch += 1
                results.append({"path": path, "status": STATUS_SIZE})
            continue
        if meta["size"] != item.get("size"):
            mismatch += 1
            results.append({"path": path, "status": STATUS_SIZE})
            continue
        if meta["md5"] and meta["md5"].lower() == drive_md5.lower():
            matched += 1
            results.append({"path": path, "status": STATUS_OK})
        else:
            mismatch += 1
            results.append({"path": path, "status": STATUS_HASH})

    for p in sorted(local_dir.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(local_dir)).replace("\\", "/")
            if rel not in local_files:
                extra += 1
                results.append({"path": rel, "status": STATUS_EXTRA})

    passed = missing == 0 and mismatch == 0
    result: dict[str, Any] = {
        "created": now_iso(),
        "local_dir": str(local_dir),
        "total": len(files),
        "matched": matched,
        "missing": missing,
        "mismatch": mismatch,
        "extra": extra,
        "passed": passed,
        "results": results,
    }
    state_path("verify_result.json").write_text(
        json.dumps(result, indent=1), encoding="utf-8")
    line_cb(f"Verify: {matched} OK, {missing} missing, {mismatch} mismatched, "
            f"{extra} extra -> {'PASS' if passed else 'FAIL'}")
    if progress_cb:
        progress_cb(1.0, "Verification complete")
    return result


def load_manifest_for_verify() -> Optional[dict[str, Any]]:
    path = state_path("manifest.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check_remote(remote: str, local_dir: Union[str, Path], transfers: int = 4,
                 checkers: int = 8, download: bool = False,
                 line_cb: Callable[[str], None] = LOG.info,
                 root: str = "",
                 gphotos_proxy: str = "") -> dict[str, Any]:
    counts: Dict[str, Any] = {"files": 0, "missing": 0, "mismatch": 0, "error": 0}

    def on_line(line: str) -> None:
        line_cb(line)
        if "Checked" in line:
            m = re.search(
                r"Checked\s+(\d+)\s+files?,\s+(\d+)\s+missing,\s+(\d+)\s+mismatch",
                line)
            if m:
                counts["files"] = int(m.group(1))
                counts["missing"] = int(m.group(2))
                counts["mismatch"] = int(m.group(3))
        elif "ERROR" in line:
            counts["error"] += 1

    manager.check(remote, local_dir, transfers, checkers, download, on_line,
                  root=root, gphotos_proxy=gphotos_proxy)
    counts["passed"] = (counts["missing"] == 0 and counts["mismatch"] == 0
                        and counts["error"] == 0)
    return counts


def verify_fresh(now: Optional[datetime] = None,
                 hours: int = 24) -> Tuple[bool, str]:
    data = load_verify_result()
    if not data or not data.get("passed"):
        return False, "No successful verification on record"
    try:
        created = datetime.fromisoformat(data["created"])
    except (ValueError, KeyError):
        return False, "Verification record is unreadable"
    now = now or datetime.now()
    if now - created > timedelta(hours=hours):
        return False, f"Last successful verification is too old ({data['created']})"
    return True, f"Verification PASS at {data['created']}"
