from contextlib import nullcontext
import json as _json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from nicegui import ui

from .widgets import (ACCENT, DANGER, GOOD, INFO, MUTED, PRIMARY, WARN,
                      FilePickerDialog, LogConsole, PipelineChips, StatCard,
                      confirm_dialog, info_card, open_in_explorer, page_header,
                      pick_directory)

from ..ai import analyzer as ai_analyzer
from ..ai import llm
from ..ai.report import generate_report, save_report
from ..engine import backup as bk
from ..engine import verify as vf
from ..engine import wipe as wp
from ..utils.config import format_bytes, state_path
from ..utils.updater import check_for_update, install_update
from ..utils.version import APP_VERSION


def _fmt(n: Any) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


_UPDATE_JOB_RUNNING = False


def apply_update(ctx: Any, info: Any) -> None:
    """Download, install and relaunch an update in a background job."""

    def fn(hub: Any) -> bool:
        hub.log("INFO", f"Downloading {info.asset_name} ...")
        install_update(info, progress=lambda m: hub.log("INFO", m))
        hub.log("SUCCESS", f"Update v{info.version} staged - closing for install ...")
        return True

    def on_done(result: Any, error: Optional[Exception]) -> None:
        global _UPDATE_JOB_RUNNING
        _UPDATE_JOB_RUNNING = False
        if error:
            ui.notify(f"Update failed: {error}", type="negative",
                      position="top-right")
            return
        ui.notify("Installing - the app will reopen on its own ...",
                  type="positive", position="top-right")
        from nicegui import app as napp
        napp.shutdown()

    global _UPDATE_JOB_RUNNING
    if _UPDATE_JOB_RUNNING:
        ui.notify("An update is already being installed.", type="warning",
                  position="top-right")
        return
    _UPDATE_JOB_RUNNING = True
    ctx.start_job("update", fn, on_done=on_done)


class DashboardPage:
    def __init__(self, ctx: Any, navigate: Callable[[str], None]) -> None:
        self.ctx = ctx
        self.navigate = navigate
        self.stats: Dict[str, Any] = {}
        self.connect_btn: Optional[Any] = None
        self.disconnect_btn: Optional[Any] = None
        self.guide_icon: Optional[Any] = None
        self.guide_title: Optional[Any] = None
        self.guide_text: Optional[Any] = None
        self.guide_btn: Optional[Any] = None
        self._guide_step = ""
        self.service_select: Optional[Any] = None
        self._photos_notice: Optional[Any] = None

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header(
                "cloud_download",
                "Google Drive & Photos Backup",
                "Back up everything, verify it, then safely wipe your Drive - "
                "with AI analysis in between.")

            # Service selector
            with ui.card().props("flat bordered").classes("w-full mb-3 p-3"):
                ui.label("ACTIVE SERVICE").classes(
                    "text-[10px] font-semibold uppercase tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                self.service_select = ui.select(
                    {"drive": "🗄️  Google Drive",
                     "photos": "🖼️  Google Photos"},
                    value=self.ctx.config.get("active_service", "drive"),
                    on_change=self._service_changed,
                ).props("outlined dense").classes("w-full max-w-xs mt-1")
                self._photos_notice = ui.label(
                    "⚠️  Google Photos: backup & analysis only. "
                    "Deletion is blocked by Google's API."
                ).classes("text-xs mt-1").style(f"color:{WARN}") \
                    .bind_visibility_from(
                    self.service_select, "value",
                    backward=lambda v: v == "photos")

            with ui.row().classes("w-full items-center gap-2 mb-4"):
                self.connect_btn = ui.button("Connect", icon="link",
                                             on_click=self._connect)\
                    .props("color=primary no-caps")
                self.disconnect_btn = ui.button("Disconnect account", icon="link_off",
                                                on_click=self._disconnect)\
                    .props("outline no-caps color=negative").set_visibility(False)
                ui.button("Refresh", icon="refresh", on_click=self.refresh)\
                    .props("outline no-caps")

            ui.label("Your journey").classes("text-[10px] font-semibold uppercase "
                                             "tracking-[0.16em]") \
                .style(f"color:{MUTED}")
            PipelineChips(self.ctx, on_navigate=self._step_to)

            with ui.card().props("flat bordered").classes("w-full mt-3"):
                with ui.row().classes("w-full items-center gap-3 p-1 flex-wrap"):
                    self.guide_icon = ui.icon("rocket_launch") \
                        .classes("text-3xl shrink-0").style(f"color:{ACCENT}")
                    with ui.column().classes("flex-1 min-w-[220px] gap-0"):
                        self.guide_title = ui.label("").classes(
                            "text-[15px] font-semibold")
                        self.guide_text = ui.label("").classes(
                            "text-xs mt-0.5").style(f"color:{MUTED}")
                    self.guide_btn = ui.button("", icon="arrow_forward",
                                               on_click=self._guide_action) \
                        .props("color=primary no-caps")

            with ui.element("div").classes("w-full grid stats-grid gap-3 mt-4"):
                self.stats["state"] = StatCard("Connection", "-", "cloud_off", MUTED)
                self.stats["total"] = StatCard("Total", "-", "storage", ACCENT)
                self.stats["used"] = StatCard("Used", "-", "pie_chart", WARN)
                self.stats["free"] = StatCard("Free", "-", "check_circle", GOOD)
                self.stats["backed"] = StatCard("Backed up", "-", "folder_copy",
                                                PRIMARY)
                self.stats["files"] = StatCard("Files", "-", "description", INFO)
            self.refresh()
            self._refresh_connect_label()

    def _guide_action(self) -> None:
        step = self._guide_step
        if step == "connect":
            self._connect()
        elif step in ("Backup", "Verify", "Analyze", "Wipe", "Settings",
                      "Help", "Dashboard"):
            self.navigate(step)

    def _step_to(self, step: str) -> None:
        mapping = {"Connect": "Dashboard", "Backup": "Backup", "Verify": "Verify",
                   "Analyze": "Analyze", "Wipe": "Wipe"}
        self.navigate(mapping.get(step, "Dashboard"))

    def _service_changed(self, e: Any) -> None:
        self.ctx.config.set("active_service", e.value)
        self._refresh_connect_label()
        self.refresh()

    def _refresh_connect_label(self) -> None:
        if not self.connect_btn:
            return
        svc = self.ctx.config.get("active_service", "drive")
        label = "Connect Google Photos" if svc == "photos" else "Connect Google Drive"
        self.connect_btn.set_text(label)

    def refresh(self) -> None:
        ctx = self.ctx
        remote = ctx.config.active_remote
        connected = ctx.manager.remote_exists(remote)
        if not connected:
            self.stats["state"].set("Not connected", MUTED)
            self.stats["state"].set_icon("cloud_off", MUTED)
            self.stats["total"].set("-")
            self.stats["used"].set("-")
            self.stats["free"].set("-")
            self.stats["files"].set("-")
            self.stats["backed"].set("-")
            if self.connect_btn:
                self.connect_btn.enable()
                self.connect_btn.set_text("Connect Google Drive")
            if self.disconnect_btn:
                self.disconnect_btn.set_visibility(False)
            self._guide(
                "connect",
                "Step 1 of 4: Connect your Google Drive",
                "Your files are safe in Google's cloud, but DriveBackup can "
                "only reach them after you allow access once.",
                "Connect Google Drive")
            ctx.hub.log("WARNING", "Drive not connected - click 'Connect Google Drive'.")
            return
        self.stats["state"].set("Connected", GOOD)
        self.stats["state"].set_icon("cloud_done", GOOD)
        if self.disconnect_btn:
            self.disconnect_btn.set_visibility(True)
        manifest = bk.load_manifest()
        if not manifest:
            self._guide(
                "Backup",
                "Step 2 of 4: Back up your Drive",
                "Choose what to back up (everything, folders, or specific "
                "files) and where to save it on this computer.",
                "Go to Backup")
        else:
            ok, _msg = vf.verify_fresh(
                hours=ctx.config.get("verify_freshness_hours", 24))
            if not ok:
                self._guide(
                    "Verify",
                    "Step 3 of 4: Verify your backup",
                    "Checksums prove every downloaded file matches the Drive "
                    "original. Do this before wiping anything.",
                    "Go to Verify")
            else:
                self._guide(
                    "Analyze",
                    "Step 4 of 4: Analyze, then wipe (optional)",
                    "See AI insights about your Drive and, when ready, wipe "
                    "it safely - Trash first, permanent only after verify.",
                    "Go to Analyze")
        job = ctx.jobs.get("stats")
        if job and job["running"]:
            return
        self.stats["total"].set("...")
        self.stats["used"].set("...")
        self.stats["free"].set("...")
        ctx.start_job(
            "stats",
            lambda hub: (ctx.manager.about_cached(remote),
                         bk.load_inventory()),
            on_done=self._stats_done,
        )

    def _stats_done(self, result: Any, error: Optional[Exception]) -> None:
        ctx = self.ctx
        ctx.finish_job("stats")
        if error:
            ctx.hub.log("ERROR", f"Could not read drive stats: {error}")
            return
        about, inv = result or ({}, None)
        for key, stat in (("Total", "total"), ("Used", "used"),
                          ("Free", "free")):
            if key in about:
                self.stats[stat].set(about[key])
        if inv:
            total = sum(f.get("Size", 0) for f in inv)
            self.stats["files"].set(f"{_fmt(len(inv))}")
            self.stats["backed"].set(format_bytes(total))
        else:
            self.stats["files"].set("0")
            self.stats["backed"].set("-")

    def _guide(self, step: str, title: str, text: str, button_label: str) -> None:
        self._guide_step = step
        if self.guide_title:
            self.guide_title.set_text(title)
        if self.guide_text:
            self.guide_text.set_text(text)
        if self.guide_btn:
            self.guide_btn.set_text(button_label)

    def _connect(self) -> None:
        ctx = self.ctx
        if self.connect_btn:
            self.connect_btn.disable()
            self.connect_btn.set_text("Connecting ...")
        svc = ctx.config.get("active_service", "drive")
        remote = ctx.config.active_remote
        backend_type = "google photos" if svc == "photos" else "drive"
        ctx.start_job(
            "connect",
            lambda hub: ctx.manager.connect(
                remote,
                backend_type,
                ctx.config.get("export_formats"),
                auth_cb=lambda url, ce=None: hub.ask_auth_url(url, ce),
                code_cb=lambda ce=None: hub.ask_code(ce),
            ),
            on_done=self._connect_done,
        )

    def _connect_done(self, result: Any, error: Optional[Exception]) -> None:
        from .widgets import connect_dialog_status
        self.ctx.finish_job("connect")
        svc = self.ctx.config.get("active_service", "drive")
        svc_label = "Google Photos" if svc == "photos" else "Google Drive"
        if self.connect_btn:
            self.connect_btn.enable()
            self._refresh_connect_label()
        if error:
            connect_dialog_status(f"Connection failed: {error}", ok=False)
            ui.notify(f"Connection failed: {error}", type="negative",
                      position="top-right")
            return
        connect_dialog_status(f"Connected! {svc_label} is ready.", ok=True)
        self.ctx.hub.log("SUCCESS", f"{svc_label} connected.")
        ui.notify(f"{svc_label} connected", type="positive", position="top-right")
        self.refresh()

    def _disconnect(self) -> None:
        confirm_dialog(
            "Disconnect Google Drive?",
            "This removes the connected Google account from the app.\n\n"
            "The local backup stays untouched. The next 'Connect' will ask "
            "you to sign in again - you can pick a different account then.",
            ok_label="Yes, disconnect", danger=True,
            on_ok=self._disconnect_start,
        )

    def _disconnect_start(self) -> None:
        ctx = self.ctx
        remote = ctx.config.active_remote
        if self.disconnect_btn:
            self.disconnect_btn.disable()
        ctx.start_job(
            "disconnect",
            lambda hub: ctx.manager.disconnect(
                remote, line_cb=lambda m: hub.log("WARNING", m)),
            on_done=self._disconnect_done,
        )

    def _disconnect_done(self, result: Any, error: Optional[Exception]) -> None:
        ctx = self.ctx
        ctx.finish_job("disconnect")
        if error:
            if self.disconnect_btn:
                self.disconnect_btn.enable()
            ui.notify(f"Disconnect failed: {error}", type="negative",
                      position="top-right")
            return
        inv_path = bk.state_path("inventory.json")
        try:
            inv_path.unlink(missing_ok=True)
        except OSError:
            pass
        ctx.hub.log("SUCCESS", "Google Drive disconnected. Sign in again to "
                               "connect a different account.")
        ui.notify("Google Drive disconnected", type="positive",
                  position="top-right")
        self.refresh()


