"""The live overlay.

A worker thread takes screenshots of the game and runs the Session on them; the main thread turns
the Session's events into panels (OverlayState) and shows them in click-through windows on top of
the screen (winpanel.py). Everything works from screenshots: the overlay never attaches to the
game, reads or changes its memory, or sends it input.

It normally runs inside the roll editor's window (Riven Helper.bat): App(root=the editor's window)
uses that window's event loop, and report() puts the overlay's status in the editor. Alone
(python -m riven_helper --overlay) it has a hidden window of its own and prints to the console.

Hotkeys (config.json): toggle the overlay, reload roll files, save a snapshot to debug/.
"""

import ctypes
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import ROOT, load_config
from .layout import render_to_image, text_scale
from .odds import chance_of_better
from .overlay_state import OverlayState
from .style import render_status
from .theme import palette

KEY_CODES = {f"F{i}": 0x6F + i for i in range(1, 13)} | {"INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
                                                       "PAUSE": 0x13, "SCROLLLOCK": 0x91}
TICK_MS = 15                       # how often panels are redrawn


class App:
    def __init__(self, cfg, analyzer, root=None, report=print):
        """root: a Tk window whose event loop to share (the editor's); without one, a hidden one of its own.
        report(text): where status messages go (the console, or the editor's status line)."""
        import tkinter as tk
        self.cfg, self.analyzer, self.report = cfg, analyzer, report
        if root is None:
            root = tk.Tk()             # only for its event loop and timers; never shown
            root.withdraw()
        self.root = root
        self.events = queue.Queue()    # (kind, area, payload) from the worker thread
        self.running = True
        self.rescan = threading.Event()
        self.state = OverlayState(analyzer, cfg)
        self.windows = {}              # panel key -> winpanel.Panel
        self.status_window = None
        self.area = None               # where the game is on screen (left, top, width, height)
        self.last_read = None          # (image, OCR lines, results), for F10 snapshots
        self.upgrade_weapon = None     # for F10 snapshots on the upgrade screen
        self.reads = 0
        self.message, self.message_until = self._library_summary(), time.time() + 6
        if cfg.get("_problem"):
            self.report(cfg["_problem"])
            self.message = cfg["_problem"]
        self.keys = {name: KEY_CODES.get(str(key).upper()) for name, key in cfg["hotkeys"].items()}
        self.config_path = Path(cfg.get("_path", ROOT / "config.json"))
        self.config_time = self._config_time()
        self.keys_down = {}

    def _library_summary(self):
        lib = self.analyzer.library
        for w in lib.warnings:
            self.report("WARNING: " + w)
        text = f"Riven Helper: {len(lib.files)} roll file(s), {sum(map(len, lib.rolls.values()))} rolls"
        return text + (f"  |  {len(lib.warnings)} warning(s): {lib.warnings[0]}" if lib.warnings else "")

    def _config_time(self):
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return None

    def flash(self, text, seconds=4):
        self.message, self.message_until = text, time.time() + seconds

    # -- worker thread: screenshots and the session -----------------------------------------
    def worker(self):
        from .capture import Ocr, Screen, find_game
        from .session import Session
        ocr = Ocr()
        self.events.put(("status", None, f"OCR language: {ocr.language}"))
        if not ocr.language.startswith("en"):
            self.events.put(("status", None, "WARNING: no English OCR installed; add English in Windows' "
                                             "language settings (Time & language > Language & region)"))
        session, screen = Session(self.analyzer, ocr), Screen()
        status = None
        while self.running:
            started, wait = time.time(), 1.0
            try:
                if self._config_time() != self.config_time:   # saved (e.g. by the editor's Settings tab)
                    self.config_time = self._config_time()
                    self.analyzer.apply_settings(load_config(self.config_path))
                    self.events.put(("settings", None, None))
                    self.rescan.set()
                if self.rescan.is_set() or self.analyzer.library.changed():
                    if self.analyzer.library.changed():
                        self.analyzer.library.reload()
                        self.events.put(("reloaded", None, None))
                    self.rescan.clear()
                    session.reset()
                area, now_status = find_game(self.cfg["window_title"])
                if now_status != status:              # say what's going on, once per change
                    self.events.put(("status", None, now_status))
                    status = now_status
                if area is None:                 # not open, minimised, or not in front
                    self.events.put(("hide", None, None))
                    session.reset()
                else:
                    events, wait = session.step(screen.grab(area))
                    self.reads = session.reads
                    for kind, payload in events:
                        if kind == "results" and len(payload[2]) == 1:
                            chance_of_better(payload[2][0], self.analyzer)   # worked out here, not while drawing
                        self.events.put((kind, area, payload))
            except Exception as e:               # keep going; show what went wrong
                self.events.put(("error", None, f"{type(e).__name__}: {e}"))
            self.rescan.wait(max(0.005, wait - (time.time() - started)))

    # -- main thread: events -> panels -------------------------------------------------------
    def _handle(self, kind, area, payload):
        if area is not None:
            self.area = area
        size = (area[2], area[3]) if area else None
        if kind == "results":
            img, lines, results = payload
            summary = [(r.ev.weapon.name, r.rating.score) for r in results]
            if summary != getattr(self, "_last_summary", None):
                self.report(f"read {self.reads}: " + (", ".join(f"{w} {s:.0f}%" for w, s in summary)
                                                      or "no riven cards"))
                self._last_summary = summary
            self.last_read = (img, lines, results)
            self.state.on_results(size, results)
        elif kind == "track":
            self.state.on_track(payload)
        elif kind == "relayout":
            self.state.on_relayout(payload)
        elif kind == "hold":
            self.state.on_hold()
        elif kind == "config":
            self.state.on_config(payload)
        elif kind == "upgrade":
            self.upgrade_weapon = payload
            self.state.on_upgrade(size, payload)
        elif kind == "theme":
            self.report(f"UI theme: {payload.primary} / {payload.accent} on {payload.background}")
            self.state.on_theme(payload)
        elif kind == "hide":
            self.state.on_hide()
        elif kind == "status":
            self.report(payload)
        elif kind == "settings":
            self.report(self.cfg.get("_problem") or "Settings changed (config.json): applied")
            self.flash("Settings applied: " + self._library_summary(), 6)
        elif kind == "reloaded":
            self.flash(self._library_summary(), 6)
        elif kind == "error":
            self.report("ERROR: " + payload)
            self.flash(payload, 5)

    def _draw(self):
        from .winpanel import Panel
        left, top = self.area[:2] if self.area else (0, 0)
        showing = set()
        for key, image, x, y, alpha in self.state.tick():
            if key not in self.windows:
                self.windows[key] = Panel()
            window = self.windows[key]
            window.set_image(image, key=id(image))
            window.place(left + x, top + y, alpha)
            window.show()
            showing.add(key)
        for key, window in self.windows.items():
            if key not in showing:
                window.hide()
        self._draw_status(left, top)

    def _draw_status(self, left, top):
        """The hint line in the top-left corner (or a message, e.g. after reloading roll files)."""
        from .winpanel import Panel
        text = self.message if time.time() < self.message_until else None
        if text is None and ((self.last_read and self.last_read[2]) or self.upgrade_weapon):
            k = self.cfg["hotkeys"]
            text = f"Riven Helper   {k['toggle']} hide   {k['reload']} reload rolls   {k['snapshot']} snapshot"
        if not text or not self.state.visible or not self.area:
            if self.status_window:
                self.status_window.hide()
            return
        self.status_window = self.status_window or Panel()
        scale = text_scale(self.cfg, self.area[3])
        key = (text, scale, self.state.theme)
        if key != self.status_window.image_key:           # draw the text only when it changes
            self.status_window.set_image(render_status(text, scale, self.cfg["font_size"], palette(self.state.theme)),
                                         key=key)
        self.status_window.place(left + 8, top + 8, 255)
        self.status_window.show()

    def _pressed(self, name):
        code = self.keys.get(name)
        if not code:
            return False
        down = bool(ctypes.windll.user32.GetAsyncKeyState(code) & 0x8000)
        was, self.keys_down[name] = self.keys_down.get(name, False), down
        return down and not was

    def tick(self):
        if self._pressed("toggle"):
            self.state.visible = not self.state.visible
        if self._pressed("reload"):
            self.analyzer.library.reload()
            self.flash(self._library_summary(), 6)
            self.rescan.set()
        if self._pressed("snapshot") and self.last_read:
            self.flash(f"Saved {self.snapshot()}", 4)
        try:
            while True:
                self._handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self._draw()
        self.root.after(TICK_MS, self.tick)

    def snapshot(self):
        """Save the last frame read, its OCR text and the overlay drawn on it, to debug/."""
        out = ROOT / "debug"
        out.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        img, lines, results = self.last_read
        img.save(out / f"{stamp}.png")
        (out / f"{stamp}.ocr.json").write_text(json.dumps(lines, indent=1), encoding="utf-8")
        annotated = render_to_image(img, self.analyzer, results, self.cfg, self.upgrade_weapon, self.state.theme,
                                    self.state.upgrade_config)
        annotated.save(out / f"{stamp}.annotated.png")
        return out / f"{stamp}.png"

    def start(self):
        """Start watching the game (the event loop is whoever owns root)."""
        threading.Thread(target=self.worker, daemon=True).start()
        self.root.after(TICK_MS, self.tick)

    def run(self):
        """Run on its own, until the hidden window's event loop ends (Ctrl+C in the console)."""
        self.start()
        try:
            self.root.mainloop()
        finally:
            self.running = False
