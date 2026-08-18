import html as _html

from nicegui import ui

from ..utils.config import format_bytes

# ---- design tokens (Premium Glassmorphism Design System) ------------
PRIMARY = "var(--primary)"
PRIMARY_HOVER = "var(--primary-hover)"
ACCENT = "var(--accent)"
DANGER = "var(--danger)"
GOOD = "var(--good)"
WARN = "var(--warn)"
INFO = "var(--info)"
MUTED = "var(--muted)"

LEVEL_COLORS = {
    "INFO": INFO,
    "DEBUG": "var(--muted)",
    "WARNING": WARN,
    "ERROR": DANGER,
    "SUCCESS": GOOD,
}

PIPELINE_STEPS = ["Connect", "Backup", "Verify", "Analyze", "Wipe"]


def page_header(icon, title, subtitle=None):
    """Consistent page hero: icon + title + optional subtitle."""
    with ui.row().classes("w-full items-start gap-3 mb-4"):
        with ui.element("div").classes(
                "w-10 h-10 rounded-lg flex items-center justify-center shrink-0") \
                .style(f"background:var(--glow-primary); color:{PRIMARY}; box-shadow: 0 0 15px var(--glow-primary);"):
            ui.icon(icon).classes("text-xl")
        with ui.column().classes("gap-0.5 flex-1"):
            ui.label(title).classes("text-xl font-semibold tracking-tight")\
                .style(f"color: {PRIMARY};")
            if subtitle:
                ui.label(subtitle).classes("text-sm").style(
                    f"color:{MUTED}")


def info_card(icon, title, lines, tone="info"):
    """Compact 'what this page does' card: icon, title and bullet lines."""
    accent = {"info": INFO, "good": GOOD, "warn": WARN, "danger": DANGER}\
        .get(tone, INFO)
    with ui.card().props("flat bordered").classes("w-full p-3").style(
            f"border-color:var(--border); background:var(--input-bg);"):
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon(icon).classes("text-lg").style(f"color:{accent}")
            ui.label(title).classes("text-sm font-semibold")
        with ui.column().classes("w-full gap-0.5 mt-1"):
            for line in lines:
                with ui.row().classes("items-start gap-2"):
                    ui.label("•").classes("text-xs").style(f"color:{accent}")
                    ui.label(line).classes("text-sm").style(f"color:{MUTED}")


class LogConsole:
    """Live, color-coded, auto-scrolling log console."""

    def __init__(self, max_lines=500, height="200px"):
        self.max_lines = max_lines
        self._count = 0
        self._items = []
        with ui.row().classes("w-full items-center gap-2 px-3 pt-1"):
            ui.icon("terminal").classes("text-sm").style(f"color:{MUTED}")
            ui.label("CONSOLE").classes("text-[10px] font-semibold "
                                        "tracking-[0.14em]").style(
                f"color:{MUTED}")
            ui.space()
            ui.button(icon="delete_sweep", on_click=self.clear)\
                .props("flat dense round size=sm").tooltip("Clear console")\
                .style(f"color:{MUTED}")
        self.scroll = ui.scroll_area().classes("w-full")
        self.scroll.style(f"height: {height}")
        with self.scroll:
            self.col = ui.column().classes("w-full gap-0 px-3 py-1")
        self.clear()

    def push(self, message, level="INFO"):
        color = LEVEL_COLORS.get(level, "#CBD5E1")
        tag = {"ERROR": "ERROR", "WARNING": "WARN", "SUCCESS": "OK"}\
            .get(level, level)
        line = (f'<div class="log-line" style="color:{color}">'
                f'<span class="log-tag">{_html.escape(tag)}</span> '
                f'{_html.escape(message)}</div>')
        with self.col:
            el = ui.html(line).classes("w-full")
        self._items.append(el)
        self._count += 1
        if self._count > self.max_lines:
            oldest = self._items.pop(0)
            oldest.delete()
        try:
            self.scroll.scroll_to(percent=1.0)
        except Exception:
            pass

    def clear(self):
        self._items = []
        self._count = 0
        self.col.clear()