class BackupPage:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.dir_input: Optional[Any] = None
        self.start_btn: Optional[Any] = None
        self.progress: Optional[Any] = None
        self.progress_label: Optional[Any] = None
        self.summary: Optional[Any] = None
        self.running = False
        self.scope_radio: Optional[Any] = None
        self.folders_input: Optional[Any] = None
        self.skip_input: Optional[Any] = None
        self.files_input: Optional[Any] = None
        self.pick_files: List[str] = []
        self.scope_summary: Optional[Any] = None
        self.refresh_btn: Optional[Any] = None
        self._listing_cb: Optional[Callable[[Any, Any], None]] = None
        self.picker: Optional[Any] = None

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header(
                "cloud_download",
                "Backup",
                "Downloads the files you choose from Google Drive to a local "
                "folder and saves a manifest (paths + checksums) for Verify.")
            info_card(
                "help",
                "What happens when you click Start Backup",
                ["Every file in the scope below is downloaded into the "
                 "destination folder (an empty folder on your PC or an "
                 "external drive).",
                 "Google Docs / Sheets / Slides are exported as docx / xlsx / "
                 "pptx so nothing is lost.",
                 "Afterwards a manifest is saved - Verify and Wipe use it."])
            with ui.card().props("flat bordered").classes("w-full"):
                with ui.row().classes("w-full items-center gap-2"):
                    self.dir_input = ui.input(
                        "Where to save the backup",
                        placeholder="Choose an EMPTY local folder "
                                    "(external drive, NAS, ...)").props(
                        "outlined dense").classes("flex-1")
                    ui.button("Browse", icon="folder_open",
                              on_click=self._browse).props("outline no-caps")

            with ui.card().props("flat bordered").classes("w-full mt-3"):
                ui.label("WHAT TO BACK UP").classes(
                    "text-[10px] font-semibold uppercase tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                self.scope_radio = ui.radio({
                    "all": "Everything in my Google Drive",
                    "only": "Only these folders",
                    "skip": "Everything except folders I list",
                    "files": "Only these files (pick them one by one)",
                }, value="all", on_change=self._scope_changed)\
                    .props("dense").classes("mt-2")
                self.folders_input = ui.textarea(
                    "Folders to back up - one per line, e.g.  Documents  or  "
                    "Photos/2026  (case-sensitive)",
                    placeholder="Documents\nPhotos/2026\nWork/Projects") \
                    .props("outlined dense autogrow").classes(
                    "w-full max-w-xl mt-2").bind_visibility_from(
                    self.scope_radio, "value", value="only")
                self.skip_input = ui.textarea(
                    "Folders to SKIP - one per line (everything else is "
                    "backed up)",
                    placeholder="Videos\nDownloads/temp") \
                    .props("outlined dense autogrow").classes(
                    "w-full max-w-xl mt-2").bind_visibility_from(
                    self.scope_radio, "value", value="skip")
                with ui.row().classes("w-full items-center gap-2 mt-2") \
                        .bind_visibility_from(self.scope_radio, "value",
                                              value="files"):
                    ui.button("Browse & select files", icon="checklist",
                              on_click=self._open_picker).props(
                        "outline no-caps")
                    self.files_input = ui.label("No files selected yet") \
                        .classes("text-sm").style(f"color:{MUTED}")
                self.scope_summary = ui.label("").classes("text-sm mt-2") \
                    .style(f"color:{INFO}")
                with ui.row().classes("items-center gap-2 mt-1"):
                    self.refresh_btn = ui.button("Refresh Drive listing",
                                                 icon="sync",
                                                 on_click=self._refresh_listing) \
                        .props("flat dense no-caps").classes("text-xs")
                    ui.label("The file list comes from your Drive - refresh "
                             "after uploading new files.").classes("text-xs") \
                        .style(f"color:{MUTED}")

            self.start_btn = ui.button("Start Backup", icon="download",
                                       on_click=self._run).props(
                "color=primary size=lg no-caps").classes("w-full mt-4")
            with ui.column().classes("w-full gap-1 mt-3"):
                self.progress = ui.linear_progress(value=0, show_value=False) \
                    .props("color=primary").classes("w-full")
                self.progress_label = ui.label("Idle").classes(
                    "text-xs").style(f"color:{MUTED}")
            self.summary = ui.label("").classes("text-sm").style(f"color:{GOOD}")
            self._scope_changed()

    def _scope_changed(self) -> None:
        self._update_scope_summary()

    def _open_picker(self) -> None:
        inv = bk.load_inventory()
        if self.picker is None:
            self.picker = FilePickerDialog(
                "Select files to back up",
                "Browsing your connected Google Drive account. Click files "
                "to select them; shift-click selects a range; search "
                "filters the list.",
                on_refresh=self._picker_refresh)
        if inv:
            self.picker.open(inv, on_confirm=self._files_picked)
            return
        ui.notify("Fetching your Drive listing ...", type="info",
                  position="top-right")
        self._start_listing(self._open_picker_with)

    def _open_picker_with(self, result: Any, error: Optional[Exception]) -> None:
        if error or not result:
            return
        self.picker.open(result, on_confirm=self._files_picked)

    def _picker_refresh(self, picker: Any) -> None:
        self._start_listing(
            lambda result, error: picker.refresh_done(error, result))

    def _start_listing(self, cb: Optional[Callable[[Any, Any], None]]) -> None:
        ctx = self.ctx
        remote = ctx.config.active_remote
        if not ctx.manager.remote_exists(remote):
            ui.notify("Connect Google Drive first (Dashboard).",
                      type="warning")
            if cb:
                cb(None, "Drive is not connected.")
            return
        self._listing_cb = cb
        if self.refresh_btn:
            self.refresh_btn.disable()
        ctx.start_job(
            "listing-backup",
            lambda hub: ctx.manager.lsjson(remote),
            on_done=self._listing_done,
        )

    def _listing_done(self, result: Any, error: Optional[Exception]) -> None:
        ctx = self.ctx
        ctx.finish_job("listing-backup")
        if self.refresh_btn:
            self.refresh_btn.enable()
        cb, self._listing_cb = self._listing_cb, None
        if error:
            ui.notify(f"Could not read your Drive: {error}", type="negative",
                      position="top-right")
            if cb:
                cb(None, error)
            return
        bk.state_path("inventory.json").write_text(
            _json.dumps(result, indent=1), encoding="utf-8")
        ctx.hub.log("SUCCESS",
                    f"Drive listing refreshed: {len(result)} files")
        ui.notify(f"Listing refreshed: {_fmt(len(result))} files",
                  type="positive", position="top-right")
        if self.pick_files:
            wanted = set(self.pick_files)
            missing = [p for p in self.pick_files
                       if p not in {(f.get("Path") or f.get("Name"))
                                    for f in result}]
            if missing:
                self.pick_files = [p for p in self.pick_files
                                   if p not in set(missing)]
                self.files_input.set_text(
                    f"{_fmt(len(self.pick_files))} files selected - "
                    f"{_fmt(len(missing))} are no longer on Drive and were "
                    "dropped")
        self._update_scope_summary()
        if cb:
            cb(result, None)

    def _files_picked(self, paths: List[str]) -> None:
        self.pick_files = paths
        if paths:
            total = sum(f.get("Size", 0) for f in bk.load_inventory()
                        if (f.get("Path") or f.get("Name")) in set(paths))
            self.files_input.set_text(
                f"{_fmt(len(paths))} files selected ({format_bytes(total)})")
        else:
            self.files_input.set_text("No files selected yet")
        self._update_scope_summary()

    def _refresh_listing(self) -> None:
        self._start_listing(None)

    def _folder_lines(self, widget: Any) -> List[str]:
        return [ln.strip("/ ").strip() for ln in (widget.value or "").splitlines()
                if ln.strip()]

    def _update_scope_summary(self) -> None:
        try:
            scope = self.scope_radio.value
            remote = self.ctx.config.active_remote
            if not self.ctx.manager.remote_exists(remote):
                self.scope_summary.set_text(
                    "Connect Google Drive first (Dashboard) to see what will "
                    "be backed up.")
                return
            inv = bk.load_inventory()
            if not inv:
                self.scope_summary.set_text(
                    "No Drive listing cached yet - the exact file count is "
                    "shown after the first backup. Everything you select "
                    "will be downloaded to the destination folder.")
                return
            from ..engine.backup import _match_folders
            only = self._folder_lines(self.folders_input)
            skip = self._folder_lines(self.skip_input)
            if scope == "files":
                picked = set(self.pick_files)
                files = [f for f in inv
                         if (f.get("Path") or f.get("Name")) in picked]
                label = (f"{_fmt(len(files))} selected files, "
                         f"{format_bytes(sum(f.get('Size', 0) for f in files))}"
                         if files else "No files selected yet")
            elif scope == "only" and only:
                files = [f for f in inv
                         if _match_folders(f.get("Path") or f.get("Name"), only)]
                label = f"Only the selected folders - {len(files)} files, " \
                        f"{format_bytes(sum(f.get('Size', 0) for f in files))}"
            elif scope == "skip" and skip:
                files = [f for f in inv
                         if not _match_folders(f.get("Path") or f.get("Name"),
                                               skip)]
                label = f"Everything except the skipped folders - " \
                        f"{len(files)} files, " \
                        f"{format_bytes(sum(f.get('Size', 0) for f in files))}"
            else:
                files = inv
                label = f"Everything in your Drive - {len(files)} files, " \
                        f"{format_bytes(sum(f.get('Size', 0) for f in files))}"
            self.scope_summary.set_text(f"Scope: {label}")
        except (ValueError, KeyError, AttributeError):
            self.scope_summary.set_text("")

    def _browse(self) -> None:
        path = pick_directory("Choose backup destination")
        if path:
            self.dir_input.value = path

    def _run(self) -> None:
        target = (self.dir_input.value or "").strip()
        if not target:
            ui.notify("Choose a destination folder first.", type="warning")
            return
        remote = self.ctx.config.active_remote
        if not self.ctx.manager.remote_exists(remote):
            ui.notify("Connect Google Drive first (Dashboard).", type="warning")
            return
        scope = self.scope_radio.value
        only = self._folder_lines(self.folders_input) if scope == "only" else []
        skip = self._folder_lines(self.skip_input) if scope == "skip" else []
        files = self.pick_files if scope == "files" else []
        if scope == "only" and not only:
            ui.notify("List at least one folder to back up.", type="warning")
            return
        if scope == "skip" and not skip:
            ui.notify("List at least one folder to skip.", type="warning")
            return
        if scope == "files" and not files:
            ui.notify("Select at least one file to back up.", type="warning")
            return
        cfg = self.ctx.config
        self.running = True
        self.start_btn.disable()
        self.start_btn.set_text("Backing up ...")
        self.progress.props("indeterminate")
        self.ctx.start_job(
            "backup",
            lambda hub: bk.backup(
                remote, target,
                transfers=int(cfg.get("transfers")),
                checkers=int(cfg.get("checkers")),
                line_cb=lambda m: hub.log("INFO", m),
                progress_cb=lambda p, t: hub.progress(p, t),
                include_folders=only or None,
                exclude_folders=skip or None,
                include_files=files or None,
                gphotos_proxy=cfg.get("gphotos_proxy", ""),
            ),
            on_progress=self._on_progress,
            on_done=self._on_done,
        )

    def _on_progress(self, pct: Optional[float], text: str) -> None:
        if pct is not None and pct > 0:
            self.progress.props(remove="indeterminate")
            self.progress.set_value(min(pct, 1.0))
            self.progress_label.set_text(f"{pct * 100:.1f}% - {text}")
        else:
            self.progress_label.set_text(text)

    def _on_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("backup")
        self.running = False
        self.start_btn.enable()
        self.start_btn.set_text("Start Backup")
        self.progress.props(remove="indeterminate")
        self.progress.set_value(0)
        if error:
            ui.notify(f"Backup failed: {error}", type="negative")
            self.progress_label.set_text("Backup failed")
            return
        self.summary.set_text(
            f"Backup complete: {_fmt(result['files'])} files, "
            f"{format_bytes(result['bytes'])} - {result['ok']} present, "
            f"{result['missing']} missing")
        self.progress_label.set_text("Backup complete")
        ui.notify("Backup complete", type="positive", position="top-right")
        self.ctx.hub.log("SUCCESS", f"Backup manifest saved to {result['manifest']}")
        self._update_scope_summary()


