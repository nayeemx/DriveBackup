import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .widgets import Card, Tree, stat_row

from ..ai import analyzer as ai_analyzer
from ..ai import llm
from ..ai.report import generate_report, save_report
from ..engine import backup as bk
from ..engine import verify as vf
from ..engine import wipe as wp
from ..utils.config import format_bytes, state_path


def _fmt(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


def _ask_dir(parent, entry):
    d = filedialog.askdirectory(parent=parent, title="Choose backup destination")
    if d:
        entry.delete(0, "end")
        entry.insert(0, d)
    return d


class DashboardTab(ctk.CTkFrame):
    def __init__(self, master, ctx):
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)

        self.title = ctk.CTkLabel(
            self, text="Google Drive Backup Tool", font=("Segoe UI", 20, "bold"))
        self.title.grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")

        self.sub = ctk.CTkLabel(
            self, text="Backup -> Verify -> Analyze -> Wipe, with safety gates.",
            font=("Segoe UI", 12), text_color="#9aa0a6")
        self.sub.grid(row=1, column=0, padx=16, sticky="w")

        self.stats_frame = Card(self, title="Drive status")
        self.stats_frame.grid(row=2, column=0, padx=16, pady=10, sticky="ew")
        self.stat_labels = {}
        for i, key in enumerate(["state", "total", "used", "free", "inventory"]):
            self.stat_labels[key] = ctk.CTkLabel(self.stats_frame.body, text="...")
            stat_row(self.stats_frame.body, key.capitalize(), self.stat_labels[key], i)

        self.connect_btn = ctk.CTkButton(self, text="Connect Google Drive",
                                         command=self._connect, height=36)
        self.connect_btn.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="w")
        self.refresh_btn = ctk.CTkButton(self, text="Refresh", command=self._refresh)
        self.refresh_btn.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="e")

        self._refresh()

    def _refresh(self):
        if not self.ctx.manager.remote_exists(self.ctx.config.get("remote")):
            self.stat_labels["state"].configure(text="NOT CONNECTED")
            for k in ("total", "used", "free", "inventory"):
                self.stat_labels[k].configure(text="-")
            self.ctx.hub.log("WARNING", "Drive not connected - click 'Connect Google Drive'.")
            return
        self.stat_labels["state"].configure(text="connected")
        try:
            about = self.ctx.manager.about(self.ctx.config.get("remote"))
            for key, label in (("Total", "total"), ("Used", "used"), ("Free", "free")):
                if key in about:
                    self.stat_labels[label].configure(text=about[key])
        except Exception as exc:
            self.ctx.hub.log("ERROR", f"Could not read drive stats: {exc}")
        inv = bk.load_inventory()
        if inv:
            total = sum(f.get("Size", 0) for f in inv)
            self.stat_labels["inventory"].configure(
                text=f"{len(inv):,} files, {format_bytes(total)}")

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
            on_progress=lambda p, t: None,
            on_done=self._connect_done,
        )

    def _connect_done(self, result, error):
        self.ctx.finish_job("connect")
        if error:
            messagebox.showerror("Connection failed",
                                 f"{type(error).__name__}: {error}")
            return
        self.ctx.hub.log("SUCCESS", "Google Drive connected.")
        self._refresh()


