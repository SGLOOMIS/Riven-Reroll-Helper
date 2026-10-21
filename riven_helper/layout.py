"""Where each panel goes, and rendering the panels for a frame.

Coordinates are pixels within the captured game window (W x H). The same plan is used by the
live overlay, F10 snapshots and video replays, so all three show exactly the same thing.

  card panels   just above each riven card; slid sideways if they'd overlap, or beside / below the
                card when there's no room above. Never over a card, the bottom buttons or FITS IN.
  IDEAL ROLL    at the left edge, between the header and the bottom buttons
  IDEAL RIVEN   on the upgrade screen, in the empty area by the arcane slot (see UPGRADE_AREA)
"""

from .advice import progress
from .panel_text import card_rows, ideal_rows, kuva_to_target, upgrade_rows
from .style import render_panel
from .theme import detect as detect_theme
from .theme import palette

GAP = 8                     # px kept between panels and anything they must not touch
ABOVE_GAP = 10              # px between a card panel and the top of its card
BUTTON_ZONE = 0.85          # below this fraction of the height are the Cycle / Lock Trait / Cancel buttons
FITS_IN = (0.84, 0.64, 1.0, 0.85)       # the FITS IN panel at the bottom right (x0, y0, x1, y1 fractions)
IDEAL_AT = (0.02, 0.17)                 # IDEAL ROLL's top-left corner (fractions)
KUVA_TIE = 0.05                         # BETTER by Kuva only for a card expected to take over 5% less
# Upgrade screen: the empty area for IDEAL RIVEN (x, y, width, height fractions). On gun screens it's
# below the arcane slot on the right; on melee screens the arcane slot is at the top right, beside
# COMBOS, and the area is right below it.
UPGRADE_AREA = {"gun": (0.822, 0.442, 0.151, 0.118), "melee": (0.822, 0.305, 0.151, 0.255)}


def text_scale(cfg, H):
    """Panel size for this window: font_size is for 1080p."""
    return max(7, round(cfg["font_size"] * H / 1080)) / cfg["font_size"]


def card_rect(geometry, W, H):
    """The whole card (art, title, stats) estimated from its stat lines.

    geometry is (x, y, w, h, line height) with the box reaching down to the card's MR footer. The
    card has a fixed size and its text grows upward over the art, so it's measured up from the
    footer, in line heights (it's ~21.6 tall and ~16.9 wide at 1080p); on the cycle screen the
    unselected card is drawn smaller, and its text with it.
    """
    x, y, w, h = geometry[:4]
    line_h = geometry[4] if len(geometry) > 4 and geometry[4] else H * 0.0167
    cx, bottom = x + w / 2, y + h
    half = max(w / 2 + 25, 8.45 * line_h)
    top = min(y, bottom - 21.6 * line_h)
    return (cx - half, top, 2 * half, bottom - top)


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw + GAP and bx < ax + aw + GAP and ay < by + bh + GAP and by < ay + ah + GAP


def place_card_panels(items, W, H, avoid=()):
    """Top-left corners for every card's panel, placed together so they never overlap.

    items: [(card geometry, (panel width, panel height))]. avoid: rectangles to keep off (IDEAL ROLL).
    The selected (larger) card is placed first. Each panel takes the first clear spot of: just above
    its card (or slid sideways from there, staying over the card), beside it on the outer side,
    beside it on the inner side, below its stats.
    """
    cards = [card_rect(g, W, H) for g, _ in items]
    fits_in = (W * FITS_IN[0], H * FITS_IN[1], W * (FITS_IN[2] - FITS_IN[0]), H * (FITS_IN[3] - FITS_IN[1]))
    by_x = sorted(range(len(items)), key=lambda i: cards[i][0])
    placed, spots = list(avoid), [None] * len(items)

    for i in sorted(range(len(items)), key=lambda i: -(items[i][0][4] if len(items[i][0]) > 4 else 0)):
        geometry, (pw, ph) = items[i]
        cx, top, cw, _ = cards[i]
        if len(items) == 1:
            outer = "right" if cx + cw / 2 >= W * 0.45 else "left"
        else:
            outer = "left" if by_x.index(i) < len(items) / 2 else "right"
        inner = "left" if outer == "right" else "right"

        def beside(side):
            px = cx + cw + GAP + 1 if side == "right" else cx - pw - GAP - 1
            py = min(geometry[1] + geometry[3] - ph, H * BUTTON_ZONE - ph)
            return (int(px), int(max(GAP, py)), pw, ph)

        above = (int(cx + cw / 2 - pw / 2), int(top - ph - ABOVE_GAP - 1), pw, ph)
        slid = [above]                                  # moved just clear of whatever it hits
        for p in placed + [c for j, c in enumerate(cards) if j != i]:
            if _overlap(above, p):
                slid += [(int(p[0] + p[2] + GAP + 1), above[1], pw, ph), (int(p[0] - GAP - 1 - pw), above[1], pw, ph)]
        slid = sorted((s for s in slid if s[0] < cx + cw / 2 < s[0] + pw), key=lambda s: abs(s[0] - above[0]))
        below = (int(geometry[0] + geometry[2] / 2 - pw / 2), int(geometry[1] + geometry[3] + GAP), pw, ph)
        # (spot, may it touch its own card): above / below sit against the card on purpose
        tries = [(s, True) for s in slid] + [(beside(outer), False), (beside(inner), False), (below, True)]

        def clear(r, own_card_ok):
            x, y, w, h = r
            if x < 0 or y < 0 or x + w > W or y + h > H * BUTTON_ZONE or _overlap(r, fits_in):
                return False
            if any(_overlap(r, c) for j, c in enumerate(cards) if j != i or not own_card_ok):
                return False
            return not any(_overlap(r, p) for p in placed)

        spot = next((t for t, ok in tries if clear(t, ok)), None)
        if spot is None:                                # nothing clear: above the card, stacked up past others
            x, y = max(GAP, min(above[0], W - pw - GAP)), above[1]
            for p in list(placed):
                if _overlap((x, y, pw, ph), p):
                    y = p[1] - ph - GAP
            spot = (x, max(GAP, y), pw, ph)
        spots[i] = spot
        placed.append(spot)
    return [(int(s[0]), int(s[1])) for s in spots]