class StatCard:
    """Flat stat card: tinted icon tile, uppercase label, bold value."""

    def __init__(self, label, value="-", icon="info", color=ACCENT):
        self.icon = icon
        self.color = color
        with ui.card().props("flat bordered").classes("w-full p-3 hover-lift"):
            with ui.row().classes("items-center gap-3 w-full"):
                with ui.element("div").classes(
                        "w-9 h-9 rounded-lg flex items-center justify-center "
                        "shrink-0").style(f"background:var(--input-bg);"
                                          f"color:{color}; box-shadow: 0 0 10px var(--shadow-color)"):
                    ui.icon(icon).classes("text-lg")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    self.label_el = ui.label(label).classes(
                        "text-[10px] font-semibold uppercase tracking-[0.14em]") \
                        .style(f"color:{MUTED}")
                    self.value_el = ui.label(value).classes(
                        "text-xl font-semibold tracking-tight truncate")

    def set(self, value, color=None):
        self.value_el.set_text(str(value))
        if color:
            self.value_el.style(f"color: {color}")


def _rgb(hex_color, alpha="0.12"):
    pass


def chip(text, color="grey", icon=None):
    c = ui.chip(text, icon=icon)
    c.props(f"color={color} text-color=white")
    return c


class PipelineChips:
    """Visual progress of the 5-step journey (flat segmented pills)."""

    def __init__(self, ctx, on_navigate=None):
        self.ctx = ctx
        self.on_navigate = on_navigate
        self.states = {s: "pending" for s in PIPELINE_STEPS}
        self.elements = {}
        self._applied = {}
        with ui.row().classes("items-center gap-2 flex-wrap"):
            for step in PIPELINE_STEPS:
                b = ui.button(step, on_click=lambda s=step: self._go(s))
                b.props("flat unelevated dense no-caps")
                b.classes("rounded-lg")
                self.elements[step] = b
                self._applied[step] = ""
        self.refresh()

    def _go(self, step):
        if self.on_navigate:
            self.on_navigate(step)

    def _color(self, state):
        return {"done": "teal", "active": "primary",
                "blocked": "red-8", "pending": "grey-8"}[state]

    def set_state(self, step, state):
        if step in self.states:
            self.states[step] = state

    def refresh(self):
        connected = self.ctx.manager.remote_exists(self.ctx.config.active_remote)
        verify_ok = self._verify_ok()
        for step in PIPELINE_STEPS:
            state = "pending"
            if step == "Connect":
                state = "done" if connected else "active"
            elif step == "Backup":
                state = "done" if self._manifest_exists() else "pending"
            elif step == "Verify":
                state = "done" if verify_ok else "pending"
            elif step == "Analyze":
                state = "done" if self._analysis_exists() else "pending"
            elif step == "Wipe":
                state = "done" if verify_ok else "blocked" if connected else "pending"
            self.set_state(step, state)
            b = self.elements[step]
            color = self._color(state)
            new = f"color={color}"
            if state == "done":
                new += " icon=check"
            b.props(remove=self._applied[step], add=new)
            self._applied[step] = new

    def _manifest_exists(self):
        from ..engine import backup as bk
        return bk.load_manifest() is not None

    def _verify_ok(self):
        from ..engine import verify as vf
        data = vf.load_verify_result()
        return bool(data and data.get("passed"))

    def _analysis_exists(self):
        from ..engine import backup as bk
        return bk.load_inventory() is not None or bk.load_manifest() is not None


def confirm_dialog(title, message, ok_label="Continue", danger=False,
                   on_ok=None, on_cancel=None):
    dlg = ui.dialog()
    color = "negative" if danger else "primary"
    with dlg, ui.card().classes("w-[26rem] max-w-[90vw] p-4"):
        ui.label(title).classes("text-lg font-semibold")
        ui.label(message).classes("text-sm").style(f"color:{MUTED}")
        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            def cancel():
                dlg.close()
                if on_cancel:
                    on_cancel()

            def ok():
                dlg.close()
                if on_ok:
                    on_ok()

            ui.button("Cancel", on_click=cancel).props("flat")
            ui.button(ok_label, on_click=ok).props(f"color={color} no-caps")
    dlg.open()
    return dlg


