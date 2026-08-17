import os as _os
import queue
import threading

from nicegui import app, ui

from .context import AppContext
from .pages import (AnalyzePage, BackupPage, DashboardPage, SettingsPage,
                    VerifyPage, WipePage)
from ..utils.version import APP_VERSION
from .widgets import LogConsole, code_dialog, auth_url_dialog

PORT = 8085
APP_TITLE = "DriveBackup - Google Drive backup, verify & wipe"
WINDOW_SIZE = (1280, 860)
_WINDOW = None
_SHUTDOWN = threading.Event()

# ---- UI UX Pro Max: Flat Design system (developer tool, dark) ---------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
  --bg: #0F172A;
  --fg: #F8FAFC;
  --card: #111827;
  --muted: #1E293B;
  --muted-fg: #CBD5E1;
  --border: #334155;
  --primary: #0D9488;
  --primary-hover: #14B8A6;
  --accent: #EA580C;
  --danger: #DC2626;
  --good: #22C55E;
  --warn: #F59E0B;
  --info: #38BDF8;
}

html, body { background: var(--bg) !important; }
body {
  font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
  color: var(--fg);
  -webkit-font-smoothing: antialiased;
}

/* Quasar color tokens -> flat palette */
body { --q-primary: var(--primary); --q-secondary: #14B8A6;
       --q-accent: var(--accent); --q-negative: var(--danger);
       --q-positive: var(--good); --q-warning: var(--warn);
       --q-info: var(--info); --q-dark: var(--bg); }

