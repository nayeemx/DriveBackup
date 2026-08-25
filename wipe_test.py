import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["APPDATA"] = str(Path(tempfile.mkdtemp()) / "AppData")

from app.engine.rclone_manager import manager
from app.engine import backup as bk
from app.engine import verify as vf
from app.engine import wipe as wp

T = Path(tempfile.mkdtemp())
SRC = T / "src"
DST = T / "dst"
(SRC / "sub").mkdir(parents=True)
(SRC / "a.txt").write_text("alpha" * 100)
(SRC / "sub" / "b.bin").write_bytes(b"\x05" * 5000)

try:
    manager.ensure_binary()
    manager.run(["config", "create", "localtest", "local"], capture=True)

    print("== deep check (with download) ==")
    bk.backup("localtest", DST, root=str(SRC), line_cb=lambda m: None)
    counts = vf.check_remote("localtest", DST, download=True, root=str(SRC),
                             line_cb=lambda m: None)
    print("DEEP:", counts)
    assert counts["passed"], "deep check should pass"
    print("deep check PASSED")

    print("\n== wipe: move to trash ==")
    wp.move_to_trash("localtest", root=str(SRC), line_cb=lambda m: None)
    remaining = manager.lsjson("localtest", root=str(SRC))
    print("files after trash:", len(remaining))
    assert len(remaining) == 0, "src should be empty after trash"

    print("\n== wipe: empty trash ==")
    wp.empty_trash("localtest", line_cb=lambda m: None)
    print("trash emptied OK")

    print("\nWIPE TESTS PASSED")
finally:
    try:
        manager.disconnect("localtest", line_cb=lambda m: None)
    except Exception:
        pass
    shutil.rmtree(T, ignore_errors=True)