class VerifyPage:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.status: Optional[Any] = None
        self.progress: Optional[Any] = None
        self.table: Optional[Any] = None
        self.verify_btn: Optional[Any] = None
        self.deep_btn: Optional[Any] = None
        self.deep = False

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header(
                "fact_check",
                "Verify",
                "Proves your backup really matches Google Drive - the gate "
                "that unlocks Wipe.")
            info_card(
                "fact_check",
                "What Verify does",
                ["Checks every backed-up file (size + checksum) against the "
                 "manifest saved during Backup.",
                 "Nothing is downloaded again and NOTHING on Google Drive is "
                 "touched or changed.",
                 "Wipe stays locked until this passes. Deep check goes one "
                 "step further: it re-downloads files from Drive and compares "
                 "them (extra safety, uses your data allowance)."])
            with ui.card().props("flat bordered").classes("w-full"):
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    self.verify_btn = ui.button("Verify backup", icon="fact_check",
                                                on_click=self._verify).props(
                        "color=primary no-caps")
                    self.deep_btn = ui.button("Deep check (re-download)",
                                              icon="sync", on_click=self._deep).props(
                        "outline no-caps")
                    ui.switch("Download & compare against Drive (slower, extra "
                              "safety)").bind_value(self, "deep").props("dense")

            self.status = ui.label("No verification yet - run 'Verify backup' "
                                   "after your first Backup.").classes(
                "text-sm font-semibold mt-4")
            self.freshness = ui.label("").classes("text-xs mt-1") \
                .style(f"color:{MUTED}")
            with ui.column().classes("w-full gap-1 mt-2"):
                self.progress = ui.linear_progress(value=0, show_value=False) \
                    .props("color=primary").classes("w-full")
            self.table = ui.table(
                columns=[
                    {"name": "path", "label": "File", "field": "path", "sortable": True},
                    {"name": "status", "label": "Status", "field": "status",
                     "sortable": True},
                ],
                rows=[],
                row_key="path",
            ).classes("w-full mt-3")
            self.table.props('flat bordered dense')
            self._show_status()

    def _show_status(self) -> None:
        data = vf.load_verify_result()
        if data:
            color = GOOD if data.get("passed") else DANGER
            label = "PASS" if data.get("passed") else "FAIL"
            self.status.set_text(
                f"{label} at {data.get('created', '?')} - {data.get('matched', 0)} OK, "
                f"{data.get('missing', 0)} missing, {data.get('mismatch', 0)} mismatched")
            self.status.style(f"color: {color}")
            hours = self.ctx.config.get("verify_freshness_hours", 24)
            try:
                from datetime import datetime, timedelta
                created = datetime.fromisoformat(data["created"])
                age = (datetime.now() - created).total_seconds() / 3600
                left = max(0.0, hours - age)
                self.freshness.set_text(
                    f"Result is {age:.1f} hours old - Wipe stays unlocked for "
                    f"another {left:.1f} hours (or re-verify anytime).")
            except (ValueError, KeyError):
                self.freshness.set_text(
                    f"Wipe window: {hours} hours after a passing verify.")
        else:
            self.status.set_text("No verification yet - run 'Verify backup' "
                                 "after your first Backup.")
            self.status.style(f"color: {MUTED}")
            self.freshness.set_text("")

    def _verify(self) -> None:
        self.verify_btn.disable()
        self.verify_btn.set_text("Verifying ...")
        self.progress.props("indeterminate")
        self.ctx.start_job(
            "verify",
            lambda hub: vf.verify_local(
                workers=8,
                progress_cb=lambda p, t: hub.progress(p, t),
                line_cb=lambda m: hub.log("INFO", m),
            ),
            on_progress=self._on_progress,
            on_done=self._verify_done,
        )

    def _on_progress(self, pct: Optional[float], text: str) -> None:
        if pct and pct > 0:
            self.progress.props(remove="indeterminate")
            self.progress.set_value(min(pct, 1.0))

    def _verify_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("verify")
        self.verify_btn.enable()
        self.verify_btn.set_text("Verify backup")
        self.progress.props(remove="indeterminate")
        self.progress.set_value(0)
        if error:
            ui.notify(f"Verification failed: {error}", type="negative")
            return
        rows = [{"path": r["path"], "status": r["status"]}
                for r in result["results"]]
        self.table.update_rows(rows)
        self._show_status()
        if result["passed"]:
            ui.notify("Verification PASSED", type="positive", position="top-right")
            self.ctx.hub.log("SUCCESS", "Verification PASSED")
        else:
            ui.notify("Verification FAILED - do not wipe!", type="negative",
                      position="top-right")
            self.ctx.hub.log("ERROR", "Verification FAILED")
        self.ctx.notify_verify_done()

    def _deep(self) -> None:
        remote = self.ctx.config.active_remote
        manifest = vf.load_manifest_for_verify()
        if not manifest:
            ui.notify("Run a backup first.", type="warning")
            return
        if not self.deep:
            ui.notify("Deep check re-downloads everything. Enable the switch "
                      "to confirm.", type="warning")
            return
        self.deep_btn.disable()
        self.deep_btn.set_text("Deep checking ...")
        self.progress.props("indeterminate")
        cfg = self.ctx.config
        self.ctx.start_job(
            "deepcheck",
            lambda hub: vf.check_remote(
                remote, manifest["local_dir"],
                transfers=int(cfg.get("transfers")),
                checkers=int(cfg.get("checkers")),
                download=True,
                line_cb=lambda m: hub.log("INFO", m),
                gphotos_proxy=cfg.get("gphotos_proxy", ""),
            ),
            on_done=self._deep_done,
        )

    def _deep_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("deepcheck")
        self.deep_btn.enable()
        self.deep_btn.set_text("Deep check (re-download)")
        self.progress.props(remove="indeterminate")
        self.progress.set_value(0)
        if error:
            ui.notify(f"Deep check failed: {error}", type="negative")
            return
        if result["passed"]:
            ui.notify(f"Deep check PASSED: {result['files']} files",
                      type="positive", position="top-right")
        else:
            ui.notify("Deep check FAILED", type="negative", position="top-right")
        self.ctx.hub.log(
            "SUCCESS" if result["passed"] else "ERROR",
            f"Deep check: {result['files']} files, {result['missing']} missing, "
            f"{result['mismatch']} mismatched -> "
            f"{'PASS' if result['passed'] else 'FAIL'}")


