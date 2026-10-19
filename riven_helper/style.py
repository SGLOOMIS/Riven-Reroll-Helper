"""Panel rendering in the game's own look.

Colours are sampled from the riven screens: the orange of the game's labels
and button outlines, the dark navy of its buttons, and the lavender of riven
stat text. Panels are drawn as RGBA images so they can be translucent like
the game's own UI; the live overlay shows these images in layered windows,
and F10 snapshots paste the very same images onto the screenshot.

A panel is a list of rows:
    ("score", "87%", grade, is_best)      big rating with the RIVEN RATING label (and BETTER badge)
    ("title", "IDEAL ROLL")               heading in the game's orange label style
    ("label", text)                       which roll it matched
    ("stat", mark, name, value, tag)      one stat: tag picks the colour
    ("note", text, kind)                  explanation (kind "warn" or "bad")
    ("meta", text)                        weapon / rank / disposition
    ("rule",)                             thin divider
"""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ORANGE = (253, 132, 2)          # labels, outlines ("LOCK TRAIT", "FITS IN")
ORANGE_DIM = (172, 95, 14)
NAVY = (16, 24, 35)             # button fill
NAVY_TOP = (26, 36, 54)
LAVENDER = (172, 131, 213)      # riven stat text
LAVENDER_HI = (205, 180, 250)
TEXT = (222, 222, 232)          # light grey text ("Damage" on a wrapped line)
GREY = (128, 130, 148)
RED = (240, 88, 80)
GREEN = (126, 226, 160)

GRADE = {"great": GREEN, "good": (196, 228, 112), "ok": (253, 190, 60), "bad": RED}
TAG = {"good": LAVENDER_HI, "ok": LAVENDER, "unwanted": GREY, "harmless": (150, 196, 230), "neutral": GREY,
       "bad": RED, "dealbreaker": RED}
MARK = {"good": ORANGE, "ok": ORANGE_DIM, "unwanted": GREY, "harmless": (150, 196, 230), "neutral": GREY,
        "bad": RED, "dealbreaker": RED}

FONT_DIR = Path("C:/Windows/Fonts")
FONTS = {
    # The game's stat text is a Roboto-like sans; its labels a bold, slightly narrow face.
    "body": ["NotoSansJP-Regular.ttf", "NotoSans-Regular.ttf", "segoeui.ttf"],
    "bold": ["NotoSansJP-Bold.ttf", "NotoSans-Bold.ttf", "segoeuib.ttf"],
    "label": ["ARIALNB.TTF", "seguisb.ttf", "segoeuib.ttf"],
}


@lru_cache(maxsize=64)
def font(kind, size):
    for name in FONTS[kind]:
        path = FONT_DIR / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def _spaced_width(draw, text, f, spacing):
    return sum(draw.textlength(ch, font=f) for ch in text) + spacing * max(len(text) - 1, 0)


