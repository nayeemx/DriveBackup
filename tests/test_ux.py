"""Headless UI smoke: every tab must build and render (no windows spawned)."""
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