def best_flags(results, analyzer):
    """Which card gets the BETTER badge: the one the reroll strategy (flow.plan) is expected to finish for
    less Kuva, as their panels show (within KUVA_TIE of each other, neither); without a target, or before
    the plans are worked out, the one further towards the ideal roll (advice.progress); with next-step
    advice off, the higher rating. Only when one is strictly ahead."""
    kuva = [kuva_to_target(r, analyzer) for r in results] if analyzer.cfg.get("next_step", True) else []
    if len(kuva) >= 2 and all(k is not None for k in kuva) and min(kuva) < float("inf"):
        best = min(kuva)
        if sum(k <= best * (1 + KUVA_TIE) for k in kuva) > 1:   # as good as each other: no badge
            return [False] * len(kuva)
        return [k == best for k in kuva]
    if analyzer.cfg.get("next_step", True):
        scores = [progress(r, analyzer)[0] if r.ev else (-1,) for r in results]
    else:                                         # next-step advice off: simply the higher rating
        scores = [(0, 0.0, r.rating.score) if r.ev else (-1,) for r in results]
    if len(scores) < 2 or max(scores) <= (0, 0.0, 0.0) or scores.count(max(scores)) > 1:
        return [False] * len(scores)
    return [s == max(scores) for s in scores]


def plan_riven_screen(analyzer, results, W, H, cfg, geometries=None, theme=None):
    """Render the panels for the riven / cycle screen (in theme's colours) and place them.

    Returns (cards, ideal): cards is [(image, (x, y))] in result order, ideal is (image, (x, y)) or
    None. geometries replaces the cards' read-time geometry (after they've moved on screen).
    """
    colours = palette(theme)
    scale, base = text_scale(cfg, H), cfg["font_size"]
    ideal, avoid = None, []
    rows = ideal_rows(analyzer, results)
    if rows:
        image = render_panel(rows, scale, base, palette=colours)
        at = (int(W * IDEAL_AT[0]), int(H * IDEAL_AT[1]))
        ideal = (image, at)
        avoid.append((*at, image.width, image.height))
    alone = len(results) == 1
    images = [render_panel(card_rows(analyzer, r, best, alone), scale, base, highlight=best, palette=colours)
              for r, best in zip(results, best_flags(results, analyzer))]
    geometries = geometries or [r.card.geometry for r in results]
    spots = place_card_panels([(g, im.size) for g, im in zip(geometries, images)], W, H, avoid)
    return list(zip(images, spots)), ideal


def plan_upgrade_screen(analyzer, weapon_name, W, H, cfg, theme=None, config=None):
    """The IDEAL RIVEN panel for a weapon's upgrade screen, fitted into UPGRADE_AREA: the largest text
    that fits, with the negatives on one line or wrapped two or one per line. (image, (x, y)) or None."""
    if not cfg.get("config_rolls", True):
        config = None                             # config-specific rolls off: always the first roll
    if not upgrade_rows(analyzer, weapon_name, config=config):
        return None
    weapon = analyzer.gamedata.weapon_by_base_name(weapon_name)
    fx, fy, fw, fh = UPGRADE_AREA["melee" if weapon and weapon.cls == "melee" else "gun"]
    ax, ay, aw, ah = fx * W, fy * H, fw * W, fh * H
    scale = text_scale(cfg, H)
    image = None
    for shrink in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6):
        for per_line in (3, 2, 1):
            image = render_panel(upgrade_rows(analyzer, weapon_name, per_line, config), scale * shrink,
                                 cfg["font_size"],
                                 min_width=aw * 0.9 - 14 * scale * shrink, palette=palette(theme))
            if image.width <= aw + 2 and image.height <= ah + 2:
                return image, (int(ax + aw - image.width), int(ay))
    return image, (int(ax + aw - image.width), int(ay))


def render_to_image(img, analyzer, results, cfg, upgrade_weapon=None, theme=None, config=None):
    """A screenshot with the overlay's panels pasted on (F10 snapshots, --image --out), in theme's
    colours (by default the theme read off the screenshot itself)."""
    theme = theme or detect_theme(img)
    out = img.convert("RGBA")
    cards, ideal = plan_riven_screen(analyzer, results, img.width, img.height, cfg, theme=theme)
    panels = cards + ([ideal] if ideal else [])
    if upgrade_weapon and not results:
        plan = plan_upgrade_screen(analyzer, upgrade_weapon, img.width, img.height, cfg, theme, config)
        panels += [plan] if plan else []
    for panel, (x, y) in panels:
        out.alpha_composite(panel, (int(x), int(y)))
    return out.convert("RGB")