class AnalyzePage:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.analysis: Optional[Any] = None
        self.summary_line: Optional[Any] = None
        self.cat_table: Optional[Any] = None
        self.details: Optional[Any] = None

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header(
                "analytics",
                "Analyze",
                "Understand what's in your Drive: duplicates, junk and the "
                "largest files - plus an optional AI report.")
            info_card(
                "analytics",
                "What Analyze does",
                ["Scans your backup listing: file categories, largest files, "
                 "duplicate groups, junk and empty files - all locally, "
                 "nothing leaves your PC.",
                 "With an AI key (Settings) you can also get a plain-language "
                 "summary, a quality check and an organization plan.",
                 "Report saves a full Markdown document to "
                 "%APPDATA%\\DriveBackup\\reports\\ - open it with any text "
                 "editor."])
            with ui.row().classes("w-full items-center gap-2 mb-2 flex-wrap"):
                ui.button("Analyze Drive", icon="analytics",
                          on_click=self._analyze).props("color=primary no-caps")
                ui.button("Generate Report", icon="description",
                          on_click=self._report).props("outline no-caps")
                ui.button("AI Summary", icon="auto_awesome",
                          on_click=self._ai).props("outline no-caps")
                ui.button("AI Quality Check", icon="fact_check",
                          on_click=self._quality).props("outline no-caps")
            self.summary_line = ui.label("Run analysis to see drive health.").classes(
                "text-sm font-semibold").style(f"color:{MUTED}")
            self.cat_table = ui.table(
                columns=[
                    {"name": "cat", "label": "Category", "field": "cat", "sortable": True},
                    {"name": "count", "label": "Files", "field": "count", "sortable": True},
                    {"name": "size", "label": "Size", "field": "size", "sortable": True},
                ],
                rows=[],
                row_key="cat",
            ).classes("w-full mt-3")
            self.cat_table.props("flat bordered dense")
            self.details = ui.markdown("").classes("w-full mt-2")

    def _ai_settings(self) -> tuple:
        return (self.ctx.config.get("gemini_api_key"),
                self.ctx.config.get("ai_provider", "gemini"),
                self.ctx.config.get("ai_model") or None)

    def _analyze(self) -> None:
        key, provider, model = self._ai_settings()
        self.ctx.start_job(
            "analyze",
            lambda hub: ai_analyzer.analyze(key, provider=provider,
                                            model=model),
            on_done=self._analyze_done,
        )

    def _analyze_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("analyze")
        if error:
            ui.notify(f"Analysis failed: {error}", type="negative")
            return
        self.analysis = result
        self.ctx.hub.log("SUCCESS", "Analysis complete.")
        if result.get("ai_classified"):
            self.ctx.hub.log("INFO",
                             f"AI classified {result['ai_classified']} files "
                             "the rules could not.")
        ui.notify("Analysis complete", type="positive", position="top-right")
        self._render(result)

    def _render(self, a: Any) -> None:
        self.summary_line.set_text(
            f"{_fmt(a['count'])} files, {format_bytes(a['size'])} | "
            f"{a['dup_count']} duplicate groups | {format_bytes(a['junk_size'])} junk")
        self.summary_line.style(f"color: {GOOD}")
        self.cat_table.update_rows([
            {"cat": k, "count": _fmt(v["count"]), "size": format_bytes(v["size"])}
            for k, v in sorted(a["categories"].items(), key=lambda kv: -kv[1]["size"])
        ])
        lines = ["### Top 10 largest files"]
        for f in a["top_files"][:10]:
            lines.append(f"- `{format_bytes(f['size']):>10}`  {f['path']}")
        lines.append("")
        lines.append(f"### Duplicates\n- **{a['dup_count']} groups**, "
                     f"**{format_bytes(a['dup_wasted'])}** wasted space")
        for d in a.get("duplicates", [])[:10]:
            lines.append(f"- {format_bytes(d['size'])} x{len(d['paths'])}: "
                         f"{', '.join(d['paths'][:3])}")
        lines.append("")
        lines.append(f"### Junk & empty files\n- Junk: "
                     f"{format_bytes(a['junk_size'])} across "
                     f"{len(a['junk'])} categories")
        lines.append(f"- Empty files: {len(a['empty_files'])}")
        for label, paths in a.get("junk", {}).items():
            for p in paths[:5]:
                lines.append(f"- `{label}`: {p}")
        self.details.set_content("\n".join(lines))

    def _report(self) -> None:
        ctx = self.ctx
        if not self.analysis:
            ui.notify("Run analysis first (it will be included in the report).",
                      type="warning")
            return
        verify = vf.load_verify_result()
        key, provider, model = self._ai_settings()
        ctx.start_job(
            "report",
            lambda hub: _write_report(ctx, verify, self.analysis,
                                      key, provider=provider, model=model),
            on_done=self._report_done,
        )

    def _report_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("report")
        if error:
            ui.notify(f"Report failed: {error}", type="negative")
            return
        ui.notify(f"Report saved: {result}", type="positive", position="top-right",
                  multi_line=True)

    def _ai(self) -> None:
        key, provider, model = self._ai_settings()
        if not key:
            ui.notify("No AI key. Get a FREE Gemini key (no credit card) at "
                      "aistudio.google.com/apikey or use an OpenRouter key, "
                      "then add it in Settings.",
                      type="warning", position="top-right", multi_line=True)
            return
        if not self.analysis:
            ui.notify("Run analysis first.", type="warning")
            return
        self.ctx.start_job(
            "ai",
            lambda hub: llm.summarize(key, self.analysis,
                                      provider=provider, model=model),
            on_done=self._ai_done,
        )

    def _ai_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("ai")
        if error:
            ui.notify(f"AI summary failed: {error}", type="negative")
            return
        self.details.set_content(f"## AI Summary\n\n{result}")
        ui.notify("AI summary ready", type="positive", position="top-right")

    def _quality(self) -> None:
        ctx = self.ctx
        key, provider, model = self._ai_settings()
        if not key:
            ui.notify("No AI key. Get a FREE Gemini key (no credit card) at "
                      "aistudio.google.com/apikey or use an OpenRouter key, "
                      "then add it in Settings.",
                      type="warning", position="top-right", multi_line=True)
            return
        if not self.analysis:
            ui.notify("Run analysis first.", type="warning")
            return
        ctx.start_job(
            "ai",
            lambda hub: ai_analyzer.quality_check(
                key, self.analysis, vf.load_verify_result(),
                provider=provider, model=model),
            on_done=self._quality_done,
        )

    def _quality_done(self, result: Any, error: Optional[Exception]) -> None:
        self.ctx.finish_job("ai")
        if error:
            ui.notify(f"AI quality check failed: {error}", type="negative")
            return
        if not result:
            ui.notify("No findings - drive looks healthy (or AI returned "
                      "nothing usable).", type="positive", position="top-right")
            return
        colors = {"high": DANGER, "medium": "#F59E0B", "low": INFO}
        lines = ["## AI Findings"]
        for f in result:
            lines.append(f"- **{f['severity'].upper()}** *({colors[f['severity']]})*: "
                         f"{f['message']}")
        self.details.set_content("\n".join(lines))
        ui.notify(f"{len(result)} findings", type="warning", position="top-right")