class BackupTab(ctk.CTkFrame):
    def __init__(self, master, ctx):
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)

        card = Card(self, title="Backup destination")
        card.grid(row=0, column=0, padx=16, pady=10, sticky="ew")
        self.dir_entry = ctk.CTkEntry(card.body, placeholder_text=
            "Choose an EMPTY local folder (external drive, NAS, etc.)")
        self.dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(card.body, text="Browse", width=90,
                      command=lambda: _ask_dir(self, self.dir_entry)).grid(
            row=0, column=1)

        info = ctk.CTkLabel(
            self,
            text="Downloads every file and folder from Google Drive to the chosen "
                 "location, then builds a manifest (inventory + checksums).\n"
                 "Google Docs/Sheets/Slides are exported (docx/xlsx/pptx) so nothing "
                 "is lost.",
            text_color="#9aa0a6", justify="left", font=("Segoe UI", 11))
        info.grid(row=1, column=0, padx=24, pady=(0, 8), sticky="w")

        self.start_btn = ctk.CTkButton(self, text="Start Backup",
                                       command=self._run, height=40)
        self.start_btn.grid(row=2, column=0, padx=16, pady=6, sticky="ew")

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.grid(row=3, column=0, padx=16, pady=(4, 2), sticky="ew")
        self.progress_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 11))
        self.progress_label.grid(row=4, column=0, padx=16, sticky="w")

        self.summary = ctk.CTkLabel(self, text="", font=("Segoe UI", 12, "bold"),
                                    text_color="#6bff8e")
        self.summary.grid(row=5, column=0, padx=16, pady=4, sticky="w")

    def _run(self):
        target = self.dir_entry.get().strip()
        if not target:
            messagebox.showwarning("Backup", "Choose a destination folder first.")
            return
        remote = self.ctx.config.get("remote")
        if not self.ctx.manager.remote_exists(remote):
            messagebox.showwarning("Backup", "Connect Google Drive first (Dashboard).")
            return
        cfg = self.ctx.config
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
        self.start_btn.configure(state="disabled", text="Backing up ...")

    def _on_progress(self, pct, text):
        self.progress.set(pct)
        self.progress_label.configure(text=text)

    def _on_done(self, result, error):
        self.ctx.finish_job("backup")
        self.start_btn.configure(state="normal", text="Start Backup")
        if error:
            messagebox.showerror("Backup failed", str(error))
            return
        self.summary.configure(
            text=(f"Backup complete: {_fmt(result['files'])} files, "
                  f"{format_bytes(result['bytes'])} - "
                  f"{result['ok']} verified present locally, "
                  f"{result['missing']} missing"))
        self.ctx.hub.log("SUCCESS", f"Backup manifest saved to {result['manifest']}")


class VerifyTab(ctk.CTkFrame):
    def __init__(self, master, ctx):
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        card = Card(self, title="Integrity verification")
        card.grid(row=0, column=0, padx=16, pady=10, sticky="ew")
        ctk.CTkLabel(
            card.body,
            text="Compares every backed-up file against the manifest (size + MD5 "
                 "checksum).\nNothing is touched on Google Drive by this step.",
            text_color="#9aa0a6", justify="left", font=("Segoe UI", 11)).grid(
            row=0, column=0, sticky="w")
        ctk.CTkButton(card.body, text="Verify backup", command=self._verify,
                      width=160).grid(row=1, column=0, sticky="w", pady=6)

        self.deep_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(card.body, text="Deep check: re-download & compare against "
                        "Drive (slower, extra safety)", variable=self.deep_var).grid(
            row=2, column=0, sticky="w", pady=(4, 2))
        self.deep_btn = ctk.CTkButton(card.body, text="Run deep check",
                                      command=self._deep, width=160)
        self.deep_btn.grid(row=3, column=0, sticky="w", pady=6)

        self.status = ctk.CTkLabel(self, text="", font=("Segoe UI", 12, "bold"))
        self.status.grid(row=1, column=0, padx=16, sticky="w")

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.grid(row=2, column=0, padx=16, pady=4, sticky="ew")

        self.tree = Tree(self, columns=("path", "status"), widths=(520, 160), height=12)
        self.tree.grid_with_scroll(row=4, column=0, padx=16, pady=(6, 12), sticky="nsew")

        self._show_status()

    def _show_status(self):
        data = vf.load_verify_result()
        if data:
            color = "#6bff8e" if data.get("passed") else "#ff6b6b"
            self.status.configure(
                text=(f"{'PASS' if data.get('passed') else 'FAIL'} at {data.get('created', '?')} "
                      f"- {data.get('matched', 0)} OK, {data.get('missing', 0)} missing, "
                      f"{data.get('mismatch', 0)} mismatched"),
                text_color=color)
        else:
            self.status.configure(text="No verification yet.", text_color="#9aa0a6")

    def _verify(self):
        cfg = self.ctx.config
        self.ctx.start_job(
            "verify",
            lambda hub: vf.verify_local(
                workers=8,
                progress_cb=lambda p, t: hub.progress(p, t),
                line_cb=lambda m: hub.log("INFO", m),
            ),
            on_progress=lambda p, t: (self.progress.set(p), None),
            on_done=self._verify_done,
        )

    def _verify_done(self, result, error):
        self.ctx.finish_job("verify")
        if error:
            messagebox.showerror("Verification failed", str(error))
            return
        self.tree.set_rows([[r["path"], r["status"]] for r in result["results"]])
        self._show_status()
        self.ctx.hub.log(
            "SUCCESS" if result["passed"] else "ERROR",
            f"Verification {'PASSED' if result['passed'] else 'FAILED'}")

    def _deep(self):
        cfg = self.ctx.config
        remote = cfg.get("remote")
        manifest = vf.load_manifest_for_verify()
        if not manifest:
            messagebox.showwarning("Deep check", "Run a backup first.")
            return
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
        self.deep_btn.configure(state="disabled", text="Deep checking ...")

    def _deep_done(self, result, error):
        self.ctx.finish_job("deepcheck")
        self.deep_btn.configure(state="normal", text="Run deep check")
        if error:
            messagebox.showerror("Deep check failed", str(error))
            return
        self.ctx.hub.log(
            "SUCCESS" if result["passed"] else "ERROR",
            f"Deep check: {result['files']} files, {result['missing']} missing, "
            f"{result['mismatch']} mismatched -> "
            f"{'PASS' if result['passed'] else 'FAIL'}")