class FilePickerDialog:
    """Browse the Drive listing and select individual files.

    Searchable + sortable table, native multi-select (shift-click selects a
    range). Returns the chosen relative paths via on_confirm. Call
    update_inventory() to refresh rows (e.g. after a fresh lsjson).
    Your selection is kept even if you close the dialog - it only clears
    when you hit 'Clear selection' or confirm with 'Use selected files'.
    """

    def __init__(self, title="Select files", subtitle=None, on_refresh=None):
        self.title = title
        self.subtitle = subtitle
        self.on_refresh = on_refresh
        self.dialog = None
        self.table = None
        self.search = None
        self.refresh_btn = None
        self.count_label = None
        self.count_badge = None
        self._rows = []
        self._inventory = []
        self._selected_paths = []
        self.on_confirm = None

    def _build(self):
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes(
                "w-[56rem] max-w-[96vw] h-[76vh] flex flex-col gap-0 "
                "p-0 overflow-hidden"):
            with ui.row().classes("w-full items-center gap-3 px-5 pt-4"):
                with ui.element("div").classes(
                        "w-10 h-10 rounded-lg flex items-center justify-center "
                        "shrink-0").style(
                    f"background:rgba(13,148,136,0.12);color:{PRIMARY}"):
                    ui.icon("folder_open").classes("text-xl")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    ui.label(self.title).classes(
                        "text-[15px] font-semibold tracking-tight")
                    if self.subtitle:
                        ui.label(self.subtitle).classes(
                            "text-xs mt-0.5").style(f"color:{MUTED}")
                self.count_badge = ui.badge("0 selected") \
                    .props("color=primary text-color=white").classes(
                    "rounded-full shrink-0")
            with ui.row().classes("w-full items-center gap-2 px-5 pt-3"):
                self.search = ui.input("Search files and folders",
                                       placeholder="type to filter ...",
                                       on_change=self._apply_filter) \
                    .props("outlined dense clearable").classes("flex-1")
                if self.on_refresh:
                    self.refresh_btn = ui.button("Refresh from Drive",
                                                 icon="sync",
                                                 on_click=self._refresh)\
                        .props("flat dense no-caps").tooltip(
                        "Re-read the Drive listing")
                ui.button("Select all", icon="checklist",
                          on_click=self._all).props("flat dense no-caps") \
                    .tooltip("Select every file in the list")
                ui.button("Clear selection", icon="clear_all",
                          on_click=self._clear).props("flat dense no-caps")
            self.table = ui.table(
                columns=[
                    {"name": "name", "label": "Name", "field": "name",
                     "sortable": True, "align": "left"},
                    {"name": "folder", "label": "Folder", "field": "folder",
                     "sortable": True, "align": "left"},
                    {"name": "size", "label": "Size", "field": "size",
                     "sortable": True, "align": "right"},
                ],
                rows=self._rows,
                row_key="path",
                selection="multiple",
                on_select=self._on_select,
            ).props('flat bordered dense card-scroll') \
                .classes("w-full flex-1 min-h-0 mx-5 my-3")
            with ui.row().classes(
                    "w-full items-center justify-between px-5 py-3 "
                    "border-t").style("border-color: var(--border) !important"):
                self.count_label = ui.label("") \
                    .classes("text-xs").style(f"color:{MUTED}")
                with ui.row().classes("items-center gap-2"):
                    ui.button("Cancel", on_click=self._cancel).props("flat")
                    ui.button("Use selected files", icon="check",
                              on_click=self._confirm)\
                        .props("color=primary no-caps")

    def _apply_filter(self):
        q = (self.search.value or "").strip().lower()
        if q:
            rows = [r for r in self._rows
                    if q in r["path"].lower() or q in r["name"].lower()]
        else:
            rows = list(self._rows)
        self.table.update_rows(rows)
        self._sync_count()

    def _refresh(self):
        if not self.on_refresh:
            return
        if self.refresh_btn:
            self.refresh_btn.disable()
        if self.count_label:
            self.count_label.set_text("Refreshing from Drive ...")
        self.on_refresh(self)

    def refresh_done(self, error=None, inventory=None):
        """Called by the page after the Drive listing job finished."""
        if self.refresh_btn:
            self.refresh_btn.enable()
        if error:
            if self.count_label:
                self.count_label.set_text(
                    f"{len(self._rows)} rows loaded - refresh failed: {error}")
            return
        if inventory is not None:
            self.update_inventory(inventory)

    def _all(self):
        self.table.selected = list(self.table.rows)
        self._sync_count()

    def _clear(self):
        self.table.selected = []
        self._selected_paths = []
        self._sync_count()

    def _on_select(self, event):
        self._sync_count()

    def _sync_count(self):
        n = len(self.table.selected)
        total = sum(r.get("_size", 0) for r in self.table.selected)
        if self.count_badge:
            self.count_badge.set_text(f"{n} selected")
        if self.count_label:
            self.count_label.set_text(
                f"{n} of {len(self._inventory)} files on your Drive selected"
                + (f"  ({_human_size(total)})" if total else ""))

    def _confirm(self):
        paths = [r["path"] for r in self.table.selected]
        self._selected_paths = list(paths)
        self.dialog.close()
        if self.on_confirm:
            self.on_confirm(paths)

    def _cancel(self):
        self.dialog.close()

    def open(self, inventory, on_confirm):
        """Show the picker for the given inventory list (lsjson items).

        Keeps the previous selection across close/reopen so nothing is
        lost if the dialog is dismissed by accident.
        """
        if self.dialog is None:
            self._build()
        self._inventory = inventory
        self._rows = []
        for f in inventory:
            path = f.get("Path") or f.get("Name")
            name = path.rsplit("/", 1)[-1]
            folder = path.rsplit("/", 1)[0] if "/" in path else "Drive root"
            is_dir = bool(f.get("IsDir"))
            self._rows.append({
                "path": path,
                "name": name + ("/" if is_dir else ""),
                "folder": folder,
                "size": format_bytes(f.get("Size", 0)),
                "_size": f.get("Size", 0),
            })
        self.table.update_rows(self._rows)
        self.table.selected = [r for r in self.table.rows
                               if r["path"] in self._selected_paths]
        if self.search:
            self.search.value = ""
        self.on_confirm = on_confirm
        self._sync_count()
        self.dialog.open()

    def update_inventory(self, inventory):
        """Refresh the table in place (keeps selection if paths still exist)."""
        if self.dialog is None:
            return
        kept = {r["path"] for r in self.table.selected}
        self.open(inventory, self.on_confirm)
        self.table.selected = [r for r in self.table.rows
                               if r["path"] in kept]
        self._selected_paths = [r["path"] for r in self.table.selected]
        self._sync_count()


