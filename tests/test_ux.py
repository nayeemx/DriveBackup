"""Headless UI smoke: every tab must build and render (no windows spawned).

APPDATA is redirected to a temp dir BEFORE importing app modules so the
tests never touch the real app state / rclone config.
"""
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.gettempdir()) / "db_ux_appdata"
_TMP.mkdir(parents=True, exist_ok=True)
_real_appdata = os.environ.get("APPDATA", "")
os.environ["APPDATA"] = str(_TMP / "AppData")

_real_rclone = None
for _cand in (Path(os.environ.get("LOCALAPPDATA", "")) / "DriveBackup",
              Path(_real_appdata) / "DriveBackup"):
    _p = _cand / "tools" / "rclone.exe"
    if _p.exists():
        _real_rclone = _p
        break
if _real_rclone:
    tools = Path(os.environ["APPDATA"]) / "DriveBackup" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    if not (tools / "rclone.exe").exists():
        shutil.copy2(_real_rclone, tools / "rclone.exe")

from nicegui import ui
from nicegui.testing import User

from app.gui.app import build
from app.gui.context import AppContext


async def test_all_tabs_render(create_user):
    @ui.page("/")
    def page():
        ctx = AppContext()
        build(ctx)

    user: User = create_user()
    await user.open("/")
    await user.should_see("DriveBackup")
    for tab in ("Backup", "Verify", "Analyze", "Wipe", "Settings", "Help"):
        user.find(tab).click()
        await user.should_see(tab)
    await user.should_see("Google Drive Backup")
    await user.should_see("Help & Guide")
    await user.should_see("Everything in my Google Drive")
    await user.should_see("What Verify does")
    await user.should_see("Step 1 of 4: Connect your Google Drive")


async def test_file_picker_dialog_opens(create_user):
    import json

    import app.engine.backup as bk

    inv_path = bk.state_path("inventory.json")
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    inv_path.write_text(json.dumps([
        {"Path": "docs/report.txt", "Name": "report.txt", "Size": 2400},
        {"Path": "photos/img1.jpg", "Name": "img1.jpg", "Size": 8192},
        {"Path": "photos/img2.png", "Name": "img2.png", "Size": 2048},
    ]), encoding="utf-8")

    from app.gui.app import build
    from app.gui.context import AppContext

    @ui.page("/")
    def page():
        ctx = AppContext()
        build(ctx)

    user: User = create_user()
    await user.open("/")
    user.find("Backup").click()
    await user.should_see("Everything in my Google Drive")
    user.find("Only these files (pick them one by one)").click()
    await user.should_see("Browse & select files")
    user.find("Browse & select files").click()
    await user.should_see("Select files to back up")
    await user.should_see("0 of 3 files selected")
    user.find("Wipe").click()
    await user.should_see("Select files to wipe")
    user.find("Select files to wipe").click()
    await user.should_see("Shift-click selects a range")
