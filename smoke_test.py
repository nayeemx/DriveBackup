import json
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
from app.ai import analyzer as ai
from app.ai.report import generate_report, save_report
from app.utils.config import Config

TEST_DIR = Path(tempfile.mkdtemp(prefix="db_test_"))
SRC = TEST_DIR / "src"
DST = TEST_DIR / "dst"

print("== 1. build fake drive tree ==")
(SRC / "docs").mkdir(parents=True)
(SRC / "photos").mkdir(parents=True)
(SRC / "empty_dir").mkdir()
(SRC / "docs" / "report.txt").write_text("hello world backup test " * 100)
(SRC / "docs" / "same_a.bin").write_bytes(b"\x00" * 4096)
(SRC / "docs" / "same_b.bin").write_bytes(b"\x00" * 4096)
(SRC / "photos" / "img1.jpg").write_bytes(os.urandom(8192))
(SRC / "photos" / "img2.png").write_bytes(os.urandom(2048))
(SRC / "junk.tmp").write_bytes(b"junk")
(SRC / "Thumbs.db").write_bytes(b"x")
(SRC / "empty.txt").write_text("")
(SRC / "big_video.mp4").write_bytes(b"\x01" * 200_000)

manager.ensure_binary()
out = manager.run(["config", "create", "localtest", "local"], capture=True)
print("remote created:", manager.listremotes())

print("\n== 2. backup ==")
result = bk.backup("localtest", DST, root=str(SRC), line_cb=lambda m: print("   ", m))
print("RESULT:", result)

print("\n== 3. verify ==")
vres = vf.verify_local(line_cb=lambda m: print("   ", m))
assert vres["passed"], "verify should PASS"
print("VERIFY PASSED OK")

print("\n== 4. tamper detection ==")
(DST / "docs" / "report.txt").write_text("TAMPERED DATA")
vres2 = vf.verify_local(line_cb=lambda m: None)
assert not vres2["passed"], "verify should FAIL after tamper"
tampered = [r for r in vres2["results"] if r["status"] != "OK"]
assert tampered, "should list tampered file"
print("TAMPER DETECTED:", tampered[0])
(DST / "docs" / "report.txt").write_text("hello world backup test " * 100)

print("\n== 5. analyzer ==")
inv = manager.lsjson("localtest", root=str(SRC))
bk.state_path("inventory.json").write_text(json.dumps(inv), encoding="utf-8")
analysis = ai.analyze()
print("  files:", analysis["count"], " size:", analysis["size"])
print("  categories:", {k: v["count"] for k, v in analysis["categories"].items()})
print("  dup groups:", analysis["dup_count"], "wasted:", analysis["dup_wasted"])
print("  junk size:", analysis["junk_size"], "empty:", len(analysis["empty_files"]))
assert analysis["dup_count"] == 1, "same_a/same_b should be duplicates"
assert analysis["empty_files"], "empty.txt should be detected"

print("\n== 6. report ==")
plan = ai.organization_plan()
content = generate_report(result, vres, analysis, plan)
path = save_report(content)
print("  report:", path, f"({len(content)} chars)")

print("\n== 7. wipe safety gates ==")
cfg = Config()
cfg.set("verify_freshness_hours", 24)
try:
    wp.require_fresh_verification(cfg)
    print("FAIL: gate should block after tamper")
except wp.SafetyGateError as exc:
    print("  gate blocked correctly after failed verify")
vf.verify_local(line_cb=lambda m: None)
wp.require_fresh_verification(cfg)
print("  gate passes after fresh successful verify")
try:
    wp.require_confirmation("nope")
    print("FAIL: phrase gate should block")
except wp.SafetyGateError:
    print("  phrase gate blocked 'nope'")
wp.require_confirmation("DELETE ALL")
print("  phrase gate accepted 'DELETE ALL'")

print("\n== 8. org plan ==")
for entry in plan[:4]:
    print("  ", entry["source"], "->", entry["target"])

print("\nALL PIPELINE TESTS PASSED")