def _human_size(n):
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} PB"


def auth_url_dialog(url, on_cancel=None):
    """Connect-flow dialog with live status so the user always knows what
    is happening: copy URL -> open browser -> sign in -> this dialog flips
    to 'connected' automatically and closes itself."""
    global _CONNECT_DIALOG
    dlg = ui.dialog()

    def cancel():
        _close_connect_dialog()
        if on_cancel:
            on_cancel()

    with dlg, ui.card().classes("w-[38rem] max-w-[92vw] p-5"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.icon("link").classes("text-2xl").style(f"color:{PRIMARY}")
            ui.label("Connect Google Drive").classes("text-lg font-semibold")
        ui.label("3 steps, then this window updates by itself:").classes(
            "text-sm mt-2").style(f"color:{MUTED}")
        with ui.column().classes("w-full gap-1 mt-2"):
            with ui.row().classes("items-start gap-2"):
                ui.label("1").classes("w-5 h-5 rounded-full text-center "
                                       "text-[11px] font-bold shrink-0") \
                    .style(f"background:rgba({_rgb(PRIMARY, '0.15')});color:{PRIMARY}")
                ui.label("Click 'Open in browser' below.").classes("text-sm")
            with ui.row().classes("items-start gap-2"):
                ui.label("2").classes("w-5 h-5 rounded-full text-center "
                                       "text-[11px] font-bold shrink-0") \
                    .style(f"background:rgba({_rgb(PRIMARY, '0.15')});color:{PRIMARY}")
                ui.label("Sign in with the Google account that owns the "
                         "Drive and approve access.").classes("text-sm")
            with ui.row().classes("items-start gap-2"):
                ui.label("3").classes("w-5 h-5 rounded-full text-center "
                                       "text-[11px] font-bold shrink-0") \
                    .style(f"background:rgba({_rgb(PRIMARY, '0.15')});color:{PRIMARY}")
                ui.label("Come back here - it connects automatically.")\
                    .classes("text-sm")
        with ui.row().classes("w-full items-center gap-2 mt-3"):
            ui.input("Authorization URL", value=url).props(
                "readonly outlined dense").classes("flex-1")
            ui.button(icon="content_copy",
                      on_click=lambda: ui.clipboard.write(url)) \
                .props("outline").tooltip("Copy URL")
        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Open in browser", icon="open_in_new",
                      on_click=lambda: ui.open(url, new_tab=True)).props(
                "color=primary no-caps")
            ui.button("Cancel connection", icon="close",
                      on_click=cancel).props("flat")
        status_row = ui.row().classes("w-full items-center gap-2 mt-4 p-3 "
                                      "rounded-lg").style(
            f"background:rgba(56,189,248,0.07);border:1px solid rgba(56,189,248,.25)")
        with status_row:
            spinner = ui.spinner(size="18px")
            status = ui.label("Waiting for you to complete the sign-in in "
                              "your browser ...").classes("text-sm")
            status.style(f"color:{INFO}")
    dlg.open()
    _CONNECT_DIALOG = {"dialog": dlg, "status": status, "spinner": spinner,
                       "row": status_row}
    return dlg


