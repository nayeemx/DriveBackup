import os as _os
import queue
import threading

from nicegui import app, ui

from .context import AppContext
from .pages import (AnalyzePage, BackupPage, DashboardPage, HelpPage,
                    SettingsPage, VerifyPage, WipePage, apply_update)
from ..utils.version import APP_VERSION
from .widgets import LogConsole, code_dialog, auth_url_dialog, confirm_dialog
from ..utils.updater import check_for_update

PORT = 8085
APP_TITLE = "DriveBackup - Google Drive backup, verify & wipe"
WINDOW_SIZE = (1280, 860)
_WINDOW = None
_SHUTDOWN = threading.Event()
_AUTO_CHECKED = False

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

/* Page content: readable max width on large windows */
.q-tab-panel { max-width: 1080px; margin: 0 auto; }

/* Responsive stat cards: 2-up until wide windows */
.stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (min-width: 1280px) { .stats-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }

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
             ("Wipe", "delete_forever"), ("Settings", "settings"),
             ("Help", "help"))


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
            ui.label("·").classes("opacity-30 hidden sm:block")
            ui.label("Drive backup, verify & wipe").classes(
                "text-xs hidden sm:block").style("color: var(--muted-fg)")
        ui.space()
        ctx.header_status = ui.chip("Ready", icon="bolt").props(
            "outline color=primary text-color=white").classes("rounded-full")

    # --- drawer (auto-collapses on narrow windows, floating toggle appears) ---
    with ui.left_drawer(value=None, fixed=False).props("bordered").classes(
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
                .style("color: #64748B")

    # --- footer console (collapsible) ---------------------------------------
    console_visible = ctx.config.get("console_visible", "1") != "0"
    with ui.footer().classes("px-2 py-1"):
        with ui.row().classes("w-full items-center gap-2"):
            btn = ui.button(icon="keyboard_arrow_down" if console_visible
                            else "keyboard_arrow_up",
                            on_click=lambda: None).props(
                "flat dense round size=sm").classes("!ml-0")
            ui.label("Console").classes(
                "text-[10px] font-semibold uppercase tracking-[0.16em]") \
                .style("color: var(--muted-fg)")
            ui.space()
            clear_btn = ui.button(icon="delete_sweep").props(
                "flat dense round size=sm").classes("!ml-0") \
                .tooltip("Clear console")
        console_box = ui.column().classes("w-full gap-0")
        ctx.console = LogConsole()

        def toggle():
            nonlocal console_visible
            console_visible = not console_visible
            console_box.set_visibility(console_visible)
            btn.props("icon=" + ("keyboard_arrow_down" if console_visible
                                 else "keyboard_arrow_up"))
            ctx.config.set("console_visible", "1" if console_visible else "0")

        btn.on("click", toggle)
        clear_btn.on("click", ctx.console.clear)
        if not console_visible:
            console_box.set_visibility(False)

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
        with ui.tab_panel("Help"):
            HelpPage(ctx).build(None)

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
        auth_url_dialog(evt[1], on_cancel=evt[2])
    elif kind == "ask_code":
        code_dialog(evt[2], evt[1])


@ui.page("/")
def _page():
    ctx = AppContext()
    build(ctx)
    ui.timer(3.0, lambda: _auto_update_check(ctx), once=True)
    auto = _os.environ.get("DRIVEBACKUP_AUTOCLOSE")
    if auto:
        ui.timer(float(auto), _close_window)


def _auto_update_check(ctx):
    """Check GitHub for a newer release a few seconds after startup.

    Mode (Settings -> Updates -> Automatic updates):
      prompt (default): ask before downloading/installing
      silent:           download, install and relaunch without asking
      off:              never check automatically
    """
    global _AUTO_CHECKED
    if _AUTO_CHECKED:
        return
    _AUTO_CHECKED = True
    mode = (ctx.config.get("auto_update", "prompt") or "prompt").strip()
    if mode == "off":
        return
    owner = (ctx.config.get("github_owner", "") or "").strip()
    repo = (ctx.config.get("github_repo", "") or "").strip()
    if not owner or not repo:
        return

    def fn(hub):
        hub.log("INFO", f"Checking GitHub for updates ({owner}/{repo}) ...")
        info, err = check_for_update(owner, repo)
        if err:
            hub.log("INFO", f"Auto update check skipped: {err}")
            return None
        return info

    def on_done(result, error):
        if error or result is None:
            return
        info = result
        if mode == "silent":
            apply_update(ctx, info)
            return
        ctx.hub.log("INFO",
                    f"Update available: v{info.version} "
                    f"(you have v{APP_VERSION}).")
        confirm_dialog(
            "Update available",
            f"DriveBackup v{info.version} is available (you have "
            f"v{APP_VERSION}). Download and install now?",
            ok_label="Update now",
            on_ok=lambda: apply_update(ctx, info),
        )

    ctx.start_job("auto-update", fn, on_done=on_done)


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


def _close_splash():
    """Close the bootloader splash once the real window is showing."""
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass


def _kill_orphan_webviews():
    """Kill WebView2 browser processes orphaned by dead app instances.

    If DriveBackup is terminated uncleanly (crash, force-kill, power loss),
    its WebView2 browser process tree survives and keeps the WebView2
    user-data-folder lock. The NEXT launch then stalls for tens of seconds
    waiting for that lock - the classic 'stuck on loading screen' symptom.
    Only processes whose parent is no longer alive are killed, so other
    applications' WebView2 processes (Teams, Office, ...) are never touched.
    """
    import ctypes
    from ctypes import wintypes
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        TH32CS_SNAPPROCESS = 0x00000002
        MAX_PATH = 260

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * MAX_PATH),
            ]

        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap in (-1, ctypes.c_void_p(-1).value):
            return
        procs = []
        alive = set()
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                alive.add(entry.th32ProcessID)
                procs.append((entry.th32ProcessID,
                              entry.th32ParentProcessID,
                              entry.szExeFile.decode("utf-8", "ignore")))
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)

        PROCESS_TERMINATE = 0x0001
        kills = []
        for _ in range(8):
            found = False
            for pid, ppid, name in procs:
                if (name.lower() == "msedgewebview2.exe"
                        and ppid not in alive and pid not in kills):
                    kills.append(pid)
                    found = True
            if not found:
                break
        for pid in kills:
            try:
                h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if h:
                    kernel32.TerminateProcess(h, 1)
                    kernel32.CloseHandle(h)
                    alive.discard(pid)
            except Exception:
                pass
        if kills:
            pass
    except Exception:
        pass


def _run_native():
    """Run the server and the window in SEPARATE processes.

    Root cause of the 40-60 s startup stall: WebView2's initialization and
    message pumping run on the .NET side of pythonnet and pin the GIL for
    tens of seconds, starving uvicorn's event loop in the same process
    (requests complete on the handler side but responses are never sent).
    NiceGUI's native mode runs the window in a multiprocessing spawn child,
    so the web server keeps its own event loop and responds immediately.
    The bootloader splash (pyi_splash) covers the window child's startup.
    """
    _kill_orphan_webviews()
    app.on_startup(_close_splash)
    threading.Timer(90, _close_splash).start()
    ui.run(host="127.0.0.1", port=PORT, dark=True, title=APP_TITLE,
           reload=False, show=False, uvicorn_logging_level="warning",
           native=True, window_size=WINDOW_SIZE)


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
            _run_native()
            return
        except Exception as exc:
            print(f"Native window failed ({exc}) - opening in browser instead.")
    ui.run(host="127.0.0.1", port=PORT, dark=True, title=APP_TITLE,
           reload=False, show=True, uvicorn_logging_level="warning",
           window_size=WINDOW_SIZE)