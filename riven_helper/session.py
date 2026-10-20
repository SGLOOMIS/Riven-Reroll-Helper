"""What to do with each captured frame: read it, follow the cards, or wait.

Kept apart from the live loop (app.py) so the same logic can be replayed on a screen recording
(tools/replay_video.py). Session.step(frame) returns events for the overlay:

  ("results", (img, lines, results))  a trusted reading of the riven cards on screen
  ("hold", None)                      a new reading is being confirmed: show no card panels yet
  ("track", [card position or None])  where each card is now (None: lost, or dimmed by a dialog)
  ("relayout", [card geometry])       the cards slid somewhere new and stopped: place panels again
  ("upgrade", weapon or None)         the weapon upgrade screen opened (for which weapon) or closed
  ("config", name or None)            the config tab selected on the upgrade screen ("CONFIG A", "Main")
  ("theme", Theme)                    the player's UI theme, when first seen or changed (theme.py)

Rules:
  * No cards known: read (OCR) once a second, which also notices the upgrade screen; but only when
    the frame has a menu header (upgrade_screen.has_header), so no OCR runs during missions.
  * Cards known: find each card again in every frame (tracker.py) and
      - a card stays unmatched (rerolled, confirmed, the screen closed) -> wait for the cards'
        area to settle, then read again;
      - a lone card moves (the cycle animation starting) -> read once it settles;
      - the cycle screen's two cards slide but are still found (switching between the old and
        new riven) -> no read; once they stop, re-lay out the panels.
  * A stat locked or unlocked on the riven screen (LOCK_AREA changes) -> read again.
  * The upgrade screen's panel showing: its header is compared with the upgrade screen's in every
    frame (no OCR), so leaving the screen hides the panel at once.
  * A reading is only shown once trustworthy (see _trust).
"""

import time

import cv2
import numpy as np
from PIL import Image

from .tracker import CardTracker, to_gray_small
from .theme import button_colour
from .theme import detect as detect_theme
from .upgrade_screen import HEADER_AREA, UpgradeScreen, has_header

SCAN_EVERY = 1.0             # s between reads while no cards are known
FAST, SLOW = 1 / 30, 1 / 8   # s between frames while cards move / while they're still
LOST_GRACE = 0.45            # s a card must stay unmatched before it counts as replaced (cursor, flashes)
SETTLE_FRAMES = 3            # frames without change before the picture counts as settled
SETTLE_DIFF = 3.0            # mean pixel difference (0-255) of the cards' area below which it's unchanged
GIVE_UP_WAITING = 2.0        # s after which a changed screen is read even if it hasn't settled
MOVE_PX, MOVE_SCALE = 3, 0.015   # how far a card must move / resize between frames to count as moving
DIMMED = 0.5                 # card text darker than this share of normal: a dialog is over it
CONFIRM_AFTER = 0.6          # s before re-reading to confirm a reading
MAX_CONFIRMS = 3
RIVEN_SCREEN_GRACE = 5.0     # s the riven screen's labels may be hidden (dialog, animation) and still count
# The riven screen shows the locked trait above LOCK TRAIT ("[lock] +89.4% Critical Damage  x"). Locking or
# unlocking only adds or removes a small icon on the card, so a change here is what triggers a new read.
LOCK_AREA = (0.05, 0.765, 0.22, 0.815)      # x0, y0, x1, y1 as fractions of the window
LOCK_CHANGE = 12.0           # mean pixel difference (0-255) in LOCK_AREA that counts as a lock change
# Leaving the upgrade screen: the header (UPGRADES/<weapon>) no longer looks like it did there.
HEADER_CHANGED = 0.2         # share of the header's pixels that must have changed (the cursor alone is less)
LEFT_AFTER = 2               # frames in a row with the header changed (not a single flicker)
UPGRADE_WATCH = 1 / 15       # s between those checks while the upgrade screen's panel is showing


def to_image(frame):
    """A BGR or BGRA numpy frame as a PIL RGB image."""
    if frame.shape[2] == 4:
        return Image.frombuffer("RGB", (frame.shape[1], frame.shape[0]), frame.tobytes(), "raw", "BGRX", 0, 1)
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