class AnalyzeTab(ctk.CTkFrame):
    def __init__(self, master, ctx):
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, padx=16, pady=10, sticky="ew")
        top.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(top, text="Analyze Drive", command=self._analyze,
                      width=140).grid(row=0, column=0, padx=(0, 8))
        self.report_btn = ctk.CTkButton(top, text="Generate Report",
                                        command=self._report, width=140)
        self.report_btn.grid(row=0, column=1, padx=(0, 8))
        self.ai_btn = ctk.CTkButton(top, text="AI Summary (Gemini)",
                                    command=self._ai, width=160)
        self.ai_btn.grid(row=0, column=3)

        self.summary_line = ctk.CTkLabel(self, text="Run analysis to see drive health.",
                                         font=("Segoe UI", 12, "bold"),
                                         text_color="#9aa0a6")
        self.summary_line.grid(row=1, column=0, padx=16, sticky="w")

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.grid(row=2, column=0, padx=16, pady=4, sticky="ew")

        self.result_text = ctk.CTkTextbox(self, height=200, wrap="word")
        self.result_text.grid(row=3, column=0, padx=16, pady=(4, 6), sticky="nsew")
        self.result_text.configure(state="disabled")

        self.analysis = None
        self.plan = None

    def _analyze(self):
        self.ctx.start_job(
            "analyze",
            lambda hub: ai_analyzer.analyze(),
            on_progress=lambda p, t: (self.progress.set(p), None),
            on_done=self._analyze_done,
        )

    def _analyze_done(self, result, error):
        self.ctx.finish_job("analyze")
        if error:
            messagebox.showerror("Analysis failed", str(error))
            return
        self.analysis = result
        self.ctx.hub.log("SUCCESS", "Analysis complete.")
        self._render(result)

    def _render(self, a):
        lines = []
        lines.append(f"FILES: {_fmt(a['count'])}   SIZE: {format_bytes(a['size'])}\n")
        for k, v in sorted(a["categories"].items(), key=lambda kv: -kv[1]["size"]):
            lines.append(f"  {k:<15} {_fmt(v['count']):>6} files  {format_bytes(v['size']):>12}")
        lines.append("")
        lines.append(f"DUPLICATES: {a['dup_count']} groups, "
                     f"{format_bytes(a['dup_wasted'])} wasted space")
        lines.append(f"JUNK: {format_bytes(a['junk_size'])} "
                     f"({len(a['junk'])} junk categories)")
        lines.append(f"EMPTY FILES: {len(a['empty_files'])}")
        lines.append("")
        lines.append("TOP 10 LARGEST:")
        for f in a["top_files"][:10]:
            lines.append(f"  {format_bytes(f['size']):>12}  {f['path']}")
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "\n".join(lines))
        self.result_text.configure(state="disabled")
        self.summary_line.configure(
            text=(f"{_fmt(a['count'])} files, {format_bytes(a['size'])} | "
                  f"{a['dup_count']} dup groups | {format_bytes(a['junk_size'])} junk"),
            text_color="#ffffff")

    def _report(self):
        ctx = self.ctx
        backup = None
        verify = vf.load_verify_result()
        if not self.analysis:
            messagebox.showinfo("Report", "Run analysis first (it will be included).")
            return
        ctx.start_job(
            "report",
            lambda hub: _write_report(ctx, backup, verify, self.analysis),
            on_done=lambda r, e: (
                messagebox.showinfo("Report", f"Saved: {r}") if r and not e
                else messagebox.showerror("Report failed", str(e)) if e else None,
                ctx.finish_job("report"),
            ),
        )

    def _ai(self):
        key = self.ctx.config.get("gemini_api_key")
        if not key:
            messagebox.showinfo(
                "AI Summary",
                "No Gemini API key set.\n\nGet a FREE key (no credit card) at "
                "https://aistudio.google.com/apikey then add it in Settings.")
            return
        if not self.analysis:
            messagebox.showinfo("AI Summary", "Run analysis first.")
            return
        self.ctx.start_job(
            "ai",
            lambda hub: llm.summarize(key, self.analysis),
            on_progress=lambda p, t: None,
            on_done=lambda r, e: (
                self.result_text.configure(state="normal"),
                self.result_text.delete("1.0", "end") if r else None,
                self.result_text.insert("1.0", f"[AI SUMMARY]\n\n{r}") if r else None,
                self.result_text.configure(state="disabled"),
                messagebox.showerror("AI failed", str(e)) if e else None,
                self.ctx.finish_job("ai"),
            ),
        )


