"""What each panel says, as rows for style.render_panel (see style.py for the row types).

  card_rows     the panel above a riven card: rating, stats, how the negative counts, the next step,
                and (a lone card) the chance that the next cycle rates higher
  ideal_rows    IDEAL ROLL on the riven screens: the best stats for this weapon, with maximum values
  upgrade_rows  the compact IDEAL RIVEN on a weapon's upgrade screen
"""

import textwrap

from .advice import next_step, progress, spliced_stats
from .odds import chance_of_better
from .riven_math import format_value, max_value

MARK = {"good": "+", "ok": "~", "unwanted": "x", "harmless": "+", "neutral": "=", "bad": "x", "dealbreaker": "!"}
NEGATIVE_LABEL = {"harmless": "harmless", "neutral": "neutral", "bad": "bad", "dealbreaker": "DEALBREAKER"}
MELEE_NAMES = {"Damage": "Melee Damage", "Fire Rate": "Attack Speed"}   # what melee rivens call these stats


def display_name(stat, weapon):
    return MELEE_NAMES.get(stat, stat) if weapon.cls == "melee" else stat


def grade(score):
    """Colour of a rating."""
    return "great" if score >= 85 else "good" if score >= 65 else "ok" if score >= 40 else "bad"


def roll_label(analyzer, roll):
    """A roll's label, plus its file name when several roll files are loaded."""
    if len(analyzer.library.files) > 1:
        return f"{roll.label}  ({roll.source})" if roll.label else roll.source
    return roll.label


def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def card_rows(analyzer, result, best=False, alone=False):
    """The panel for one card. best: this card is the better of the two on the cycle screen. alone: it's
    the only card (the riven screen, before cycling): show the chance that the next cycle rates higher."""
    r, ev = result.rating, result.ev
    if ev is None:
        return [("score", "?", "bad", False), ("label", r.detail)]
    label = roll_label(analyzer, r.roll) if r.roll else r.detail
    rows = [("score", f"{r.score:.0f}%", grade(r.score), best)] + ([("label", label)] if label else [])
    if alone:
        chance = chance_of_better(result, analyzer)
        if chance is not None:
            shown = "under 1" if 0 < chance < 0.005 else f"{chance * 100:.0f}"
            rows.append(("note", f"next cycle rates higher: {shown}%", "warn"))
    advise = analyzer.cfg.get("next_step", True)
    if best and advise:
        why = progress(result, analyzer)[1]
        if why:                                   # better than its rating says: it's closer to the ideal roll
            rows += [("note", line, "warn") for line in textwrap.wrap(f"closer to the ideal: {why}", 44)]
    rows.append(("rule",))

    spliced = spliced_stats()
    for st in ev.positives:
        tag = r.tags.get(st.name, "unwanted")
        flag = {"bad": "  BAD", "dealbreaker": "  DEALBREAKER"}.get(tag, "")
        held = "spliced  " if st.name in spliced else "locked  " if st.locked else ""
        rows.append(("stat", MARK[tag], display_name(st.name, ev.weapon), f"{held}{st.quality * 100:.0f}%{flag}", tag))
    neg = ev.negative
    if neg is None:
        rows.append(("stat", " ", "no negative", "", "neutral"))
    else:
        tag = r.tags.get(neg.name, "neutral")
        rows.append(("stat", MARK[tag], "-" + display_name(neg.name, ev.weapon), NEGATIVE_LABEL[tag], tag))

    if r.dealbreaker:
        rows.append(("note", f"dealbreaker: {r.dealbreaker}", "bad"))
    rows += [("note", why, "warn") for why in r.bad]
    if r.missing:
        rows.append(("note", "missing " + ", ".join(r.missing), "warn"))
    rows += [("note", n, "warn") for n in ev.notes + result.card.problems]
    step = next_step(result, analyzer.gamedata) if advise else None
    if step:
        action, why = step
        rows += [("rule",)] + [("note", line, "next") for line in textwrap.wrap(f"NEXT: {action}", 34)]
        rows += [("meta", line) for line in textwrap.wrap(why, 48)]
    return rows