def _write_report(ctx: Any, verify: Any, analysis: Any, gemini_key: str = "",
                  provider: str = "gemini", model: Optional[str] = None) -> str:
    plan = ai_analyzer.organization_plan(gemini_key, provider=provider,
                                         model=model)
    findings: List[Any] = []
    if gemini_key:
        findings = ai_analyzer.quality_check(gemini_key, analysis, verify,
                                             provider=provider, model=model)
    content = generate_report(None, verify, analysis, plan,
                              ai_findings=findings)
    path = save_report(content)
    ctx.hub.log("SUCCESS", f"Report saved: {path}")
    return path


class WipePage:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.gate: Optional[Any] = None
        self.phrase: Optional[Any] = None
        self.checkbox: Optional[Any] = None
        self.trash_btn: Optional[Any] = None
        self.empty_btn: Optional[Any] = None
        self.purge_btn: Optional[Any] = None
        self.inv_table: Optional[Any] = None
        self.inv_summary: Optional[Any] = None
        self.wipe_files: List[str] = []
        self.wipe_scope_label: Optional[Any] = None
        self.picker: Optional[Any] = None
        self._listing_cb: Optional[Callable[[Any, Any], None]] = None

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header(
                "delete_forever",
                "Wipe",
                "Deletes the files on your Google Drive - only after your "
                "backup is verified.")

            # Google Photos API hard block
            svc = self.ctx.config.get("active_service", "drive")
            if svc == "photos":
                with ui.card().props("flat bordered").classes("w-full p-4 mt-4") \
                        .style("border-color: rgba(244,180,0,0.5);"):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon("block").classes("text-4xl").style(
                            f"color:{WARN}")
                        with ui.column().classes("gap-1"):
                            ui.label("Wipe is not available for Google Photos") \
                                .classes("text-lg font-semibold").style(
                                f"color:{WARN}")
                            ui.label(
                                "Google's API explicitly prohibits third-party apps "
                                "from deleting media from Google Photos. "
                                "Switch to Google Drive on the Dashboard to use Wipe."
                            ).classes("text-sm").style(f"color:{MUTED}")
                return
            info_card(
                "delete_forever",
                "What Wipe deletes",
                ["By default EVERYTHING on your Google Drive that you backed "
                 "up. You can also select individual files below.",
                 "Only Google Drive is affected - Gmail, Contacts and Photos "
                 "are NOT touched.",
                 "Files others shared with you are only removed from your "
                 "view, not deleted.",
                 "Wipe is a safety-gated 2-step flow: 1) files move to the "
                 "Trash (recoverable), 2) you empty the Trash (permanent)."],
                tone="danger")
            with ui.row().classes("w-full items-center gap-2 mt-2 flex-wrap"):
                ui.button("Preview Drive contents", icon="list",
                          on_click=self._show_inventory).props(
                    "outline no-caps")
                ui.button("Select files to wipe", icon="checklist",
                          on_click=self._pick_files).props("outline no-caps")
            self.wipe_scope_label = ui.label("") \
                .classes("text-xs mt-1").style(f"color:{INFO}")
            self.inv_summary = ui.label("").classes("text-xs mt-1") \
                .style(f"color:{MUTED}")
            self.inv_table = ui.table(
                columns=[
                    {"name": "path", "label": "File / folder path",
                     "field": "path", "sortable": True},
                    {"name": "size", "label": "Size", "field": "size",
                     "sortable": True},
                ],
                rows=[],
                row_key="path",
            ).classes("w-full mt-2")
            self.inv_table.props('flat bordered dense')
            self.inv_table.set_visibility(False)
            with ui.card().classes("w-full mt-2").props("flat bordered") \
                    .style("border-color: rgba(220,38,38,0.45)"):
                with ui.row().classes("w-full items-center gap-3 p-1"):
                    ui.icon("warning").classes("text-3xl") \
                        .style(f"color:{DANGER}")
                    ui.label("The dangerous part").classes(
                        "text-lg font-semibold").style(f"color:{DANGER}")

            self.gate = ui.label("").classes("text-sm font-semibold mt-4")
            ui.label("Type the confirmation phrase to unlock:  DELETE ALL").classes(
                "text-sm mt-2").style(f"color:{MUTED}")
            self.phrase = ui.input("Confirmation phrase", password=True,
                                   password_toggle_button=True,
                                   placeholder="DELETE ALL",
                                   on_change=self._update_buttons).props(
                "outlined").classes("w-full max-w-md")
            self.checkbox = ui.checkbox("I verified the backup: every file exists "
                                        "locally and passed checksum verification",
                                        on_change=self._update_buttons)
            with ui.row().classes("w-full items-center gap-2 mt-2 flex-wrap"):
                self.trash_btn = ui.button("1. Move to Trash", icon="delete",
                                           on_click=self._trash).props(
                    "color=warning no-caps")
                self.empty_btn = ui.button("2. Empty Trash", icon="delete_forever",
                                           on_click=self._empty).props(
                    "color=warning no-caps")
                self.purge_btn = ui.button("ADVANCED: Permanent delete (no Trash)",
                                           icon="delete_sweep",
                                           on_click=self._purge).props(
                    "color=negative no-caps")
            self._update_gate()
            self.ctx.after_verify.append(self._update_gate)
            self.wipe_scope_label.set_text(
                "Wipe scope: ALL files on your Google Drive (default).")

    def _show_inventory(self) -> None:
        inv = bk.load_inventory()
        if not inv:
            ui.notify("No Drive listing yet - run a Backup first "
                      "(the listing is captured during Backup).",
                      type="warning", position="top-right")
            self.inv_table.set_visibility(False)
            self.inv_summary.set_text("")
            return
        rows = [{"path": f.get("Path") or f.get("Name"),
                 "size": format_bytes(f.get("Size", 0))} for f in inv]
        self.inv_table.update_rows(rows)
        self.inv_table.set_visibility(True)
        total = sum(f.get("Size", 0) for f in inv)
        if self.wipe_files:
            picked = set(self.wipe_files)
            total = sum(f.get("Size", 0) for f in inv
                        if (f.get("Path") or f.get("Name")) in picked)
            self.inv_summary.set_text(
                f"{_fmt(len(self.wipe_files))} files selected "
                f"({format_bytes(total)}) - 'Move to Trash' will only touch "
                "these.")
        else:
            self.inv_summary.set_text(
                f"{_fmt(len(inv))} files, {format_bytes(total)} - these are the "
                "files 'Move to Trash' will delete from your Drive.")
        ui.notify(f"{len(rows)} files in scope", type="info", position="top-right")

    def _pick_files(self) -> None:
        inv = bk.load_inventory()
        if self.picker is None:
            self.picker = FilePickerDialog(
                "Select files to wipe",
                "Browsing your connected Google Drive account. Only these "
                "files will be deleted (still goes through Trash and the "
                "safety gates). Shift-click selects a range.",
                on_refresh=self._picker_refresh)
        if inv:
            self.picker.open(inv, on_confirm=self._files_picked)
            return
        ui.notify("Fetching your Drive listing ...", type="info",
                  position="top-right")
        self._start_listing(self._open_picker_with)

    def _open_picker_with(self, result: Any, error: Optional[Exception]) -> None:
        if error or not result:
            return
        self.picker.open(result, on_confirm=self._files_picked)

    def _picker_refresh(self, picker: Any) -> None:
        self._start_listing(
            lambda result, error: picker.refresh_done(error, result))

    def _start_listing(self, cb: Optional[Callable[[Any, Any], None]]) -> None:
        ctx = self.ctx
        remote = ctx.config.active_remote
        if not ctx.manager.remote_exists(remote):
            ui.notify("Connect Google Drive first (Dashboard).",
                      type="warning")
            if cb:
                cb(None, "Drive is not connected.")
            return
        self._listing_cb = cb
        ctx.start_job(
            "listing-wipe",
            lambda hub: ctx.manager.lsjson(remote),
            on_done=self._listing_done,
        )

    def _listing_done(self, result: Any, error: Optional[Exception]) -> None:
        ctx = self.ctx
        ctx.finish_job("listing-wipe")
        cb, self._listing_cb = self._listing_cb, None
        if error:
            ui.notify(f"Could not read your Drive: {error}", type="negative",
                      position="top-right")
            if cb:
                cb(None, error)
            return
        bk.state_path("inventory.json").write_text(
            _json.dumps(result, indent=1), encoding="utf-8")
        ctx.hub.log("SUCCESS",
                    f"Drive listing refreshed: {len(result)} files")
        if cb:
            cb(result, None)

    def _files_picked(self, paths: List[str]) -> None:
        self.wipe_files = paths
        if paths:
            inv = bk.load_inventory()
            picked = set(paths)
            total = sum(f.get("Size", 0) for f in inv
                        if (f.get("Path") or f.get("Name")) in picked)
            self.wipe_scope_label.set_text(
                f"Wipe scope: {_fmt(len(paths))} selected files "
                f"({format_bytes(total)}) - only these will be deleted.")
        else:
            self.wipe_scope_label.set_text(
                "Wipe scope: ALL files on your Google Drive (default).")

    def _update_gate(self) -> None:
        ok, msg = vf.verify_fresh(hours=self.ctx.config.get("verify_freshness_hours", 24))
        color = GOOD if ok else DANGER
        self.gate.set_text(f"Safety gate: {msg}")
        self.gate.style(f"color: {color}")
        self._update_buttons()

    def _update_buttons(self) -> None:
        if not self.phrase or not self.checkbox:
            return
        phrase_ok = (self.phrase.value or "").strip().upper() == "DELETE ALL"
        enabled = bool(self.checkbox.value) and phrase_ok
        for b in (self.trash_btn, self.empty_btn, self.purge_btn):
            if b is None:
                continue
            if enabled:
                b.enable()
            else:
                b.disable()

    def _gate_check(self) -> str:
        cfg = self.ctx.config
        wp.require_fresh_verification(cfg)
        wp.require_confirmation(self.phrase.value or "")
        if not self.checkbox.value:
            raise wp.SafetyGateError("You must tick the verification checkbox.")
        remote = cfg.active_remote
        if not self.ctx.manager.remote_exists(remote):
            raise wp.SafetyGateError("Drive remote is not connected.")
        return remote

    def _trash(self) -> None:
        self._run("trash")

    def _empty(self) -> None:
        self._run("emptytrash")

    def _purge(self) -> None:
        self._run("purge")

    def _run(self, action: str) -> None:
        try:
            remote = self._gate_check()
        except wp.SafetyGateError as exc:
            ui.notify(str(exc), type="negative", position="top-right")
            return
        n = len(self.wipe_files)
        scope = f"{n} selected files" if n else "ALL files on your Drive"
        labels = {
            "trash": ("Move to Trash",
                      f"This moves {scope} into the Trash. "
                      "They stay recoverable there."),
            "emptytrash": ("Empty Trash",
                           "This PERMANENTLY deletes everything in your Drive "
                           "Trash. Files cannot be recovered afterwards."),
            "purge": ("Permanent delete",
                      f"ADVANCED: permanently deletes {scope} WITHOUT sending "
                      "them to Trash. There is NO recovery."),
        }
        title, message = labels[action]
        confirm_dialog(
            title, message, ok_label=f"Yes, {title}",
            danger=action != "trash",
            on_ok=lambda: self._start(action, remote),
        )

    def _start(self, action: str, remote: str) -> None:
        jobs = {
            "trash": wp.move_to_trash,
            "emptytrash": wp.empty_trash,
            "purge": wp.purge_forever,
        }
        fn = jobs[action]
        files = self.wipe_files or None
        self.ctx.start_job(
            action,
            lambda hub: fn(remote, line_cb=lambda m: hub.log("WARNING", m),
                           files=files),
            on_done=self._done(action),
        )

    def _done(self, action: str) -> Callable[[Any, Optional[Exception]], None]:
        def handler(result: Any, error: Optional[Exception]) -> None:
            self.ctx.finish_job(action)
            if error:
                ui.notify(f"Wipe step failed: {error}", type="negative",
                          position="top-right")
                return
            ui.notify(f"{action} done", type="positive", position="top-right")
        return handler