def _write_report(ctx, backup, verify, analysis):
    plan = ai_analyzer.organization_plan()
    content = generate_report(backup, verify, analysis, plan)
    path = save_report(content)
    ctx.hub.log("SUCCESS", f"Report saved: {path}")
    return path


class WipeTab(ctk.CTkFrame):
    def __init__(self, master, ctx):
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(self, text="Wipe Google Drive (after verified backup)",
                     font=("Segoe UI", 15, "bold")).grid(
            row=0, column=0, padx=16, pady=(14, 4), sticky="w")

        ctk.CTkLabel(
            self,
            text="Only files owned/stored in YOUR Google Drive are affected.\n"
                 "Gmail, Contacts, Photos and other Google services are NOT touched.\n"
                 "Files others shared with you are only removed from your view.",
            text_color="#9aa0a6", justify="left", font=("Segoe UI", 11)).grid(
            row=1, column=0, padx=16, sticky="w")

        self.gate = ctk.CTkLabel(self, text="", font=("Segoe UI", 12, "bold"))
        self.gate.grid(row=2, column=0, padx=16, pady=6, sticky="w")

        ctk.CTkLabel(self, text="Type the confirmation phrase to unlock:  DELETE ALL",
                     font=("Segoe UI", 11)).grid(
            row=3, column=0, padx=16, sticky="w", pady=(4, 0))
        self.phrase = ctk.CTkEntry(self, show="*", placeholder_text="DELETE ALL")
        self.phrase.grid(row=4, column=0, padx=16, pady=4, sticky="ew")
        self.phrase.bind("<KeyRelease>", lambda e: self._update_buttons())

        self.confirm = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self, text="I verified the backup: every file exists locally and passed "
                       "checksum verification.",
            variable=self.confirm, command=self._update_buttons).grid(
            row=5, column=0, padx=16, pady=4, sticky="w")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=6, column=0, padx=16, pady=8, sticky="ew")
        self.trash_btn = ctk.CTkButton(row, text="1. Move to Trash",
                                       command=self._trash, fg_color="#b3541e")
        self.trash_btn.grid(row=0, column=0, padx=(0, 8))
        self.empty_btn = ctk.CTkButton(row, text="2. Empty Trash",
                                       command=self._empty, fg_color="#b3541e")
        self.empty_btn.grid(row=0, column=1, padx=(0, 8))
        self.purge_btn = ctk.CTkButton(row, text="ADVANCED: Permanent delete (no Trash)",
                                       command=self._purge, fg_color="#8b1a1a")
        self.purge_btn.grid(row=0, column=2)
        self._update_gate()

    def _update_gate(self):
        ok, msg = vf.verify_fresh(hours=self.ctx.config.get("verify_freshness_hours", 24))
        self.gate.configure(
            text=f"Safety gate: {msg}",
            text_color="#6bff8e" if ok else "#ff6b6b")
        self._update_buttons()

    def _update_buttons(self):
        phrase_ok = self.phrase.get().strip().upper() == "DELETE ALL"
        enabled = self.confirm.get() and phrase_ok
        for b in (self.trash_btn, self.empty_btn, self.purge_btn):
            b.configure(state="normal" if enabled else "disabled")

    def _gate_check(self):
        cfg = self.ctx.config
        wp.require_fresh_verification(cfg)
        wp.require_confirmation(self.phrase.get())
        if not self.confirm.get():
            raise wp.SafetyGateError("You must tick the verification checkbox.")
        remote = cfg.get("remote")
        if not self.ctx.manager.remote_exists(remote):
            raise wp.SafetyGateError("Drive remote is not connected.")
        return remote

    def _trash(self):
        try:
            remote = self._gate_check()
        except wp.SafetyGateError as exc:
            messagebox.showerror("Blocked", str(exc))
            return
        if not messagebox.askyesno(
                "Move to Trash",
                "This moves ALL files on your Google Drive into the Trash.\n"
                "Continue?"):
            return
        self.ctx.start_job(
            "trash",
            lambda hub: wp.move_to_trash(remote, line_cb=lambda m: hub.log("WARNING", m)),
            on_done=self._generic_done("trash"),
        )

    def _empty(self):
        try:
            remote = self._gate_check()
        except wp.SafetyGateError as exc:
            messagebox.showerror("Blocked", str(exc))
            return
        if not messagebox.askyesno(
                "Empty Trash",
                "This PERMANENTLY deletes everything in your Drive Trash.\n"
                "Files cannot be recovered afterwards. Continue?"):
            return
        self.ctx.start_job(
            "emptytrash",
            lambda hub: wp.empty_trash(remote, line_cb=lambda m: hub.log("WARNING", m)),
            on_done=self._generic_done("emptytrash"),
        )

    def _purge(self):
        try:
            remote = self._gate_check()
        except wp.SafetyGateError as exc:
            messagebox.showerror("Blocked", str(exc))
            return
        if not messagebox.askyesno(
                "Permanent delete",
                "ADVANCED: this permanently deletes ALL files WITHOUT sending them "
                "to Trash. There is NO recovery. Continue?"):
            return
        self.ctx.start_job(
            "purge",
            lambda hub: wp.purge_forever(remote, line_cb=lambda m: hub.log("WARNING", m)),
            on_done=self._generic_done("purge"),
        )

    def _generic_done(self, job_id):
        def handler(result, error):
            self.ctx.finish_job(job_id)
            if error:
                messagebox.showerror("Wipe failed", str(error))
        return handler