def _best_stats(analyzer, roll, weapon, rank, count):
    """(stat, its maximum value as shown on a card) for the roll's highest-weighted stats."""
    has_negative = bool(roll.negatives)
    out = []
    for stat in sorted(roll.positives, key=lambda s: -roll.positives[s])[:count]:
        sd = analyzer.gamedata.stats[stat]
        v = max_value(sd, weapon, rank, 3, has_negative)
        if v is not None:
            out.append((stat, format_value(sd, v)))
    return out


def ideal_rows(analyzer, results):
    """IDEAL ROLL for the riven on screen: the roll the most reliably read card matched (or the
    weapon's first roll), with maximum values for its weapon and rank in the usual best layout of
    3 positives + 1 negative. None when no card was worked out."""
    evaluated = [r for r in results if r.ev]
    if not evaluated:
        return None
    ref = max(evaluated, key=lambda r: (analyzer.confidence(r), r.rating.score))
    weapon, rank = ref.ev.weapon, ref.ev.rank
    rolls = analyzer.library.rolls_for(weapon)
    roll = ref.rating.roll or (rolls[0] if rolls else None)
    if roll is None:
        return [("title", "IDEAL ROLL"), ("meta", f"no rolls listed for {weapon.family}")]

    label = roll_label(analyzer, roll)
    # The weapon and its disposition are on screen already; only an unranked riven's rank is worth saying.
    rows = [("title", "IDEAL ROLL")] + ([("label", label)] if label else []) \
        + ([("meta", f"values at rank {rank}")] if rank < 8 else []) + [("rule",)]
    for i, (stat, value) in enumerate(_best_stats(analyzer, roll, weapon, rank, 6)):
        name = display_name(stat, weapon) + (" (required)" if stat in roll.required else "")
        rows.append(("stat", "+" if i < 3 else "~", name, f"up to {value}", "good" if i < 3 else "ok"))
    if roll.negatives:
        rows.append(("rule",))
        names = [display_name(n, weapon) for n in roll.negatives[:6]]
        for i, chunk in enumerate(_chunks(names, 2)):
            rows.append(("stat", "-" if i == 0 else " ", ", ".join(chunk), "", "harmless"))
    else:
        rows.append(("stat", " ", "no negative", "", "neutral"))
    rows.append(("meta", f"max values for 3 positives{' + 1 negative' if roll.negatives else ''}"))
    if len(rolls) > 1:
        rows.append(("meta", f"{len(rolls) - 1} other roll(s) listed for {weapon.family}"))
    return rows


def upgrade_rows(analyzer, weapon_name, per_line=3, config=None):
    """The compact IDEAL RIVEN for a weapon's upgrade screen: the top 3 stats at their maximum on a
    maxed riven for exactly this weapon, and its harmless negatives (per_line to a row).

    The roll shown is the one labelled like the selected config tab (config), if there is one;
    otherwise the weapon's first roll."""
    weapon = analyzer.gamedata.weapon_by_base_name(weapon_name)
    if weapon is None:
        return None
    named = analyzer.library.roll_named(weapon, config) if config else None
    rolls = [named] if named else analyzer.library.rolls_for(weapon)
    if not rolls:
        return [("title", "IDEAL RIVEN"), ("meta", f"no rolls listed for {weapon.family}")]
    roll, rank = rolls[0], 8
    rows = [("title", "IDEAL RIVEN")] + ([("label", f"{roll.label}  (config)")] if named else [])
    rows += [("stat", "+", display_name(stat, weapon), value, "good")
             for stat, value in _best_stats(analyzer, roll, weapon, rank, 3)]
    names = [display_name(n, weapon) for n in roll.negatives[:3]]
    for i, chunk in enumerate(_chunks(names, per_line)):
        rows.append(("stat", "-" if i == 0 else " ", ", ".join(chunk), "", "harmless"))
    return rows


def rows_text(rows):
    """A panel as plain text (for the command line and tests)."""
    out = []
    for row in rows or []:
        if row[0] == "stat":
            out.append(f"{row[1]} {row[2]}   {row[3]}".rstrip())
        elif row[0] != "rule":
            out.append(str(row[1]))
    return "\n".join(out)
