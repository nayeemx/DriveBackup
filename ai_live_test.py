"""Live end-to-end AI test against the real OpenRouter API.

Runs in an isolated temp APPDATA state dir - no real user data touched.
API key comes from the OPENROUTER_KEY environment variable.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="db_live_ai_")
os.environ["APPDATA"] = TMP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ai import llm  # noqa: E402
from app.ai import analyzer as an  # noqa: E402
from app.utils.config import STATE_DIR  # noqa: E402

KEY = os.environ.get("OPENROUTER_KEY", "")
if not KEY:
    print("NO KEY - set OPENROUTER_KEY env var")
    sys.exit(1)

INVENTORY = [
    {"Path": "docs/report.pdf", "Name": "report.pdf", "Size": 2_450_000,
     "Hashes": {"MD5": "11" * 16}, "ModTime": "2026-01-15T10:00:00"},
    {"Path": "docs/proposal.docx", "Name": "proposal.docx", "Size": 890_000,
     "Hashes": {"MD5": "22" * 16}, "ModTime": "2026-02-01T09:00:00"},
    {"Path": "docs/contract_2026.pdf", "Name": "contract_2026.pdf", "Size": 3_100_000,
     "Hashes": {"MD5": "33" * 16}, "ModTime": "2026-03-10T14:30:00"},
    {"Path": "docs/notes.md", "Name": "notes.md", "Size": 12_000,
     "Hashes": {"MD5": "44" * 16}, "ModTime": "2025-11-20T08:00:00"},
    {"Path": "fin/budget.xlsx", "Name": "budget.xlsx", "Size": 1_200_000,
     "Hashes": {"MD5": "55" * 16}, "ModTime": "2026-01-05T16:00:00"},
    {"Path": "fin/expenses.csv", "Name": "expenses.csv", "Size": 340_000,
     "Hashes": {"MD5": "66" * 16}, "ModTime": "2026-04-01T11:00:00"},
    {"Path": "present/pitch.pptx", "Name": "pitch.pptx", "Size": 5_400_000,
     "Hashes": {"MD5": "77" * 16}, "ModTime": "2026-02-14T18:00:00"},
    {"Path": "photos/photo1.jpg", "Name": "photo1.jpg", "Size": 4_200_000,
     "Hashes": {"MD5": "aa" * 16}, "ModTime": "2025-07-04T12:00:00"},
    {"Path": "photos/copy_photo1.jpg", "Name": "copy_photo1.jpg", "Size": 4_200_000,
     "Hashes": {"MD5": "aa" * 16}, "ModTime": "2025-07-04T12:30:00"},
    {"Path": "photos/scan_0001.png", "Name": "scan_0001.png", "Size": 8_100_000,
     "Hashes": {"MD5": "88" * 16}, "ModTime": "2025-03-03T10:00:00"},
    {"Path": "videos/trip.mp4", "Name": "trip.mp4", "Size": 650_000_000,
     "Hashes": {"MD5": "99" * 16}, "ModTime": "2025-08-15T20:00:00"},
    {"Path": "audio/podcast.mp3", "Name": "podcast.mp3", "Size": 95_000_000,
     "Hashes": {"MD5": "00" * 16}, "ModTime": "2026-05-02T07:00:00"},
    {"Path": "arch/backup.zip", "Name": "backup.zip", "Size": 12_000_000,
     "Hashes": {"MD5": "12" * 16}, "ModTime": "2025-12-01T00:00:00"},
    {"Path": "dev/script.py", "Name": "script.py", "Size": 8_000,
     "Hashes": {"MD5": "34" * 16}, "ModTime": "2026-04-10T15:00:00"},
    {"Path": "dev/config.json", "Name": "config.json", "Size": 2_500,
     "Hashes": {"MD5": "56" * 16}, "ModTime": "2026-04-10T15:05:00"},
    {"Path": "3d/model.stl", "Name": "model.stl", "Size": 22_000_000,
     "Hashes": {"MD5": "78" * 16}, "ModTime": "2025-09-09T09:00:00"},
    {"Path": "3d/logo.ai", "Name": "logo.ai", "Size": 1_500_000,
     "Hashes": {"MD5": "9a" * 16}, "ModTime": "2025-09-09T09:10:00"},
    {"Path": "misc/invoice_2025.cdr", "Name": "invoice_2025.cdr", "Size": 720_000,
     "Hashes": {"MD5": "ab" * 16}, "ModTime": "2025-10-10T10:00:00"},
    {"Path": "misc/ebook.mobi", "Name": "ebook.mobi", "Size": 2_800_000,
     "Hashes": {"MD5": "cd" * 16}, "ModTime": "2026-01-25T19:00:00"},
    {"Path": "misc/meeting_notes.one", "Name": "meeting_notes.one", "Size": 950_000,
     "Hashes": {"MD5": "ef" * 16}, "ModTime": "2026-03-05T13:00:00"},
    {"Path": "misc/flowchart.vsdx", "Name": "flowchart.vsdx", "Size": 640_000,
     "Hashes": {"MD5": "10" * 16}, "ModTime": "2026-02-20T17:00:00"},
    {"Path": "misc/passwords.kdbx", "Name": "passwords.kdbx", "Size": 150_000,
     "Hashes": {"MD5": "32" * 16}, "ModTime": "2026-05-15T08:30:00"},
    {"Path": "misc/photo_raw.DNG", "Name": "photo_raw.DNG", "Size": 30_000_000,
     "Hashes": {"MD5": "54" * 16}, "ModTime": "2025-06-06T06:00:00"},
    {"Path": "misc/font_awesome.otf", "Name": "font_awesome.otf", "Size": 210_000,
     "Hashes": {"MD5": "76" * 16}, "ModTime": "2025-04-04T04:00:00"},
    {"Path": "misc/game_save.sav", "Name": "game_save.sav", "Size": 9_000_000,
     "Hashes": {"MD5": "98" * 16}, "ModTime": "2026-04-28T22:00:00"},
    {"Path": "misc/contract_signed.p7s", "Name": "contract_signed.p7s", "Size": 4_000,
     "Hashes": {"MD5": "ba" * 16}, "ModTime": "2026-03-11T09:00:00"},
    {"Path": "junk/thumbs.db", "Name": "thumbs.db", "Size": 500_000,
     "Hashes": {"MD5": "dc" * 16}, "ModTime": "2025-01-01T00:00:00"},
    {"Path": "junk/~$proposal.docx", "Name": "~$proposal.docx", "Size": 2_000,
     "Hashes": {"MD5": "fe" * 16}, "ModTime": "2026-02-01T09:05:00"},
    {"Path": "junk/old_backup.bak", "Name": "old_backup.bak", "Size": 4_000_000,
     "Hashes": {"MD5": "01" * 16}, "ModTime": "2024-12-31T23:00:00"},
    {"Path": "junk/empty.txt", "Name": "empty.txt", "Size": 0,
     "Hashes": {"MD5": "d4" * 16}, "ModTime": "2025-05-05T05:00:00"},
]

MANIFEST = [{"path": i["Path"], "size": i["Size"], "md5": i["Hashes"]["MD5"],
             "modtime": i["ModTime"]} for i in INVENTORY]

VERIFY = {"passed": True, "total": 30, "matched": 30, "missing": 0,
          "mismatch": 0, "extra": 0, "created": "2026-08-16T22:00:00"}

STATE_DIR.mkdir(parents=True, exist_ok=True)
(STATE_DIR / "inventory.json").write_text(json.dumps(INVENTORY), encoding="utf-8")
(STATE_DIR / "manifest.json").write_text(
    json.dumps({"files": MANIFEST}), encoding="utf-8")
(STATE_DIR / "verify_result.json").write_text(json.dumps(VERIFY), encoding="utf-8")

print("=== 1. ANALYZE (incl. AI categorization of 'Other' files) ===")
t0 = time.time()
a = an.analyze(KEY, provider="openrouter")
print(f"({time.time() - t0:.1f}s) AI classified: {a['ai_classified']} files")
for cat, v in sorted(a["categories"].items(), key=lambda kv: -kv[1]["size"]):
    print(f"  {cat:16} {v['count']:4} files  {v['size'] / 1e6:8.1f} MB")

print("\n=== 2. AI ORGANIZATION PLAN ===")
t0 = time.time()
plan = an.organization_plan(KEY, provider="openrouter")
print(f"({time.time() - t0:.1f}s)")
ai_used = sum(1 for e in plan if "Organized/" not in e["target"])
print(f"AI-proposed targets: {ai_used}/{len(plan)}")
for e in plan:
    print(f"  {e['source']:34} -> {e['target']}")

print("\n=== 3. AI QUALITY CHECK ===")
t0 = time.time()
findings = an.quality_check(KEY, analysis=a, verify=VERIFY,
                            provider="openrouter")
print(f"({time.time() - t0:.1f}s) findings: {len(findings)}")
for f in findings:
    print(f"  [{f['severity'].upper()}] {f['message']}")

print("\n=== 4. AI EXECUTIVE SUMMARY ===")
t0 = time.time()
s = llm.summarize(KEY, a, provider="openrouter")
print(f"({time.time() - t0:.1f}s)")
print(s)

shutil.rmtree(TMP, ignore_errors=True)
print("\nLIVE AI TEST COMPLETE")