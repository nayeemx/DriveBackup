import os as _os
import queue
import socket
import threading
from typing import Any, Callable, Dict, List, Optional

from nicegui import app, ui

from .context import AppContext
from .pages import (AnalyzePage, BackupPage, DashboardPage, HelpPage,
                    SettingsPage, VerifyPage, WipePage, apply_update)
from ..utils.version import APP_VERSION
from .widgets import LogConsole, code_dialog, auth_url_dialog, confirm_dialog
from ..utils.updater import check_for_update

APP_TITLE = "DriveBackup - Google Drive backup, verify & wipe"
WINDOW_SIZE = (1280, 860)
_WINDOW = None
_SHUTDOWN = threading.Event()
_AUTO_CHECKED = False


def pick_port(start: int = 8085, tries: int = 15) -> int:
    """Return the first free port on 127.0.0.1 (or 0 = OS-assigned).

    Another program (or a previous app instance) may already hold the
    default port, so we always scan for a free one - the app must work
    on any computer without configuration.
    """
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0

# ---- UI UX Pro Max: Premium Glassmorphism Design System -------------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap');

:root {
  --bg: #F8F9FA;
  --bg-secondary: #E8EAED;
  --fg: #202124;
  --card: rgba(255, 255, 255, 0.85);
  --muted: #5F6368;
  --muted-fg: #5F6368;
  --border: rgba(0, 0, 0, 0.08);
  --primary: #4285F4;
  --primary-hover: #1A73E8;
  --accent: #0F9D58;
  --danger: #DB4437;
  --good: #0F9D58;
  --warn: #F4B400;
  --info: #4285F4;
  --glow-primary: rgba(66, 133, 244, 0.2);
  --glow-accent: rgba(15, 157, 88, 0.2);
  --input-bg: rgba(255, 255, 255, 0.5);
  --input-border-hover: rgba(0, 0, 0, 0.2);
  --scroll-thumb: rgba(0, 0, 0, 0.2);
  --scroll-thumb-hover: rgba(0, 0, 0, 0.3);
  --scroll-track: rgba(0, 0, 0, 0.05);
  --header-bg: rgba(248, 249, 250, 0.8);
  --drawer-bg: rgba(232, 234, 237, 0.75);
  --shadow-color: rgba(0, 0, 0, 0.1);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #202124;
    --bg-secondary: #282A2D;
    --fg: #E8EAED;
    --card: rgba(40, 42, 45, 0.75);
    --muted: #9AA0A6;
    --muted-fg: #9AA0A6;
    --border: rgba(255, 255, 255, 0.08);
    --primary: #8AB4F8;
    --primary-hover: #A8C7FA;
    --accent: #81C995;
    --danger: #F28B82;
    --good: #81C995;
    --warn: #FDD663;
    --info: #8AB4F8;
    --glow-primary: rgba(138, 180, 248, 0.2);
    --glow-accent: rgba(129, 201, 149, 0.2);
    --input-bg: rgba(0, 0, 0, 0.2);
    --input-border-hover: rgba(255, 255, 255, 0.2);
    --scroll-thumb: rgba(255, 255, 255, 0.1);
    --scroll-thumb-hover: rgba(255, 255, 255, 0.2);
    --scroll-track: rgba(0, 0, 0, 0.1);
    --header-bg: rgba(32, 33, 36, 0.8);
    --drawer-bg: rgba(40, 42, 45, 0.75);
    --shadow-color: rgba(0, 0, 0, 0.3);
  }
}

html, body {
  background: radial-gradient(circle at top center, var(--bg-secondary) 0%, var(--bg) 100%) !important;
  min-height: 100vh;
}

body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  color: var(--fg);
  -webkit-font-smoothing: antialiased;
  animation: fadeIn 0.8s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

h1, h2, h3, h4, h5, h6, .text-xl, .text-lg, .font-semibold {
  font-family: 'Outfit', sans-serif;
  letter-spacing: -0.02em;
}

/* Quasar color tokens */
body { --q-primary: var(--primary); --q-secondary: var(--primary-hover);
       --q-accent: var(--accent); --q-negative: var(--danger);
       --q-positive: var(--good); --q-warning: var(--warn);
       --q-info: var(--info); --q-dark: var(--bg); }

/* Glassmorphism Cards */
.q-card {
  background: var(--card) !important;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 8px 32px 0 var(--shadow-color) !important;
  transition: box-shadow 0.3s ease;
}