/* Flat surfaces: 1px borders, no shadows */
.q-card {
  background: var(--card) !important;
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: none !important;
}
.q-header { background: var(--card) !important; border-bottom: 1px solid var(--border); }
.q-footer { background: #0B1220 !important; border-top: 1px solid var(--border); }
.q-drawer { background: #0B1220 !important; border-right: 1px solid var(--border); }
.q-table { background: var(--card) !important; }
.q-table th { color: var(--muted-fg) !important; font-weight: 600; }

/* Inputs */
.q-field--outlined .q-field__control {
  background: #0B1220; border-radius: 8px; border: 1px solid var(--border);
}

/* Buttons: flat, 150-200ms ease transitions */
.q-btn {
  border-radius: 8px;
  transition: background-color .18s ease, color .18s ease,
              border-color .18s ease, opacity .18s ease;
}
.q-btn:hover { filter: brightness(1.12); }
.q-btn:active { transform: translateY(0); }

/* Cursor on all clickable elements */
button, .q-btn, .q-link, a, .q-item, [role="button"], .q-field__input { cursor: pointer; }

/* Visible keyboard focus */
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* Console */
.log-line { white-space: pre-wrap; word-break: break-word;
            font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px;
            line-height: 1.5; }
.log-tag { display: inline-block; min-width: 34px; margin-right: 8px;
           font-size: 10px; font-weight: 700; letter-spacing: .08em; opacity: .55; }

/* Drawer navigation */
.nav-item { border-radius: 8px !important; transition: background-color .18s ease, color .18s ease; }
.nav-item:hover { background: rgba(148,163,184,0.08); }
.nav-item.active { background: rgba(13,148,136,0.14) !important; color: var(--primary) !important; }
.nav-item.active .q-icon { color: var(--primary) !important; }

/* Markdown (analyze/report) */
.q-markdown h3, .markdown h3 { font-size: 15px; font-weight: 600; margin: 18px 0 6px; }
.q-markdown li, .markdown li { margin: 2px 0; }

/* Scrollbars */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 5px; }
::-webkit-scrollbar-track { background: transparent; }

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""

NAV_ITEMS = (("Dashboard", "home"), ("Backup", "cloud_download"),
             ("Verify", "fact_check"), ("Analyze", "analytics"),
             ("Wipe", "delete_forever"), ("Settings", "settings"))


def build(ctx: AppContext):
    """Build the whole UI. Runs inside the page's slot."""
    ui.add_head_html(f"<style>{CSS}</style>")

    tabs = ui.tabs().classes("w-full").props("dense")
    panels = ui.tab_panels(tabs, value="Dashboard").classes("w-full flex-1")
    nav_btns = {}

    def navigate(name):
        tabs.set_value(name)
        for label, btn in nav_btns.items():
            if label == name:
                btn.classes(add="active")
            else:
                btn.classes(remove="active")

    # --- header ---------------------------------------------------------------
    with ui.header().classes("items-center px-4").style("height:54px"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("cloud_done").classes("text-2xl").style("color: var(--primary)")
            ui.label("DriveBackup").classes("text-[15px] font-semibold tracking-tight")
            ui.label("·").classes("opacity-30")
            ui.label("Drive backup, verify & wipe").classes(
                "text-xs").style("color: var(--muted-fg)")
        ui.space()
        ctx.header_status = ui.chip("Ready", icon="bolt").props(
            "outline color=primary text-color=white").classes("rounded-full")

    # --- drawer ---------------------------------------------------------------
    with ui.left_drawer(value=True, fixed=False).props("bordered").classes(
            "bg-[#0B1220]"):
        ui.label("NAVIGATION").classes("text-[10px] font-semibold uppercase "
                                       "tracking-[0.16em] px-2 pt-4 pb-1") \
            .style("color: #64748B")
        for name, icon in NAV_ITEMS:
            b = ui.button(name, icon=icon,
                          on_click=lambda n=name: navigate(n)) \
                .props("flat align=left no-caps dense").classes(
                "w-full justify-start nav-item px-3")
            nav_btns[name] = b
        ui.space()
        with ui.column().classes("w-full gap-1 px-2 pb-2"):
            ui.label(f"v{APP_VERSION}").classes("text-xs").style(
                "color: #64748B")
            ui.label("Settings → Updates").classes("text-[10px]") \
                .style("color: #475569")

    # --- footer console -------------------------------------------------------
    with ui.footer().classes("px-2 py-1"):
        ctx.console = LogConsole()

    # --- tab content ----------------------------------------------------------
    with panels:
        with ui.tab_panel("Dashboard"):
            DashboardPage(ctx, navigate).build(None)
        with ui.tab_panel("Backup"):
            BackupPage(ctx).build(None)
        with ui.tab_panel("Verify"):
            VerifyPage(ctx).build(None)
        with ui.tab_panel("Analyze"):
            AnalyzePage(ctx).build(None)
        with ui.tab_panel("Wipe"):
            WipePage(ctx).build(None)
        with ui.tab_panel("Settings"):
            SettingsPage(ctx).build(None)

    tabs.on_value_change(lambda e: navigate(e.value))
    ui.timer(0.15, lambda: poll(ctx))


def poll(ctx: AppContext):
    """Drain background-job events on the UI thread."""
    hub = ctx.hub
    try:
        while True:
            evt = hub.queue.get_nowait()
            _dispatch(ctx, evt)
    except queue.Empty:
        pass


def _dispatch(ctx, evt):
    kind = evt[0]
    if kind == "log":
        if ctx.console:
            ctx.console.push(evt[2], evt[1])
    elif kind == "progress":
        for job in reversed(list(ctx.jobs.values())):
            if job["running"]:
                try:
                    job["on_progress"](evt[1], evt[2])
                except Exception:
                    pass
                break
    elif kind == "done":
        job_id, result, error = evt[1], evt[2], evt[3]
        job = ctx.jobs.get(job_id)
        if job:
            job["running"] = False
            try:
                job["on_done"](result, error)
            except Exception:
                pass
    elif kind == "auth_url":
        auth_url_dialog(evt[1])
    elif kind == "ask_code":
        code_dialog(evt[2], evt[1])


@ui.page("/")
def _page():
    ctx = AppContext()
    build(ctx)
    auto = _os.environ.get("DRIVEBACKUP_AUTOCLOSE")
    if auto:
        ui.timer(float(auto), _close_window)


def _close_window():
    """Test hook: close the native window (mirrors the X button -> shutdown)."""
    if _WINDOW is not None:
        try:
            _WINDOW.destroy()
            return
        except Exception:
            pass
    app.shutdown()


def _native_available():
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def _run_native_in_process():
    """Serve NiceGUI in-process and open pywebview in the same process.

    This deliberately avoids nicegui's native mode, which spawns a window
    subprocess via multiprocessing. In a frozen (PyInstaller --windowed) app
    that spawn silently fails, leaving the app running without a window or
    console. Here the window lives in the main process, and closing it stops
    the server and exits the app.
    """
    global _WINDOW
    import threading
    import webview
    started = threading.Event()
    app.on_startup(started.set)

    def server():
        ui.run(host="127.0.0.1", port=PORT, dark=True, title=APP_TITLE,
               reload=False, show=False, uvicorn_logging_level="warning")

    threading.Thread(target=server, daemon=True).start()
    if not started.wait(timeout=30):
        print("Server did not start - opening in browser instead.")
        ui.run(host="127.0.0.1", port=PORT, dark=True, title=APP_TITLE,
               reload=False, show=True, uvicorn_logging_level="warning",
               window_size=WINDOW_SIZE)
        return
    _WINDOW = webview.create_window(APP_TITLE, f"http://127.0.0.1:{PORT}",
                                    width=WINDOW_SIZE[0],
                                    height=WINDOW_SIZE[1],
                                    min_size=(960, 600))
    _WINDOW.events.closed += app.shutdown
    webview.start()


def _shutdown_watchdog():
    """Force-exit if a shutdown was requested but the GUI loop never returns."""
    if not _SHUTDOWN.wait(timeout=300):
        return
    import time
    time.sleep(6)
    _os._exit(0)


def run():
    app.on_shutdown(lambda: (_SHUTDOWN.set(),
                             print("DriveBackup closed.")))
    threading.Thread(target=_shutdown_watchdog, daemon=True).start()
    if _native_available():
        try:
            _run_native_in_process()
            return
        except Exception as exc:
            print(f"Native window failed ({exc}) - opening in browser instead.")
    ui.run(host="127.0.0.1", port=PORT, dark=True, title=APP_TITLE,
           reload=False, show=True, uvicorn_logging_level="warning",
           window_size=WINDOW_SIZE)