_CONNECT_DIALOG = None


def _close_connect_dialog():
    global _CONNECT_DIALOG
    if _CONNECT_DIALOG:
        try:
            _CONNECT_DIALOG["dialog"].close()
        except Exception:
            pass
        _CONNECT_DIALOG = None


def connect_dialog_status(message, ok=False):
    """Update the connect dialog: waiting -> success / failure."""
    global _CONNECT_DIALOG
    if not _CONNECT_DIALOG:
        return
    entry = _CONNECT_DIALOG
    try:
        if ok:
            entry["spinner"].delete()
            entry["row"].style(
                f"background:rgba(34,197,94,0.08);"
                f"border:1px solid rgba(34,197,94,.35)")
            entry["status"].set_text(message)
            entry["status"].style(f"color:{GOOD}")
            ui.timer(1.4, _close_connect_dialog, once=True)
        else:
            entry["spinner"].delete()
            entry["row"].style(
                f"background:rgba(248,113,113,0.08);"
                f"border:1px solid rgba(248,113,113,.35)")
            entry["status"].set_text(message)
            entry["status"].style(f"color:{DANGER}")
    except Exception:
        _CONNECT_DIALOG = None


def code_dialog(box, event):
    dlg = ui.dialog()

    def submit(entry):
        box["code"] = entry.value or ""
        event.set()
        dlg.close()

    with dlg, ui.card().classes("w-[26rem] max-w-[90vw] p-4"):
        ui.label("Step 2 - Paste the authorization code").classes(
            "text-lg font-semibold")
        ui.label("After granting access, Google shows a code. Copy it and paste "
                 "it here.").classes("text-sm").style(f"color:{MUTED}")
        with ui.row().classes("w-full items-center gap-2 mt-2"):
            entry = ui.input("Authorization code",
                             placeholder="Paste the code Google showed you")
            entry.props("outlined dense").classes("flex-1")
        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Cancel", on_click=lambda: (event.set(), dlg.close())).props("flat")
            ui.button("OK", on_click=lambda: submit(entry)).props(
                "color=primary no-caps")
    dlg.open()


def pick_directory(title="Choose a folder"):
    """Native folder picker (Windows).

    Prefers the app window's native dialog (fast, runs in the window
    process) and falls back to a Tk dialog when running in a plain browser.
    """
    try:
        from nicegui import app as napp
        import webview
        nw = napp.native.window
        if nw is not None:
            result = nw.create_file_dialog(webview.FOLDER_DIALOG)
            if result:
                return str(result[0])
    except Exception:
        pass
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(title=title)
    finally:
        root.destroy()
    return path or None


def open_in_explorer(path):
    import os
    try:
        os.startfile(path)
    except Exception:
        pass