.hover-lift:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px 0 var(--shadow-color), 0 0 15px rgba(255,255,255,0.03) !important;
}

.q-header {
  background: var(--header-bg) !important;
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}

.q-footer {
  background: var(--header-bg) !important;
  border-top: 1px solid var(--border);
}

.q-drawer {
  background: var(--drawer-bg) !important;
  backdrop-filter: blur(16px);
  border-right: 1px solid var(--border);
}

.q-table {
  background: transparent !important;
}

.q-table th {
  color: var(--fg) !important;
  font-family: 'Outfit', sans-serif;
  font-weight: 500;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-size: 0.75rem;
}

/* Inputs */
.q-field--outlined .q-field__control {
  background: var(--input-bg);
  border-radius: 12px;
  border: 1px solid var(--border);
  transition: all 0.3s ease;
}
.q-field--outlined .q-field__control:hover {
  border-color: var(--input-border-hover);
}
.q-field--focused .q-field__control {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 2px var(--glow-primary);
}

/* Dynamic Buttons */
.q-btn {
  border-radius: 12px;
  font-family: 'Outfit', sans-serif;
  font-weight: 500;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  text-transform: none;
  letter-spacing: 0.01em;
}

.q-btn.bg-primary {
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%) !important;
  box-shadow: 0 4px 15px var(--glow-primary);
}

.q-btn.bg-primary:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 6px 20px var(--glow-primary);
  filter: brightness(1.1);
}

.q-btn:active {
  transform: translateY(1px) scale(0.98) !important;
}

/* Cursor on all clickable elements */
button, .q-btn, .q-link, a, .q-item, [role="button"], .q-field__input { cursor: pointer; }

/* Visible keyboard focus */
:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* Console */
.log-line {
  white-space: pre-wrap; word-break: break-word;
  font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px;
  line-height: 1.6;
}
.log-tag {
  display: inline-block; min-width: 36px; margin-right: 8px;
  font-size: 10px; font-weight: 700; letter-spacing: .08em;
  opacity: .8; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.1);
}

/* Drawer navigation */
.nav-item {
  border-radius: 12px !important;
  margin: 4px 12px;
  transition: all 0.2s ease;
  font-family: 'Outfit', sans-serif;
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.05);
  transform: translateX(4px);
}
.nav-item.active {
  background: linear-gradient(90deg, var(--glow-primary), transparent) !important;
  color: var(--primary) !important;
  border-left: 3px solid var(--primary);
}
.nav-item.active .q-icon { color: var(--primary) !important; filter: drop-shadow(0 0 8px var(--glow-primary)); }

/* Page content */
.q-tab-panel {
  max-width: 1080px;
  margin: 0 auto;
  animation: fadeUp 0.5s ease-out;
  overflow-y: auto;
  overflow-x: hidden;
}

@keyframes fadeUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Responsive stat cards */
.stats-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (min-width: 900px) { .stats-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }

/* Table constraints */
.q-table { max-height: 400px; overflow-y: auto; }
.q-table__middle { max-height: 380px; }