class Session:
    def __init__(self, analyzer, ocr):
        self.analyzer, self.ocr = analyzer, ocr
        self.tracker = CardTracker()
        self.upgrade = UpgradeScreen()
        self.theme = None                    # the UI theme in use (reported once two reads agree)
        self._theme_seen = None
        self._button = None                  # the riven screen's button fill, once seen (panel background)
        self.reads = 0                       # OCR passes so far
        self.results = []                    # the cards of the last reading
        self.riven_screen_seen = -1e9        # when the riven screen's labels were last read
        self.img, self.lines = None, []      # the last frame read, and its OCR lines
        self.lock_area = None                # LOCK_AREA at the last read
        self.upgrade_header = None           # the header as the upgrade screen showed it (half-size grey)
        self._header_changes = 0
        self.reset()

    def reset(self):
        """Forget the cards on screen (e.g. the game window lost focus)."""
        self.tracker.clear()
        self.results = []
        self.last_read = -1e9
        self.last_motion = -1e9
        self.moved = False                   # cards moved since the last read / relayout
        self.changed = False                 # a card was replaced: read once things settle
        self.prev_positions = self.prev_area = None
        self.still_frames = 0
        self.lost_since = {}                 # card index -> when it stopped matching
        self.confirm_at = None               # when to re-read a reading that isn't trusted yet
        self.confirms = 0
        self.prev_signature = None
        self.shown_before = False            # a reading has been shown since the riven screen appeared

    # -- reading -----------------------------------------------------------------------------
    def _read(self, frame, now, after_change=False):
        img = to_image(frame)
        results, lines = self.analyzer.analyze_image(img, self.ocr)
        self.reads += 1
        self.lines, self.img = lines, img
        self.lock_area = self._lock_area(to_gray_small(frame))
        # Only the riven and cycle screens count, not a riven selected in the inventory grid.
        if any(r.card.riven_screen for r in results):
            self.riven_screen_seen = now
        elif now - self.riven_screen_seen > RIVEN_SCREEN_GRACE:
            results = []
        results = [r for r in results if r.ev is not None]     # unidentifiable (half faded) cards: no panel

        self.last_read, self.results = now, results
        self.tracker.set_cards(img, [r.card.geometry for r in results])
        self.moved = self.changed = False
        self.prev_positions = self.prev_area = None
        self.still_frames = 0
        self.lost_since = {}
        return self._trust(results, now, after_change, img, lines)

    def _trust(self, results, now, after_change, img, lines):
        """Show a reading right away when it's clean and the screen isn't mid-change; otherwise read
        again shortly and show it once two readings agree (or after MAX_CONFIRMS tries). The riven
        screen animates in, the second card fades in a moment after the cycle animation, and
        half-faded text can drop a line, so a doubtful reading is never shown."""
        signature = tuple((r.ev.weapon.name, r.ev.rank, tuple((s.name, round(s.magnitude, 3)) for s in r.ev.stats))
                          for r in results)
        doubtful = any(not r.ev.consistent or r.ev.notes for r in results)
        first_sight = bool(results) and not self.shown_before
        unsure = doubtful or first_sight or (after_change and len(results) < 2)
        agrees = signature == self.prev_signature and not doubtful
        self.prev_signature = signature
        if results and unsure and not agrees and self.confirms < MAX_CONFIRMS:
            self.confirms += 1
            self.confirm_at = now + CONFIRM_AFTER
            return ("hold", None)
        self.confirms, self.confirm_at = 0, None
        self.shown_before = bool(results)
        return ("results", (img, lines, results))

    def _theme_event(self):
        """("theme", Theme) when the last two reads agree on a theme other than the current one."""
        self._button = button_colour(self.img, self.lines) or self._button
        seen = detect_theme(self.img, button=self._button)
        agreed = seen is not None and seen.close_to(self._theme_seen)
        self._theme_seen = seen
        if agreed and not seen.close_to(self.theme):
            self.theme = seen
            return [("theme", seen)]
        return []

    def _upgrade_event(self):
        """("upgrade", weapon or None) when the upgrade screen's weapon changes, and ("config", name) when
        another config tab is selected on it; else nothing."""
        before, config_before = self.upgrade.weapon, self.upgrade.config
        if self.results or not self.analyzer.cfg.get("upgrade_overlay", True):
            self.upgrade.clear()
        else:
            self.upgrade.update(self.img, self.lines, self.ocr, self.analyzer.gamedata)
        # Remember how the header looks here, to notice leaving the screen without OCR (step).
        self.upgrade_header = self._header(to_gray_small(self.img)) if self.upgrade.weapon else None
        self._header_changes = 0
        events = []
        if self.upgrade.config != config_before:
            events.append(("config", self.upgrade.config))
        if self.upgrade.weapon != before:
            events.append(("upgrade", self.upgrade.weapon))
        return events

    # -- each frame ----------------------------------------------------------------------------
    def step(self, frame, now=None):
        """Handle one frame (BGR or BGRA numpy array). Returns (events, seconds until the next frame)."""
        now = time.time() if now is None else now
        if not self.tracker.tracks:
            if self.upgrade.weapon and self._left_upgrade_screen(frame):
                self.upgrade.clear()                 # hide the panel now; read what's there next frame
                self.last_read = -1e9
                return [("upgrade", None)], UPGRADE_WATCH
            if now - self.last_read < SCAN_EVERY:
                return [], UPGRADE_WATCH if self.upgrade.weapon else 0.25
            if not has_header(frame):              # not a menu screen (a mission): nothing to read
                self.last_read = now
                return [], 0.25
            return [self._read(frame, now)] + self._upgrade_event() + self._theme_event(), 0.25
        return self._watch(frame, now)

    def _header(self, gray):
        h, w = gray.shape
        x0, y0, x1, y1 = HEADER_AREA
        return gray[int(h * y0):int(h * y1), int(w * x0):int(w * x1)].astype(np.int16)

    def _left_upgrade_screen(self, frame):
        """Has the header stopped looking like the upgrade screen's (for LEFT_AFTER frames in a row)?"""
        if self.upgrade_header is None:
            return False
        now = self._header(to_gray_small(frame))
        changed = now.shape != self.upgrade_header.shape or \
            float(np.mean(np.abs(now - self.upgrade_header) > 40)) > HEADER_CHANGED
        self._header_changes = self._header_changes + 1 if changed else 0
        return self._header_changes >= LEFT_AFTER

    def _lock_area(self, gray):
        h, w = gray.shape
        x0, y0, x1, y1 = LOCK_AREA
        return gray[int(h * y0):int(h * y1), int(w * x0):int(w * x1)].astype(np.int16)

    def _lock_changed(self, gray):
        """A stat was locked or unlocked since the last read (only the single-card riven screen has locks)."""
        if len(self.results) != 1 or self.lock_area is None:
            return False
        area = self._lock_area(gray)
        return area.shape == self.lock_area.shape and float(np.mean(np.abs(area - self.lock_area))) > LOCK_CHANGE

    def _watch(self, frame, now):
        gray = to_gray_small(frame)
        tracks = self.tracker.update(gray)
        if self.confirm_at is None and not self.changed and self._lock_changed(gray):
            self.confirm_at = now + CONFIRM_AFTER / 2     # read once the lock dialog has gone
        positions = [(t.x, t.y, t.scale) if t and not t.lost else None for t in tracks]
        events = [("track", [(t.x, t.y, t.scale, t.origin) if p and t.dim >= DIMMED else None
                             for t, p in zip(tracks, positions)])]
        moving = self.prev_positions is not None and any(
            a and b and (abs(a[0] - b[0]) > MOVE_PX or abs(a[1] - b[1]) > MOVE_PX or abs(a[2] - b[2]) > MOVE_SCALE)
            for a, b in zip(positions, self.prev_positions))
        self.prev_positions = positions
        if moving:
            self.last_motion, self.moved = now, True

        for i, t in enumerate(tracks):
            if t is not None and t.lost:
                self.lost_since.setdefault(i, now)
            else:
                self.lost_since.pop(i, None)
        all_lost = all(t is None or t.lost >= 2 for t in tracks)
        if all_lost or any(now - since >= LOST_GRACE for since in self.lost_since.values()):
            self.changed = True

        if self.changed:
            # Waiting for the new picture: compare the cards' area (not the animated background).
            area = self._cards_area(gray)
            steady = (self.prev_area is not None and self.prev_area.shape == area.shape
                      and float(np.mean(cv2.absdiff(area, self.prev_area))) < SETTLE_DIFF)
            self.prev_area = area
        else:
            steady = not moving and not self.lost_since
        self.still_frames = self.still_frames + 1 if steady and now - self.last_motion > 0.06 else 0
        settled = self.still_frames >= SETTLE_FRAMES

        if self.confirm_at is not None and now >= self.confirm_at and not self.changed and not moving:
            self.confirm_at = None
            return events + [self._read(frame, now)] + self._theme_event(), FAST
        waited = now - max(self.last_motion, min(self.lost_since.values(), default=now))
        if self.changed and (settled or waited > GIVE_UP_WAITING):
            events += [self._read(frame, now, after_change=True)] + self._theme_event()
        elif self.moved and settled:
            if len(self.results) >= 2:          # the cycle screen's cards swapped places: same rivens
                events.append(("relayout", [self.tracker.map_box(i, r.card.geometry) if self.tracker.tracks[i]
                                            else r.card.geometry for i, r in enumerate(self.results)]))
                self.moved = False
            else:                               # a lone card moving: the cycle animation began
                events += [self._read(frame, now)] + self._theme_event()
        busy = moving or self.changed or self.moved or now - self.last_motion < 1.0
        return events, FAST if busy else SLOW

    def _cards_area(self, gray):
        """The part of the (half-size) frame around every card, where it was read and where it is now."""
        found = [t for t in self.tracker.tracks if t]
        if not found:
            return gray
        s = 0.5
        x0 = min(min(t.x, t.origin[0]) for t in found) * s
        x1 = max(max(t.x + t.size[0] * t.scale, t.origin[0] + t.size[0]) for t in found) * s
        y0 = min(min(t.y, t.origin[1]) for t in found) * s
        y1 = max(max(t.y + t.size[1] * t.scale, t.origin[1] + t.size[1]) for t in found) * s
        h, w = gray.shape
        pad = (x1 - x0) * 0.15
        return gray[int(max(0, y0 - pad)):int(min(h, y1 + pad)), int(max(0, x0 - pad)):int(min(w, x1 + pad))]
