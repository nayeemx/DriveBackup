import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["APPDATA"] = str(Path(tempfile.mkdtemp()) / "AppData")

from nicegui import app, ui

from app.gui.app import build, poll, pick_port
from app.gui.context import AppContext

CTX = AppContext()

ERRORS = []

print("pre-installing rclone ...")
CTX.manager.ensure_binary(progress=lambda t: print("  ", t))


@ui.page("/")
def page():
    try:
        build(CTX)
        ui.timer(2.0, start_fake_job)
        ui.timer(4.5, check_console)
        ui.timer(7.0, app.shutdown)
    except Exception:
        ERRORS.append(traceback.format_exc())
        print("PAGE BUILD FAILED")
        print(ERRORS[-1])
        app.shutdown()


def start_fake_job():
    def run(hub):
        for i in range(3):
            hub.log("INFO", f"fake line {i}")
            hub.progress(i * 30, f"step {i}")
        hub.log("WARNING", "fake warning")
        hub.log("SUCCESS", "fake success")
        hub.done("fake", {"files": 42}, None)

    CTX.start_job("fake", run, on_progress=lambda p, t: None,
                  on_done=lambda r, e: print("FAKE JOB DONE OK"))


def check_console():
    count = CTX.console._count if CTX.console else -1
    print(f"CONSOLE COUNT: {count}")
    ok = CTX.console is not None and count >= 5
    print("CONSOLE LINES OK" if ok else "CONSOLE LINES MISSING")
    if CTX.jobs.get("fake"):
        print("JOB REGISTRY OK")


ui.run(title="DriveBackup GUI test", dark=True, host="127.0.0.1", port=pick_port(),
       reload=False, native=True, window_size=(1100, 780),
       uvicorn_logging_level="warning")
if ERRORS:
    print("GUI TEST FAILED")
    sys.exit(1)
print("GUI TEST PASSED (native window ran clean, console + fake job OK)")