class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, ctx):
        super().__init__(master, fg_color="transparent")
        self.ctx = ctx
        self.grid_columnconfigure(0, weight=1)

        card = Card(self, title="Settings")
        card.grid(row=0, column=0, padx=16, pady=10, sticky="ew")

        cfg = ctx.config
        row0 = ctk.CTkFrame(card.body, fg_color="transparent")
        row0.grid(row=0, column=0, sticky="ew", pady=2)
        ctk.CTkLabel(row0, text="Parallel downloads (transfers):").grid(
            row=0, column=0, sticky="w")
        self.transfers = ctk.CTkEntry(row0, width=80)
        self.transfers.insert(0, str(cfg.get("transfers")))
        self.transfers.grid(row=0, column=1, padx=(8, 0))

        row1 = ctk.CTkFrame(card.body, fg_color="transparent")
        row1.grid(row=1, column=0, sticky="ew", pady=2)
        ctk.CTkLabel(row1, text="Parallel checks (checkers):").grid(
            row=0, column=0, sticky="w")
        self.checkers = ctk.CTkEntry(row1, width=80)
        self.checkers.insert(0, str(cfg.get("checkers")))
        self.checkers.grid(row=0, column=1, padx=(8, 0))

        row2 = ctk.CTkFrame(card.body, fg_color="transparent")
        row2.grid(row=2, column=0, sticky="ew", pady=2)
        ctk.CTkLabel(row2, text="Verify freshness window (hours):").grid(
            row=0, column=0, sticky="w")
        self.hours = ctk.CTkEntry(row2, width=80)
        self.hours.insert(0, str(cfg.get("verify_freshness_hours")))
        self.hours.grid(row=0, column=1, padx=(8, 0))

        row3 = ctk.CTkFrame(card.body, fg_color="transparent")
        row3.grid(row=3, column=0, sticky="ew", pady=2)
        ctk.CTkLabel(row3, text="Gemini API key (free, optional):").grid(
            row=0, column=0, sticky="w")
        self.gemini = ctk.CTkEntry(row3, width=320, show="*")
        self.gemini.insert(0, cfg.get("gemini_api_key", ""))
        self.gemini.grid(row=0, column=1, padx=(8, 0))

        ctk.CTkLabel(card.body, text="Get a free key (no credit card needed): "
                    "https://aistudio.google.com/apikey",
                    text_color="#9aa0a6", font=("Segoe UI", 10)).grid(
            row=4, column=0, sticky="w", pady=(0, 4))

        ctk.CTkButton(card.body, text="Save settings", command=self._save,
                      width=160).grid(row=5, column=0, sticky="w", pady=4)

        info_card = Card(self, title="About")
        info_card.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
        try:
            version = ctx.manager.version()
        except Exception:
            version = "not installed"
        ctk.CTkLabel(info_card.body, text=f"rclone engine: {version}",
                     font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(info_card.body,
                     text=f"State folder: {state_path('')}",
                     font=("Segoe UI", 10), text_color="#9aa0a6").grid(
            row=1, column=0, sticky="w")
        ctk.CTkButton(info_card.body, text="Open state folder", width=160,
                      command=lambda: os.startfile(str(state_path("")))).grid(
            row=2, column=0, sticky="w", pady=4)

    def _save(self):
        cfg = self.ctx.config
        try:
            cfg.set("transfers", max(1, min(16, int(self.transfers.get()))))
            cfg.set("checkers", max(1, min(32, int(self.checkers.get()))))
            cfg.set("verify_freshness_hours",
                    max(1, min(720, int(self.hours.get()))))
        except ValueError:
            messagebox.showerror("Settings", "Transfers/checkers/hours must be numbers.")
            return
        cfg.set("gemini_api_key", self.gemini.get().strip())
        self.ctx.hub.log("SUCCESS", "Settings saved.")