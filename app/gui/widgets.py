import html as _html

from nicegui import ui

# ---- design tokens (UI UX Pro Max: Flat Design / developer tool) ------------
PRIMARY = "#0D9488"
PRIMARY_HOVER = "#14B8A6"
ACCENT = "#EA580C"
DANGER = "#DC2626"
GOOD = "#22C55E"
WARN = "#F59E0B"
INFO = "#38BDF8"
MUTED = "#94A3B8"

LEVEL_COLORS = {
    "INFO": INFO,
    "DEBUG": "#64748B",
    "WARNING": WARN,
    "ERROR": "#F87171",
    "SUCCESS": GOOD,
}

PIPELINE_STEPS = ["Connect", "Backup", "Verify", "Analyze", "Wipe"]


def page_header(icon, title, subtitle=None):
    """Consistent page hero: icon + title + optional subtitle."""
    with ui.row().classes("w-full items-start gap-3 mb-4"):
        with ui.element("div").classes(
                "w-10 h-10 rounded-lg flex items-center justify-center shrink-0") \
                .style(f"background:rgba(13,148,136,0.12); color:{PRIMARY}"):
            ui.icon(icon).classes("text-xl")
        with ui.column().classes("gap-0.5 flex-1"):
            ui.label(title).classes("text-xl font-semibold tracking-tight")
            if subtitle:
                ui.label(subtitle).classes("text-sm").style(
                    f"color:{MUTED}")


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
        with ui.card().props("flat bordered").classes("w-full p-3"):
            with ui.row().classes("items-center gap-3 w-full"):
                with ui.element("div").classes(
                        "w-9 h-9 rounded-lg flex items-center justify-center "
                        "shrink-0").style(f"background:rgba({_rgb(color)});"
                                          f"color:{color}"):
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


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b},0.12"


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
        connected = self.ctx.manager.remote_exists(self.ctx.config.get("remote"))
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


def auth_url_dialog(url, on_done=None):
    dlg = ui.dialog()
    with dlg, ui.card().classes("w-[34rem] max-w-[90vw] p-4"):
        ui.label("Step 1 - Authorize in your browser").classes("text-lg font-semibold")
        ui.label("Log in with the Google account that owns the Drive you want to "
                 "back up. Copy the URL and open it in your browser.").classes(
            "text-sm").style(f"color:{MUTED}")
        with ui.row().classes("w-full items-center gap-2 mt-2"):
            ui.input("Authorization URL", value=url).props(
                "readonly outlined dense").classes("flex-1")
            ui.button(icon="content_copy", on_click=lambda: ui.clipboard.write(url))\
                .props("outline").tooltip("Copy URL")
        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("Open in browser", icon="open_in_new",
                      on_click=lambda: ui.open(url, new_tab=True)).props(
                "color=primary no-caps")
            ui.button("Close", on_click=dlg.close).props("flat")
    dlg.open()
    if on_done:
        dlg.on_close(lambda: on_done())
    return dlg


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
    """Native folder picker (Windows). Blocks while open, returns path or None."""
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