/* Markdown */
.q-markdown h3, .markdown h3 { font-family: 'Outfit', sans-serif; font-size: 18px; font-weight: 600; margin: 24px 0 8px; color: var(--primary); }
.q-markdown li, .markdown li { margin: 4px 0; }
.q-markdown table, .markdown table { width: 100%; overflow-x: auto; display: block; }
.q-markdown td, .markdown td { max-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.q-markdown td:last-child, .markdown td:last-child { white-space: normal; word-break: break-word; }

/* Custom Scrollbars */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb {
  background: var(--scroll-thumb);
  border-radius: 8px;
}
::-webkit-scrollbar-thumb:hover { background: var(--scroll-thumb-hover); }
::-webkit-scrollbar-track { background: var(--scroll-track); }

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""

NAV_ITEMS = (("Dashboard", "home"), ("Backup", "cloud_download"),
             ("Verify", "fact_check"), ("Analyze", "analytics"),
             ("Wipe", "delete_forever"), ("Settings", "settings"),
             ("Help", "help"))


def build(ctx: AppContext) -> None:
    """Build the whole UI. Runs inside the page's slot."""
    ui.add_head_html(f"<style>{CSS}</style>")

    tabs = ui.tabs().classes("w-full").props("dense")
    panels = ui.tab_panels(tabs, value="Dashboard").classes("w-full flex-1 overflow-y-auto")
    nav_btns: Dict[str, Any] = {}

    def navigate(name: str) -> None:
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
    console_visible: bool = ctx.config.get("console_visible", "1") != "0"
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
        with console_box:
            ctx.console = LogConsole()

        def toggle() -> None:
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


def poll(ctx: AppContext) -> None:
    """Drain background-job events on the UI thread."""
    hub = ctx.hub
    try:
        while True:
            evt = hub.queue.get_nowait()
            _dispatch(ctx, evt)
    except queue.Empty:
        pass


def _dispatch(ctx: AppContext, evt: tuple) -> None:
    kind = evt[0]
    if kind == "log":
        if ctx.console:
            ctx.console.push(evt[2], evt[1])
    elif kind == "progress":
        for job in reversed(list(ctx.jobs.values())):
            if job["running"]:
                try:
                    job["on_progress"](evt[1], evt[2])
                except (KeyError, ValueError, TypeError):
                    pass
                break
    elif kind == "done":
        job_id, result, error = evt[1], evt[2], evt[3]
        job = ctx.jobs.get(job_id)
        if job:
            job["running"] = False
            try:
                job["on_done"](result, error)
            except (KeyError, ValueError, TypeError):
                pass
    elif kind == "auth_url":
        auth_url_dialog(evt[1], on_cancel=evt[2])
    elif kind == "ask_code":
        code_dialog(evt[2], evt[1], cancel_event=evt[3] if len(evt) > 3 else None)


@ui.page("/")
def _page() -> None:
    ctx = AppContext()
    build(ctx)
    ui.timer(3.0, lambda: _auto_update_check(ctx), once=True)
    auto = _os.environ.get("DRIVEBACKUP_AUTOCLOSE")
    if auto:
        ui.timer(float(auto), _close_window)


def _auto_update_check(ctx: AppContext) -> None:
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

    def fn(hub: Any) -> Any:
        hub.log("INFO", f"Checking GitHub for updates ({owner}/{repo}) ...")
        info, err = check_for_update(owner, repo)
        if err:
            hub.log("INFO", f"Auto update check skipped: {err}")
            return None
        return info

    def on_done(result: Any, error: Any) -> None:
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


def _close_window() -> None:
    """Test hook: close the native window (mirrors the X button -> shutdown)."""
    if _WINDOW is not None:
        try:
            _WINDOW.destroy()
            return
        except (OSError, AttributeError):
            pass
    app.shutdown()


def _native_available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


_SPLASH_CLOSED = False


def _close_splash() -> None:
    """Close the bootloader splash once the real window is showing."""
    global _SPLASH_CLOSED
    if _SPLASH_CLOSED:
        return
    _SPLASH_CLOSED = True
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except (ImportError, OSError):
        pass


def _kill_orphan_webviews() -> None:
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
        procs: List[tuple] = []
        alive: set = set()
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
        kills: set = set()
        for pid, ppid, name in procs:
            if (name.lower() == "msedgewebview2.exe"
                    and ppid not in alive and pid not in kills):
                kills.add(pid)
        for pid in kills:
            try:
                h = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if h:
                    kernel32.TerminateProcess(h, 1)
                    kernel32.CloseHandle(h)
            except (OSError, WindowsError):
                pass
    except (ImportError, OSError):
        pass


def _run_native() -> None:
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
    ui.run(host="127.0.0.1", port=pick_port(), dark=True, title=APP_TITLE,
           reload=False, show=False, uvicorn_logging_level="warning",
           native=True, window_size=WINDOW_SIZE)


def _shutdown_watchdog() -> None:
    """Force-exit if a shutdown was requested but the GUI loop never returns."""
    if not _SHUTDOWN.wait(timeout=300):
        return
    import time
    time.sleep(6)
    try:
        app.shutdown()
    except (OSError, RuntimeError):
        pass
    _os._exit(0)


def run() -> None:
    app.on_shutdown(lambda: (_SHUTDOWN.set(),
                             print("DriveBackup closed.")))
    threading.Thread(target=_shutdown_watchdog, daemon=True).start()
    if _native_available():
        try:
            _run_native()
            return
        except Exception as exc:
            print(f"Native window failed ({exc}) - opening in browser instead.")
    ui.run(host="127.0.0.1", port=pick_port(), dark=True, title=APP_TITLE,
           reload=False, show=True, uvicorn_logging_level="warning",
           window_size=WINDOW_SIZE)
