"""Which panels are showing, where, and how faded, frame by frame.

Turns Session events into panels to draw. Card panels only show while the screen is at rest in
one of the reroll states (the riven screen, or the cycle screen with either riven selected): when
a card moves away from where its panel was placed, the panel fades out, and once the cards come to
rest ("relayout") it fades back in at its new spot. The live overlay draws the result with layered
windows; tools/replay_video.py pastes it onto a recording. Coordinates are within the game window.
"""

from dataclasses import dataclass

from .layout import plan_riven_screen, plan_upgrade_screen

FADE_IN, FADE_OUT = 50, 90          # opacity change per tick (~15 ms): quick to hide, gentle to show
MOVED = 6                           # px a card must be away from its spot for its panel to hide


@dataclass
class Panel:
    image: object
    x: float
    y: float
    wanted: bool = True             # should be visible (it fades towards this)
    alpha: int = 0
    home: tuple = None              # card panels: where their card rests (tracked x, y, scale)

    def fade(self, visible):
        step = FADE_IN if (self.wanted and visible) else -FADE_OUT
        self.alpha = max(0, min(255, self.alpha + step))


class OverlayState:
    def __init__(self, analyzer, cfg):
        self.analyzer, self.cfg = analyzer, cfg
        self.size = None                # (W, H) of the game window
        self.results = []
        self.cards = []                 # one Panel per riven card
        self.ideal = None               # IDEAL ROLL
        self.upgrade = None             # IDEAL RIVEN on the upgrade screen
        self.visible = True             # F8 toggles this
        self._tracks = []

    def on_results(self, size, results):
        """A trusted new reading: panels for its cards (fading in) and IDEAL ROLL."""
        self.size, self.results = size, results
        cards, ideal = plan_riven_screen(self.analyzer, results, size[0], size[1], self.cfg)
        alphas = [c.alpha for c in self.cards]
        self.cards = [Panel(image, x, y, alpha=alphas[i] if i < len(alphas) else 0)
                      for i, (image, (x, y)) in enumerate(cards)]
        self._tracks = []
        if ideal:
            self.ideal = Panel(ideal[0], *ideal[1], alpha=self.ideal.alpha if self.ideal else 0)
        elif self.ideal:
            self.ideal.wanted = False

    def on_track(self, tracks):
        """Hide a card's panel while its card is lost, dimmed, or away from where the panel was placed."""
        self._tracks = tracks
        for panel, t in zip(self.cards, tracks):
            if t is None:
                panel.wanted = False
                continue
            x, y, scale, _ = t
            if panel.home is None:          # the first sighting after a reading is where the card rests
                panel.home = (x, y, scale)
            hx, hy, hscale = panel.home
            panel.wanted = abs(x - hx) <= MOVED and abs(y - hy) <= MOVED and abs(scale - hscale) < 0.02

    def on_relayout(self, geometries):
        """The cards came to rest somewhere new: place their panels again there."""
        if not self.results or not self.size:
            return
        cards, _ = plan_riven_screen(self.analyzer, self.results, self.size[0], self.size[1], self.cfg, geometries)
        for i, (panel, (_, (x, y))) in enumerate(zip(self.cards, cards)):
            panel.x, panel.y = x, y
            t = self._tracks[i] if i < len(self._tracks) else None
            if t is not None:
                panel.home = (t[0], t[1], t[2])
                panel.wanted = True

    def on_upgrade(self, size, weapon_name):
        """The weapon upgrade screen opened for weapon_name, or closed (None)."""
        plan = plan_upgrade_screen(self.analyzer, weapon_name, size[0], size[1], self.cfg) if weapon_name else None
        if plan:
            self.upgrade = Panel(plan[0], *plan[1], alpha=self.upgrade.alpha if self.upgrade else 0)
        elif self.upgrade:
            self.upgrade.wanted = False

    def on_hold(self):
        """A new reading is being confirmed: the old card panels belong to cards that are gone."""
        self.cards = []

    def on_hide(self):
        """The game window isn't showing: hide everything."""
        for panel in self.cards + [p for p in (self.ideal, self.upgrade) if p]:
            panel.wanted = False

    def tick(self):
        """Advance the fades one step. Returns [(key, image, x, y, alpha)] to draw."""
        out = []
        for i, panel in enumerate(self.cards):
            panel.fade(self.visible)
            if panel.alpha:
                out.append((("card", i), panel.image, panel.x, panel.y, panel.alpha))
        if self.ideal:
            # IDEAL ROLL stays during slides, but hides while every card is hidden (a dialog is up).
            cards_hidden = bool(self._tracks) and all(t is None for t in self._tracks)
            self.ideal.fade(self.visible and not cards_hidden)
            if self.ideal.alpha:
                out.append((("ideal",), self.ideal.image, self.ideal.x, self.ideal.y, self.ideal.alpha))
        if self.upgrade:
            self.upgrade.fade(self.visible)
            if self.upgrade.alpha:
                out.append((("upgrade",), self.upgrade.image, self.upgrade.x, self.upgrade.y, self.upgrade.alpha))
        return out
