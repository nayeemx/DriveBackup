from contextlib import nullcontext
import tempfile
from pathlib import Path

from nicegui import ui

from .widgets import (ACCENT, DANGER, GOOD, INFO, MUTED, PRIMARY, WARN,
                      LogConsole, PipelineChips, StatCard, confirm_dialog,
                      open_in_explorer, page_header, pick_directory)

from ..ai import analyzer as ai_analyzer
from ..ai import llm
from ..ai.report import generate_report, save_report
from ..engine import backup as bk
from ..engine import verify as vf
from ..engine import wipe as wp
from ..utils.config import format_bytes, state_path
from ..utils.updater import (UpdateError, check_for_update, download,
                             install_silently, launch_installed)
from ..utils.version import APP_VERSION


def _fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


class DashboardPage:
    def __init__(self, ctx, navigate):
        self.ctx = ctx
        self.navigate = navigate
        self.stats = {}

    def build(self, parent=None):
        with parent or nullcontext():
            page_header(
                "cloud_download",
                "Google Drive Backup",
                "Back up everything, verify it, then safely wipe your Drive - "
                "with AI analysis in between.")
            with ui.row().classes("w-full items-center gap-2 mb-4"):
                ui.button("Connect Google Drive", icon="link",
                          on_click=self._connect).props("color=primary no-caps")
                ui.button("Refresh", icon="refresh", on_click=self.refresh)\
                    .props("outline no-caps")

            ui.label("Your journey").classes("text-[10px] font-semibold uppercase "
                                             "tracking-[0.16em]") \
                .style(f"color:{MUTED}")
            PipelineChips(self.ctx, on_navigate=self._step_to)

            with ui.grid(columns=3).classes("w-full gap-3 mt-4"):
                self.stats["state"] = StatCard("Connection", "-", "cloud_off", MUTED)
                self.stats["total"] = StatCard("Total", "-", "storage", ACCENT)
                self.stats["used"] = StatCard("Used", "-", "pie_chart", WARN)
                self.stats["free"] = StatCard("Free", "-", "check_circle", GOOD)
                self.stats["backed"] = StatCard("Backed up", "-", "folder_copy",
                                                PRIMARY)
                self.stats["files"] = StatCard("Files", "-", "description", INFO)
            self.refresh()

    def _step_to(self, step):
        mapping = {"Connect": "Dashboard", "Backup": "Backup", "Verify": "Verify",
                   "Analyze": "Analyze", "Wipe": "Wipe"}
        self.navigate(mapping.get(step, "Dashboard"))

    def refresh(self):
        ctx = self.ctx
        remote = ctx.config.get("remote")
        connected = ctx.manager.remote_exists(remote)
        if not connected:
            self.stats["state"].set("Not connected", MUTED)
            self.stats["total"].set("-")
            self.stats["used"].set("-")
            self.stats["free"].set("-")
            ctx.hub.log("WARNING", "Drive not connected - click 'Connect Google Drive'.")
        else:
            self.stats["state"].set("Connected", GOOD)
            try:
                about = ctx.manager.about(remote)
                for key, stat in (("Total", "total"), ("Used", "used"),
                                  ("Free", "free")):
                    if key in about:
                        self.stats[stat].set(about[key])
            except Exception as exc:
                ctx.hub.log("ERROR", f"Could not read drive stats: {exc}")
        inv = bk.load_inventory()
        if inv:
            total = sum(f.get("Size", 0) for f in inv)
            self.stats["files"].set(f"{_fmt(len(inv))}")
            self.stats["backed"].set(format_bytes(total))
        else:
            self.stats["files"].set("0")
            self.stats["backed"].set("-")

    def _connect(self):
        ctx = self.ctx
        ctx.start_job(
            "connect",
            lambda hub: ctx.manager.connect(
                ctx.config.get("remote"),
                ctx.config.get("export_formats"),
                auth_cb=lambda url: hub.ask_auth_url(url),
                code_cb=lambda: hub.ask_code(),
            ),
            on_done=self._connect_done,
        )

    def _connect_done(self, result, error):
        self.ctx.finish_job("connect")
        if error:
            ui.notify(f"Connection failed: {error}", type="negative",
                      position="top-right")
            return
        self.ctx.hub.log("SUCCESS", "Google Drive connected.")
        ui.notify("Google Drive connected", type="positive", position="top-right")
        self.refresh()


class BackupPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.dir_input = None
        self.start_btn = None
        self.progress = None
        self.progress_label = None
        self.summary = None
        self.running = False

    def build(self, parent=None):
        with parent or nullcontext():
            page_header(
                "cloud_download",
                "Backup",
                "Every file and folder on Google Drive is downloaded here, then a "
                "manifest (paths + checksums) is saved. Google Docs / Sheets / "
                "Slides are exported (docx / xlsx / pptx) so nothing is lost.")
            with ui.card().props("flat bordered").classes("w-full"):
                with ui.row().classes("w-full items-center gap-2"):
                    self.dir_input = ui.input(
                        "Backup destination",
                        placeholder="Choose an EMPTY local folder "
                                    "(external drive, NAS, ...)").props(
                        "outlined dense").classes("flex-1")
                    ui.button("Browse", icon="folder_open",
                              on_click=self._browse).props("outline no-caps")

            self.start_btn = ui.button("Start Backup", icon="download",
                                       on_click=self._run).props(
                "color=primary size=lg no-caps").classes("w-full mt-4")
            with ui.column().classes("w-full gap-1 mt-3"):
                self.progress = ui.linear_progress(value=0, show_value=False) \
                    .props("color=primary").classes("w-full")
                self.progress_label = ui.label("Idle").classes(
                    "text-xs").style(f"color:{MUTED}")
            self.summary = ui.label("").classes("text-sm").style(f"color:{GOOD}")

    def _browse(self):
        path = pick_directory("Choose backup destination")
        if path:
            self.dir_input.value = path

    def _run(self):
        target = (self.dir_input.value or "").strip()
        if not target:
            ui.notify("Choose a destination folder first.", type="warning")
            return
        remote = self.ctx.config.get("remote")
        if not self.ctx.manager.remote_exists(remote):
            ui.notify("Connect Google Drive first (Dashboard).", type="warning")
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
            ),
            on_progress=self._on_progress,
            on_done=self._on_done,
        )

    def _on_progress(self, pct, text):
        if pct is not None and pct > 0:
            self.progress.props(remove="indeterminate")
            self.progress.set_value(pct / 100)
            self.progress_label.set_text(f"{pct}% - {text}")
        else:
            self.progress_label.set_text(text)

    def _on_done(self, result, error):
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


class VerifyPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.status = None
        self.progress = None
        self.table = None
        self.verify_btn = None
        self.deep_btn = None
        self.deep = False

    def build(self, parent=None):
        with parent or nullcontext():
            page_header(
                "fact_check",
                "Verify",
                "Compares every backed-up file against the manifest "
                "(size + MD5 checksum). Nothing on Google Drive is touched "
                "by this step.")
            with ui.card().props("flat bordered").classes("w-full"):
                with ui.row().classes("items-center gap-2"):
                    self.verify_btn = ui.button("Verify backup", icon="fact_check",
                                                on_click=self._verify).props(
                        "color=primary no-caps")
                    self.deep_btn = ui.button("Deep check (re-download)",
                                              icon="sync", on_click=self._deep).props(
                        "outline no-caps")
                    ui.switch("Download & compare against Drive (slower, extra "
                              "safety)").bind_value(self, "deep").props("dense")

            self.status = ui.label("No verification yet.").classes(
                "text-sm font-semibold mt-4")
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

    def _show_status(self):
        data = vf.load_verify_result()
        if data:
            color = GOOD if data.get("passed") else DANGER
            label = "PASS" if data.get("passed") else "FAIL"
            self.status.set_text(
                f"{label} at {data.get('created', '?')} - {data.get('matched', 0)} OK, "
                f"{data.get('missing', 0)} missing, {data.get('mismatch', 0)} mismatched")
            self.status.style(f"color: {color}")
        else:
            self.status.set_text("No verification yet.")
            self.status.style(f"color: {MUTED}")

    def _verify(self):
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

    def _on_progress(self, pct, text):
        if pct and pct > 0:
            self.progress.props(remove="indeterminate")
            self.progress.set_value(pct / 100)

    def _verify_done(self, result, error):
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

    def _deep(self):
        remote = self.ctx.config.get("remote")
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
            ),
            on_done=self._deep_done,
        )

    def _deep_done(self, result, error):
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
    def __init__(self, ctx):
        self.ctx = ctx
        self.analysis = None
        self.summary_line = None
        self.cat_table = None
        self.details = None

    def build(self, parent=None):
        with parent or nullcontext():
            page_header(
                "analytics",
                "Analyze",
                "Understand what's in your Drive: duplicates, junk and the "
                "largest files - plus an optional AI summary.")
            with ui.row().classes("w-full items-center gap-2 mb-2"):
                ui.button("Analyze Drive", icon="analytics",
                          on_click=self._analyze).props("color=primary no-caps")
                ui.button("Generate Report", icon="description",
                          on_click=self._report).props("outline no-caps")
                ui.button("AI Summary (Gemini)", icon="auto_awesome",
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

    def _ai_settings(self):
        return (self.ctx.config.get("gemini_api_key"),
                self.ctx.config.get("ai_provider", "gemini"),
                self.ctx.config.get("ai_model") or None)

    def _analyze(self):
        key, provider, model = self._ai_settings()
        self.ctx.start_job(
            "analyze",
            lambda hub: ai_analyzer.analyze(key, provider=provider,
                                            model=model),
            on_done=self._analyze_done,
        )

    def _analyze_done(self, result, error):
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

    def _render(self, a):
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

    def _report(self):
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

    def _report_done(self, result, error):
        self.ctx.finish_job("report")
        if error:
            ui.notify(f"Report failed: {error}", type="negative")
            return
        ui.notify(f"Report saved: {result}", type="positive", position="top-right",
                  multi_line=True)

    def _ai(self):
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

    def _ai_done(self, result, error):
        self.ctx.finish_job("ai")
        if error:
            ui.notify(f"AI summary failed: {error}", type="negative")
            return
        self.details.set_content(f"## AI Summary (Gemini)\n\n{result}")
        ui.notify("AI summary ready", type="positive", position="top-right")

    def _quality(self):
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

    def _quality_done(self, result, error):
        self.ctx.finish_job("ai")
        if error:
            ui.notify(f"AI quality check failed: {error}", type="negative")
            return
        if not result:
            ui.notify("No findings - drive looks healthy (or AI returned "
                      "nothing usable).", type="positive", position="top-right")
            return
        colors = {"high": DANGER, "medium": "#F59E0B", "low": INFO}
        lines = ["## AI Findings (Gemini)"]
        for f in result:
            lines.append(f"- **{f['severity'].upper()}** *({colors[f['severity']]})*: "
                         f"{f['message']}")
        self.details.set_content("\n".join(lines))
        ui.notify(f"{len(result)} findings", type="warning", position="top-right")


def _write_report(ctx, verify, analysis, gemini_key="",
                  provider="gemini", model=None):
    plan = ai_analyzer.organization_plan(gemini_key, provider=provider,
                                         model=model)
    findings = []
    if gemini_key:
        findings = ai_analyzer.quality_check(gemini_key, analysis, verify,
                                             provider=provider, model=model)
    content = generate_report(None, verify, analysis, plan,
                              ai_findings=findings)
    path = save_report(content)
    ctx.hub.log("SUCCESS", f"Report saved: {path}")
    return path


class WipePage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.gate = None
        self.phrase = None
        self.checkbox = None
        self.trash_btn = None
        self.empty_btn = None
        self.purge_btn = None

    def build(self, parent=None):
        with parent or nullcontext():
            page_header(
                "delete_forever",
                "Wipe",
                "Only files in YOUR Google Drive are affected. Gmail, Contacts "
                "and Photos are NOT touched. Files others shared with you are "
                "only removed from your view.")
            with ui.card().classes("w-full").props("flat bordered") \
                    .style("border-color: rgba(220,38,38,0.45)"):
                with ui.row().classes("w-full items-center gap-3 p-1"):
                    ui.icon("warning").classes("text-3xl") \
                        .style(f"color:{DANGER}")
                    ui.label("Wipe Google Drive - the dangerous part").classes(
                        "text-lg font-semibold").style(f"color:#FCA5A5")

            self.gate = ui.label("").classes("text-sm font-semibold mt-4")
            ui.label("Type the confirmation phrase to unlock:  DELETE ALL").classes(
                "text-sm mt-2").style(f"color:{MUTED}")
            self.phrase = ui.input("Confirmation phrase", password=True,
                                   placeholder="DELETE ALL",
                                   on_change=self._update_buttons).props(
                "outlined").classes("w-full max-w-md")
            self.checkbox = ui.checkbox("I verified the backup: every file exists "
                                        "locally and passed checksum verification",
                                        on_change=self._update_buttons)
            with ui.row().classes("items-center gap-2 mt-2"):
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

    def _update_gate(self):
        ok, msg = vf.verify_fresh(hours=self.ctx.config.get("verify_freshness_hours", 24))
        color = GOOD if ok else DANGER
        self.gate.set_text(f"Safety gate: {msg}")
        self.gate.style(f"color: {color}")
        self._update_buttons()

    def _update_buttons(self):
        phrase_ok = (self.phrase.value or "").strip().upper() == "DELETE ALL"
        enabled = bool(self.checkbox.value) and phrase_ok
        for b in (self.trash_btn, self.empty_btn, self.purge_btn):
            if enabled:
                b.enable()
            else:
                b.disable()

    def _gate_check(self):
        cfg = self.ctx.config
        wp.require_fresh_verification(cfg)
        wp.require_confirmation(self.phrase.value or "")
        if not self.checkbox.value:
            raise wp.SafetyGateError("You must tick the verification checkbox.")
        remote = cfg.get("remote")
        if not self.ctx.manager.remote_exists(remote):
            raise wp.SafetyGateError("Drive remote is not connected.")
        return remote

    def _trash(self):
        self._run("trash")

    def _empty(self):
        self._run("emptytrash")

    def _purge(self):
        self._run("purge")

    def _run(self, action):
        try:
            remote = self._gate_check()
        except wp.SafetyGateError as exc:
            ui.notify(str(exc), type="negative", position="top-right")
            return
        labels = {
            "trash": ("Move to Trash",
                      "This moves ALL files on your Google Drive into the Trash. "
                      "They stay recoverable there."),
            "emptytrash": ("Empty Trash",
                           "This PERMANENTLY deletes everything in your Drive "
                           "Trash. Files cannot be recovered afterwards."),
            "purge": ("Permanent delete",
                      "ADVANCED: permanently deletes ALL files WITHOUT sending "
                      "them to Trash. There is NO recovery."),
        }
        title, message = labels[action]
        confirm_dialog(
            title, message, ok_label=f"Yes, {title}",
            danger=action != "trash",
            on_ok=lambda: self._start(action, remote),
        )

    def _start(self, action, remote):
        jobs = {
            "trash": wp.move_to_trash,
            "emptytrash": wp.empty_trash,
            "purge": wp.purge_forever,
        }
        fn = jobs[action]
        self.ctx.start_job(
            action,
            lambda hub: fn(remote, line_cb=lambda m: hub.log("WARNING", m)),
            on_done=self._done(action),
        )

    def _done(self, action):
        def handler(result, error):
            self.ctx.finish_job(action)
            if error:
                ui.notify(f"Wipe step failed: {error}", type="negative",
                          position="top-right")
                return
            ui.notify(f"{action} done", type="positive", position="top-right")
        return handler


class SettingsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.transfers = None
        self.checkers = None
        self.hours = None
        self.gemini = None
        self.github_owner = None
        self.github_repo = None
        self.check_btn = None

    def build(self, parent=None):
        with parent or nullcontext():
            page_header("settings", "Settings",
                        "Tune the engine, add your AI key, and manage updates.")
            with ui.card().classes("w-full max-w-xl").props("flat bordered"):
                ui.label("Engine").classes("text-[10px] font-semibold uppercase "
                                           "tracking-[0.16em]") \
                    .style(f"color:{MUTED}")
                with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-3 mt-2"):
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
                except Exception:
                    version = "not installed"
                ui.label(f"rclone engine: {version}").classes("text-sm")
                ui.label(f"State folder: {state_path('')}").classes(
                    "text-xs").style(f"color:{MUTED}")
                ui.button("Open state folder", icon="folder_open",
                          on_click=lambda: open_in_explorer(str(state_path(""))))\
                    .props("outline no-caps").classes("mt-2")

    def _run_update_check(self):
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

        def fn(hub):
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

    def _on_update_check(self, result, error):
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
            on_ok=lambda: self._download_update(info),
        )

    def _download_update(self, info):
        dest = Path(tempfile.gettempdir()) / info.asset_name
        self.check_btn.disable()

        def fn(hub):
            hub.log("INFO", f"Downloading {info.asset_name} ...")
            download(info.asset_url, dest,
                     progress=lambda m: hub.log("INFO", m))
            hub.log("INFO", "Installing update ...")
            rc = install_silently(dest)
            if rc != 0:
                raise UpdateError(f"Installer failed (exit code {rc}).")
            hub.log("SUCCESS", f"DriveBackup v{info.version} installed.")
            return True

        self.ctx.start_job("update", fn,
                           on_done=lambda r, e: self._after_install(r, e))

    def _after_install(self, result, error):
        self.check_btn.enable()
        if error:
            ui.notify(f"Update failed: {error}", type="negative",
                      position="top-right")
            return
        ui.notify("Update installed - restarting ...", type="positive",
                  position="top-right")
        try:
            launch_installed()
        except Exception as exc:  # noqa: BLE001
            ui.notify(str(exc), type="negative", position="top-right")
        from nicegui import app as napp
        napp.shutdown()

    def _save(self):
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
        self.ctx.hub.log("SUCCESS", "Settings saved.")
        ui.notify("Settings saved", type="positive", position="top-right")