def _spaced_text(draw, xy, text, f, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + spacing


class Metrics:
    """Sizes in pixels for a panel drawn at `scale` (1.0 = 1080p game window)."""

    def __init__(self, scale=1.0, base=11):
        px = base * 1.45 * scale
        self.scale = scale
        self.body = font("body", max(9, round(px)))
        self.small = font("body", max(8, round(px * 0.85)))
        self.score = font("bold", max(14, round(px * 2.1)))
        self.label = font("label", max(9, round(px * 0.95)))
        self.title = font("label", max(11, round(px * 1.3)))
        self.line = round(px * 1.55)
        self.small_line = round(px * 1.35)
        self.pad = round(12 * scale)
        self.cut = round(9 * scale)          # chamfered corners, like the game's buttons
        self.tip = round(7 * scale)          # diamond tips on the side edges
        self.spacing = max(1, round(1.6 * scale))


def _row_height(row, m):
    kind = row[0]
    if kind == "score":
        return round(m.line * 2.0)
    if kind == "title":
        return round(m.line * 1.5)
    if kind == "rule":
        return round(m.line * 0.5)
    if kind in ("meta", "note", "label"):
        return m.small_line
    return m.line


def _row_width(draw, row, m):
    kind = row[0]
    if kind == "score":
        w = draw.textlength(row[1], font=m.score) + m.pad + _spaced_width(draw, "RIVEN RATING", m.label, m.spacing)
        if row[3]:
            w += m.pad + _spaced_width(draw, "BETTER", m.label, m.spacing) + 2 * m.pad
        return w
    if kind == "title":
        return _spaced_width(draw, row[1], m.title, m.spacing * 2)
    if kind == "stat":
        _, mark, name, value, _ = row
        return draw.textlength(f"{mark}  {name}", font=m.body) + 3 * m.pad + draw.textlength(value, font=m.body)
    if kind == "rule":
        return 0
    return draw.textlength(row[1], font=m.small)


def render_panel(rows, scale=1.0, base=11, highlight=False, min_width=0):
    """Draw one panel; returns an RGBA image."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    m = Metrics(scale, base)
    width = int(max([min_width, 200 * scale] + [_row_width(probe, r, m) for r in rows]) + 2 * m.pad)
    height = int(sum(_row_height(r, m) for r in rows) + 2 * m.pad)
    tip = m.tip
    img = Image.new("RGBA", (width + 2 * tip + 2, height + 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = tip + 1, 1, tip + width, height
    c = m.cut
    outline = [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1),
               (x0, y1 - c), (x0, y0 + c)]

    # Translucent navy glass with a slightly lighter top, like the game's buttons.
    fill = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill)
    fd.polygon(outline, fill=NAVY + (226,))
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for i in range(int(height * 0.45)):
        a = int(70 * (1 - i / (height * 0.45)))
        sd.line([(x0, y0 + i), (x1, y0 + i)], fill=NAVY_TOP + (a,))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    fill.alpha_composite(Image.composite(shade, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask))
    img.alpha_composite(fill)

    # Thin orange outline with diamond tips on the sides (brighter when this card is the better one).
    edge = ORANGE + ((235,) if highlight else (150,))
    d.line(outline + [outline[0]], fill=edge, width=2 if highlight else 1)
    mid = (y0 + y1) // 2
    for cx, direction in ((x0, -1), (x1, 1)):
        tx = cx + direction * (tip - 1)
        d.line([(cx, mid), (tx, mid)], fill=edge, width=1)
        d.polygon([(tx, mid - 3), (tx + 3 * direction, mid), (tx, mid + 3), (tx - 3 * direction, mid)], fill=edge)

    y = y0 + m.pad
    left, right = x0 + m.pad, x1 - m.pad
    for row in rows:
        kind = row[0]
        h = _row_height(row, m)
        if kind == "score":
            _, text, grade, best = row
            d.text((left, y - round(m.line * 0.15)), text, font=m.score, fill=GRADE.get(grade, TEXT))
            lx = left + d.textlength(text, font=m.score) + m.pad
            _spaced_text(d, (lx, y + round(m.line * 0.55)), "RIVEN RATING", m.label, ORANGE, m.spacing)
            if best:
                bw = _spaced_width(d, "BETTER", m.label, m.spacing) + 2 * m.pad
                bx, by, bh = right - bw, y + round(m.line * 0.3), round(m.line * 1.2)
                cc = round(bh * 0.35)
                d.polygon([(bx + cc, by), (bx + bw - cc, by), (bx + bw, by + bh / 2), (bx + bw - cc, by + bh),
                           (bx + cc, by + bh), (bx, by + bh / 2)], fill=ORANGE + (240,))
                _spaced_text(d, (bx + m.pad, by + round(bh * 0.12)), "BETTER", m.label, NAVY, m.spacing)
        elif kind == "title":
            _spaced_text(d, (left, y), row[1], m.title, ORANGE, m.spacing * 2)
        elif kind == "label":
            d.text((left, y), row[1], font=m.small, fill=TEXT)
        elif kind == "stat":
            _, mark, name, value, tag = row
            mw = d.textlength(mark + "  ", font=m.body)
            d.text((left, y), mark, font=m.body, fill=MARK.get(tag, GREY))
            d.text((left + mw, y), name, font=m.body, fill=TAG.get(tag, TEXT))
            if value:
                vcol = RED if tag in ("bad", "dealbreaker") else (TEXT if tag not in ("unwanted", "neutral") else GREY)
                d.text((right - d.textlength(value, font=m.body), y), value, font=m.body, fill=vcol)
        elif kind == "note":
            d.text((left, y), row[1], font=m.small, fill=RED if row[2] == "bad" else ORANGE)
        elif kind == "meta":
            d.text((left, y), row[1], font=m.small, fill=GREY)
        elif kind == "rule":
            ry = y + h // 2
            d.line([(left, ry), (right, ry)], fill=ORANGE + (70,), width=1)
        y += h
    return img


def render_status(text, scale=1.0, base=11):
    """The small hint line in the corner."""
    f = font("body", max(8, round(base * 1.2 * scale)))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w, h = int(probe.textlength(text, font=f)) + 16, int(f.size * 1.6)
    img = Image.new("RGBA", (w, h), NAVY + (170,))
    ImageDraw.Draw(img).text((8, int(f.size * 0.2)), text, font=f, fill=GREY)
    return img