class SettingsPage:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.transfers: Optional[Any] = None
        self.checkers: Optional[Any] = None
        self.hours: Optional[Any] = None
        self.gemini: Optional[Any] = None
        self.github_owner: Optional[Any] = None
        self.github_repo: Optional[Any] = None
        self.check_btn: Optional[Any] = None

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header("settings", "Settings",
                        "Tune the engine, add your AI key, and manage updates.")
            with ui.card().classes("w-full max-w-xl").props("flat bordered"):
                ui.label("Engine").classes("text-[10px] font-semibold uppercase "
                                           "tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                with ui.element("div").classes(
                        "w-full grid grid-cols-1 sm:grid-cols-2 gap-x-6 "
                        "gap-y-3 mt-2"):
                    self.transfers = ui.number("Parallel downloads (transfers)",
                                               value=self.ctx.config.get("transfers"),
                                               min=1, max=16, step=1).props("outlined dense")
                    self.checkers = ui.number("Parallel checks (checkers)",
                                              value=self.ctx.config.get("checkers"),
                                              min=1, max=32, step=1).props("outlined dense")
                    self.hours = ui.number("Verify freshness window (hours)",
                                           value=self.ctx.config.get(
                                               "verify_freshness_hours"),
                                           min=1, max=720, step=1).props("outlined dense")
                    self.gemini = ui.input("AI API key (your own - required for "
                                           "AI features)",
                                           value=self.ctx.config.get(
                                               "gemini_api_key", ""),
                                           password=True).props("outlined dense")
                    self.provider = ui.select(
                        {"gemini": "Gemini (free tier - no card)",
                         "openrouter": "OpenRouter"},
                        value=self.ctx.config.get("ai_provider", "gemini"),
                        label="AI provider").props("outlined dense")
                    self.model = ui.input(
                        "AI model (optional - blank = provider default)",
                        value=self.ctx.config.get("ai_model", ""),
                        placeholder="gemini-2.5-flash / openrouter/auto")\
                        .props("outlined dense")
                with ui.row().classes("w-full items-center gap-4 mt-1"):
                    ui.link("Get a free Gemini key",
                            "https://aistudio.google.com/apikey",
                            new_tab=True).classes("text-xs")
                    ui.link("OpenRouter keys", "https://openrouter.ai/keys",
                            new_tab=True).classes("text-xs")
                ui.button("Save settings", icon="save", on_click=self._save)\
                    .props("color=primary no-caps").classes("mt-3")

            with ui.card().classes("w-full max-w-xl").props("flat bordered"):
                ui.label("Google Photos").classes("text-[10px] font-semibold uppercase "
                                                  "tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                ui.label("Google Photos API delivers compressed images by default. "
                         "To download original quality, run the gphotosdl proxy "
                         "alongside rclone.").classes("text-sm").style(f"color:{MUTED}")
                self.gphotos_proxy = ui.input(
                    "gphotosdl proxy URL (blank = use Google API defaults)",
                    value=self.ctx.config.get("gphotos_proxy", ""),
                    placeholder="http://localhost:8282")\
                    .props("outlined dense").classes("w-full mt-2")
                with ui.row().classes("w-full items-center gap-4 mt-1"):
                    ui.link("gphotosdl setup instructions",
                            "https://github.com/rclone/gphotosdl",
                            new_tab=True).classes("text-xs")

            with ui.card().classes("w-full max-w-xl").props("flat bordered"):
                ui.label("Updates").classes("text-[10px] font-semibold uppercase "
                                            "tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                ui.label("Updates install in place - no uninstall needed. "
                         "Your settings and Drive connection are kept.").classes(
                    "text-sm").style(f"color:{MUTED}")
                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    self.github_owner = ui.input(
                        "GitHub owner (user or org)",
                        value=self.ctx.config.get("github_owner", ""))\
                        .props("outlined dense").classes("flex-1")
                    self.github_repo = ui.input(
                        "GitHub repository name",
                        value=self.ctx.config.get("github_repo", ""))\
                        .props("outlined dense").classes("flex-1")
                self.auto_update = ui.select(
                    {"prompt": "Ask me on startup (recommended)",
                     "silent": "Install automatically without asking",
                     "off": "Only when I click 'Check for updates'"},
                    value=self.ctx.config.get("auto_update", "prompt"),
                    label="Automatic updates").props("outlined dense")\
                    .classes("mt-2 w-full")
                ui.label("On startup the app checks GitHub and, if a newer "
                         "release exists, updates from GitHub directly - no "
                         "manual installs needed.").classes("text-xs") \
                    .style(f"color:{MUTED}").classes("mt-1")
                self.check_btn = ui.button("Check for updates", icon="update",
                                           on_click=self._run_update_check)\
                    .props("color=primary no-caps").classes("mt-2")
                ui.label(f"Current version: v{APP_VERSION}").classes(
                    "text-xs").style(f"color:{MUTED}").classes("mt-1")

            with ui.card().classes("w-full max-w-xl").props("flat bordered"):
                ui.label("About").classes("text-[10px] font-semibold uppercase "
                                          "tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                try:
                    version = self.ctx.manager.version()
                except (OSError, FileNotFoundError, AttributeError):
                    version = "not installed"
                ui.label(f"rclone engine: {version}").classes("text-sm")
                ui.label(f"State folder: {state_path('')}").classes(
                    "text-xs").style(f"color:{MUTED}")
                ui.button("Open state folder", icon="folder_open",
                          on_click=lambda: open_in_explorer(str(state_path(""))))\
                    .props("outline no-caps").classes("mt-2")

    def _run_update_check(self) -> None:
        owner = (self.github_owner.value or "").strip()
        repo = (self.github_repo.value or "").strip()
        if not owner or not repo:
            ui.notify("Enter your GitHub owner and repository first.",
                      type="warning", position="top-right")
            return
        cfg = self.ctx.config
        cfg.set("github_owner", owner)
        cfg.set("github_repo", repo)
        self.check_btn.disable()

        def fn(hub: Any) -> Any:
            hub.log("INFO", f"Checking for updates from {owner}/{repo} ...")
            info, err = check_for_update(owner, repo)
            if err:
                hub.log("WARNING", err)
                return None
            if info is None:
                hub.log("SUCCESS",
                        f"You are on the latest version (v{APP_VERSION}).")
                return None
            hub.log("INFO",
                    f"Update found: v{info.version} (you have v{APP_VERSION}).")
            return info

        self.ctx.start_job("update-check", fn,
                           on_done=lambda r, e: self._on_update_check(r, e))

    def _on_update_check(self, result: Any, error: Optional[Exception]) -> None:
        self.check_btn.enable()
        if error:
            ui.notify(f"Update check failed: {error}", type="negative",
                      position="top-right")
            return
        if result is None:
            return
        info = result
        ui.notify(f"DriveBackup v{info.version} is available!",
                  type="info", position="top-right")
        confirm_dialog(
            "Update available",
            f"DriveBackup v{info.version} is available (you have "
            f"v{APP_VERSION}). Download and install now?",
            ok_label="Update now",
            on_ok=lambda: apply_update(self.ctx, info),
        )

    def _save(self) -> None:
        cfg = self.ctx.config
        try:
            cfg.set("transfers", max(1, min(16, int(self.transfers.value))))
            cfg.set("checkers", max(1, min(32, int(self.checkers.value))))
            cfg.set("verify_freshness_hours",
                    max(1, min(720, int(self.hours.value))))
        except (TypeError, ValueError):
            ui.notify("Transfers/checkers/hours must be numbers.", type="warning")
            return
        cfg.set("gemini_api_key", (self.gemini.value or "").strip())
        cfg.set("ai_provider",
                (self.provider.value or "gemini").strip())
        cfg.set("ai_model", (self.model.value or "").strip())
        cfg.set("auto_update",
                (self.auto_update.value or "prompt").strip())
        cfg.set("gphotos_proxy", (self.gphotos_proxy.value or "").strip())
        self.ctx.hub.log("SUCCESS", "Settings saved.")
        ui.notify("Settings saved", type="positive", position="top-right")


class HelpPage:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def build(self, parent: Optional[Any] = None) -> None:
        with parent or nullcontext():
            page_header("help", "Help & Guide",
                        "Everything you need to master DriveBackup, visually explained.")
            
            with ui.card().classes("w-full max-w-4xl hover-lift").props("flat bordered"):
                ui.markdown('''
### The 5-Step Journey

Master the safety-first workflow of DriveBackup.

| Step | Action | Description |
| :--- | :--- | :--- |
| 1. Connect | **Dashboard** | Securely link your Google Drive or Google Photos. We only get access, never your password. |
| 2. Back up | **Backup tab** | Select an empty local folder. We download your files and create a secure manifest. |
| 3. Verify | **Verify tab** | *The Safety Gate.* We check that every local file exactly matches the cloud version. |
| 4. Analyze | **Analyze tab** | Discover duplicates, large files, and junk. Integrate AI for deeper insights. |
| 5. Wipe | **Wipe tab** | *Locked until verified.* Move everything to Drive Trash safely, then empty it forever. |
''').classes("w-full")

            with ui.card().classes("w-full max-w-4xl mt-4 hover-lift").props("flat bordered"):
                ui.markdown('''
### Google Drive vs Google Photos

DriveBackup supports both Google Drive and Google Photos.

**Google Drive:** Full backup, verify, and wipe support. Files are downloaded at original quality with MD5 verification.

**Google Photos:** Backup and analyze work. However, **Google Photos API prohibits third-party deletion**, so the Wipe tab is locked when Photos is active. Downloads may be slightly compressed by Google's API.

**Original Quality Photos:** To download original quality images, run the [gphotosdl proxy](https://github.com/rclone/gphotosdl) alongside rclone, then configure the proxy URL in **Settings > Google Photos**.
''').classes("w-full")

            with ui.card().classes("w-full max-w-4xl mt-4 hover-lift").props("flat bordered"):
                ui.markdown('''
### Common Questions & Security

**Is my data actually safe?**
Yes. Everything stays on your local PC. The only exception is if you explicitly enable the optional AI features, which send file metadata (names and sizes, not the contents) to the AI provider you configured.

**Does Wipe touch my Gmail or Google Photos?**
No. Wipe is strictly scoped to Google Drive files. Google Photos cannot be wiped via the API.

**What happens to files shared with me?**
Wipe simply removes them from your view. It does not delete the original files owned by others.

**How do updates work?**
The app checks GitHub for updates on startup. You can also manually check in Settings > Updates. Updates install in place — your settings and Google connection are preserved.
''').classes("w-full")

            with ui.card().classes("w-full max-w-4xl mt-4 hover-lift").props("flat bordered"):
                ui.markdown(f'''
### Data Locations

Knowing where your data lives is key to staying organized.

- **App config & tokens:** `{str(state_path("").parent)}`
- **Manifest & verify results:** `{str(state_path(""))}`
- **Reports:** `{str(state_path("").parent / "reports")}`
- **Default Backup Folder:** `{str(Path.home() / "DriveBackup")}` *(You can change this on the Backup tab)*
''').classes("w-full")

            with ui.card().classes("w-full max-w-4xl mt-4 hover-lift").props("flat bordered"):
                ui.markdown('''
### Troubleshooting Guide

- **Connection failing?** Sign out of Google in your browser and try again. Or try Settings > Updates > reconnect.
- **Folder must be empty?** DriveBackup refuses to mix backups to prevent data corruption. Select a brand new folder.
- **Verify keeps failing?** Delete the specific failing file locally and re-run Backup. It will seamlessly resume and fix the manifest.
- **SmartScreen warning?** This is normal for unsigned apps. Click "More info" > "Run anyway". Only fix is a paid code-signing cert.
- **App won't update?** Close the app, then run the new installer manually. It will upgrade in place.
- **Still stuck?** Check the log at `%APPDATA%\\DriveBackup\\app.log` for detailed technical traces.
''').classes("w-full")
