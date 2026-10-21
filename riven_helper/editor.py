"""Roll-file editor: make and edit your roll JSON files without writing JSON.

    Riven Helper.bat            (the editor with the overlay; only the editor: python -m riven_helper --edit [file])

Tabs:
  Rolls   - the weapons (and @groups, *class fallbacks) in the file, their rolls, and each roll's
            wanted stats, unwanted stats and dealbreakers.
  Groups  - named groups of weapons; rolls written for "@group" apply to every weapon in it.
  File rules - unwanted stats and dealbreakers for every roll in this file.
  Settings - the editor's colours (a Warframe UI theme), the overlay's optional features, and the
            roll files and folders it loads (saved to config.json; a running overlay applies them).
Save checks the file the same way the overlay will and lists anything it can't use.
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import ROOT, load_config, save_settings
from .editor_model import (CLASSES, OPERATORS, SIGNS, TIERS, RollFile, describe_rule, is_bad_as_positive, new_roll,
                           rule_parts, rule_text, same_rule, set_tier, stat_choices, tier_of, weapon_choices)
from .gamedata import GameData
from .rolls import roll_paths
from .theme import DEFAULT_NAME, luminance, mix, named_themes, palette

ROLLS_DIR = ROOT / "rolls"


class Colours:
    """The editor's colours, from a Warframe UI theme (set_theme; Vitruvian, the game's default, to start)."""

    def __init__(self):
        self.set_theme(DEFAULT_NAME)

    def set_theme(self, name):
        themes = named_themes()
        theme = themes.get(name) or themes[DEFAULT_NAME]     # an unknown name: the default theme
        p = palette(theme)
        bg = theme.background
        toward = (255, 255, 255) if luminance(bg) < 0.5 else (0, 0, 0)
        hexed = lambda c: "#%02x%02x%02x" % tuple(c)
        self.bg, self.panel, self.field = hexed(bg), hexed(mix(bg, toward, 0.04)), hexed(mix(bg, toward, 0.09))
        self.border, self.active = hexed(mix(bg, toward, 0.22)), hexed(mix(bg, toward, 0.16))
        self.text, self.dim, self.orange, self.lavender = hexed(p.text), hexed(p.grey), hexed(p.label), hexed(p.stat)


C = Colours()


class AutoCombo(ttk.Combobox):
    """A combobox that narrows its list to what you've typed."""

    def __init__(self, master, choices, **kw):
        super().__init__(master, values=choices, **kw)
        self.choices = list(choices)
        self.bind("<KeyRelease>", self._filter)

    def set_choices(self, choices):
        self.choices = list(choices)
        self.configure(values=self.choices)

    def _filter(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        typed = self.get().lower()
        self.configure(values=[c for c in self.choices if typed in c.lower()] or self.choices)


class RuleList(ttk.Frame):
    """A list of "bad" / "dealbreaker" rules with a builder: sign, stat, comparison, value.

    On a roll it also shows the rules the roll inherits (from the file's rules and config.json), greyed.
    Remove on one switches it off for this roll only (Remove again switches it back on); selecting
    one, changing it and pressing Add replaces it for this roll. Those exceptions go into the roll's
    "ignore_bad" / "ignore_dealbreakers".
    """

    def __init__(self, master, title, hint, stats, on_change, dealbreakers=False):
        super().__init__(master, style="Panel.TFrame")
        self.rules, self.on_change, self.dealbreakers = [], on_change, dealbreakers
        self.inherited, self.ignored = [], None       # [(rule, where it's from)], and the roll's ignore list
        self.rows = []                                # what each line of the list is: ("own", rule) / ("inherited", rule)
        self.editing = None                           # the inherited rule last selected (Add then replaces it)
        ttk.Label(self, text=title, style="Head.TLabel").grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Label(self, text=hint, style="Dim.TLabel", wraplength=520, justify="left").grid(
            row=1, column=0, columnspan=6, sticky="w")
        self.box = tk.Listbox(self, height=4, **listbox_style())
        self.box.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(2, 4))
        self.box.bind("<<ListboxSelect>>", lambda e: self._pick())
        self.sign = ttk.Combobox(self, values=list(SIGNS), width=17, state="readonly")
        self.sign.current(0)
        self.stat = AutoCombo(self, stats, width=20)
        self.op = ttk.Combobox(self, values=OPERATORS, width=10, state="readonly")
        self.op.current(0)
        self.value = ttk.Entry(self, width=6)
        for i, w in enumerate((self.sign, self.stat, self.op, self.value)):
            w.grid(row=3, column=i, sticky="w", padx=(0, 4))
        ttk.Button(self, text="Add", command=self._add).grid(row=3, column=4, padx=(0, 4))
        ttk.Button(self, text="Remove", command=self._remove).grid(row=3, column=5)
        self.columnconfigure(5, weight=1)

    def load(self, rules, inherited=(), ignored=None):
        """rules: the roll's (or file's) own list, edited in place. inherited: [(rule, where from)] it also
        gets; ignored: its list of inherited rules switched off (edited in place)."""
        self.rules, self.inherited, self.ignored = rules, list(inherited), ignored
        self.editing = None
        self.box.delete(0, "end")
        self.rows = []
        for r in rules:
            self.box.insert("end", f"{r}      ({describe_rule(r, self.dealbreakers)})")
            self.rows.append(("own", r))
        for r, source in self.inherited:
            off = self._is_off(r)
            self.box.insert("end", f"{r}      ({'off for this roll; ' if off else ''}from {source})")
            self.box.itemconfigure("end", foreground=C.dim)
            self.rows.append(("inherited", r))

    def _is_off(self, rule):
        return self.ignored is not None and any(same_rule(rule, i) for i in self.ignored)

    def _pick(self):
        """Fill the builder with the selected rule, to change it."""
        picked = self.box.curselection()
        if not picked:
            return
        kind, rule = self.rows[picked[0]]
        sign, stat, op, value = rule_parts(rule)
        self.sign.set(next(name for name, s in SIGNS.items() if s == sign))
        self.stat.set(stat)
        self.op.set(op or OPERATORS[0])
        self.value.delete(0, "end")
        self.value.insert(0, value or "")
        self.editing = (kind, rule)

    def _add(self):
        stat = self.stat.get().strip()
        if not stat:
            return
        op = self.op.get()
        value = self.value.get().strip()
        if op != OPERATORS[0] and not _is_number(value):
            messagebox.showwarning("Rule", "Enter a number for the comparison (e.g. 100 for 100%).")
            return
        new = rule_text(SIGNS[self.sign.get()], stat, op, value or None)
        kind, old = self.editing or (None, None)
        changed = old is not None and rule_parts(old)[1].lower() == stat.lower()   # the selected rule, edited
        if changed and same_rule(old, new):
            return                                    # nothing changed
        if changed and kind == "own":
            self.rules.remove(old)                    # replaced
        elif changed and self.ignored is not None and not self._is_off(old):
            self.ignored.append(old)                  # an inherited rule, replaced for this roll only
        self.rules.append(new)
        self.load(self.rules, self.inherited, self.ignored)
        self.on_change()

    def _remove(self):
        for i in reversed(self.box.curselection()):
            kind, rule = self.rows[i]
            if kind == "own":
                self.rules.remove(rule)
            elif self._is_off(rule):                  # switched off: switch it back on
                self.ignored[:] = [r for r in self.ignored if not same_rule(r, rule)]
            elif self.ignored is not None:            # inherited: off for this roll only
                self.ignored.append(rule)
        self.load(self.rules, self.inherited, self.ignored)
        self.on_change()


# What the "Unwanted stats" menu does, for players. (A "+Stat" rule is also a harmless negative.)
UNWANTED_HINT = ("Stats you don't want on the riven. Each one it has halves the rating.\n"
                 "  as a positive (+):  unwanted as a positive, but a good negative (raises the rating)\n"
                 "  as the negative (-):  unwanted as the negative, e.g. a stat your build relies on\n"
                 "  either way:  unwanted anywhere on the riven")


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def listbox_style():
    return dict(bg=C.field, fg=C.text, selectbackground=C.orange, selectforeground=C.bg, highlightthickness=0,
                borderwidth=0, activestyle="none", exportselection=False, font=("Segoe UI", 10))


class Editor:
    def __init__(self, path=None, config_path=None):
        self.gamedata = GameData()
        self.stats = stat_choices(self.gamedata)
        self.weapons = weapon_choices(self.gamedata)
        self.doc = RollFile()
        self.entry = None                     # selected weapon key
        self.roll = None                      # selected roll dict
        self.group = None                     # selected group name

        self.settings = load_config(config_path)
        C.set_theme(self.settings["editor_theme"])
        self.files = {}                       # File list entry -> path

        self.root = tk.Tk()
        self.root.title("Riven Roll Editor")
        self.root.geometry("1280x860")
        self.root.minsize(1100, 600)
        self.root.configure(bg=C.bg)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._toolbar()
        tabs = ttk.Notebook(self.root)
        tabs.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.tabs = tabs
        self._rolls_tab(tabs)
        self._groups_tab(tabs)
        self._file_tab(tabs)
        self._settings_tab(tabs)
        self.status = ttk.Label(self.root, text="", style="Dim.TLabel")
        self.status.pack(fill="x", padx=12, pady=(0, 8))
        self.open(path) if path else self.new()
        # Rules edited on File rules show up on the roll (as inherited) when you go back to it.
        tabs.bind("<<NotebookTabChanged>>", lambda e: self._show_roll())
        if self.settings.get("_problem"):
            self._say(self.settings["_problem"])

    # -- look ----------------------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=C.bg, foreground=C.text, fieldbackground=C.field, font=("Segoe UI", 10),
                    bordercolor=C.border, lightcolor=C.panel, darkcolor=C.panel)
        s.configure("Panel.TFrame", background=C.panel)
        s.configure("TFrame", background=C.bg)
        s.configure("TLabel", background=C.panel, foreground=C.text)
        s.configure("Bar.TLabel", background=C.bg, foreground=C.text)
        s.configure("Head.TLabel", background=C.panel, foreground=C.orange, font=("Segoe UI Semibold", 11))
        s.configure("Title.TLabel", background=C.bg, foreground=C.orange, font=("Segoe UI Semibold", 14))
        s.configure("Dim.TLabel", background=C.panel, foreground=C.dim, font=("Segoe UI", 9))
        s.configure("TButton", background=C.field, foreground=C.orange, borderwidth=1, focusthickness=0, padding=(10, 3))
        s.map("TButton", background=[("active", C.active)])
        s.configure("TCheckbutton", background=C.panel, foreground=C.text)
        s.configure("TNotebook", background=C.bg, borderwidth=0)
        s.configure("TNotebook.Tab", background=C.panel, foreground=C.dim, padding=(14, 5))
        s.map("TNotebook.Tab", background=[("selected", C.field)], foreground=[("selected", C.orange)])
        s.configure("Treeview", background=C.field, fieldbackground=C.field, foreground=C.lavender, rowheight=22,
                    borderwidth=0)
        s.configure("Treeview.Heading", background=C.panel, foreground=C.orange)
        s.map("Treeview", background=[("selected", C.orange)], foreground=[("selected", C.bg)])
        s.configure("TCombobox", fieldbackground=C.field, foreground=C.text, arrowcolor=C.orange, background=C.field)
        s.map("TCombobox", fieldbackground=[("readonly", C.field)], foreground=[("readonly", C.text)],
              selectbackground=[("readonly", C.field)], selectforeground=[("readonly", C.text)])
        s.configure("Vertical.TScrollbar", background=C.field, troughcolor=C.panel, arrowcolor=C.orange)
        s.configure("TEntry", fieldbackground=C.field, foreground=C.text)
        s.configure("TSpinbox", fieldbackground=C.field, foreground=C.text, arrowcolor=C.orange)
        self.root.option_add("*TCombobox*Listbox.background", C.field)
        self.root.option_add("*TCombobox*Listbox.foreground", C.text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", C.orange)

    def _toolbar(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Label(bar, text="RIVEN ROLL EDITOR", style="Title.TLabel").pack(side="left", padx=(2, 16))
        ttk.Label(bar, text="File:", style="Bar.TLabel").pack(side="left")
        self.file_pick = ttk.Combobox(bar, width=34, state="readonly")
        self.file_pick.pack(side="left", padx=4)
        self.file_pick.bind("<<ComboboxSelected>>", lambda e: self.open(self.files[self.file_pick.get()]))
        for text, cmd in (("New", self.new), ("Open…", self.open_dialog), ("Save", self.save),
                          ("Save as…", self.save_as), ("Check", self.check)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
        self.overlay_status = ttk.Label(bar, text="", style="Bar.TLabel")
        self.overlay_status.pack(side="left", padx=(16, 0))
        self._refresh_files()

    def _refresh_files(self):
        """The File list: every roll file the overlay loads (rolls/, and files or folders added in Settings)."""
        self.files = {}
        for path in roll_paths(self.settings["roll_files"], self.settings["_dir"]):
            inside = path.resolve().parent == ROLLS_DIR.resolve()
            self.files[path.name if inside else f"{path.name}  ({path.parent})"] = path
        self.file_pick.configure(values=sorted(self.files, key=str.lower))

    # -- Rolls tab ---------------------------------------------------------------------------
    def _rolls_tab(self, tabs):
        tab = ttk.Frame(tabs, style="Panel.TFrame", padding=10)
        tabs.add(tab, text="Rolls")
        tab.columnconfigure(2, weight=1)
        tab.rowconfigure(1, weight=1)

        # Weapons, @groups and *fallbacks in the file.
        ttk.Label(tab, text="Weapons & groups", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        left = ttk.Frame(tab, style="Panel.TFrame")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        srow = ttk.Frame(left, style="Panel.TFrame")
        srow.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        ttk.Label(srow, text="Search").pack(side="left", padx=(0, 6))
        self.filter = ttk.Entry(srow, width=22)
        self.filter.pack(side="left", fill="x", expand=True)
        self.filter.bind("<KeyRelease>", lambda e: self._fill_entries())
        self.entry_box = tk.Listbox(left, width=30, **listbox_style())
        self.entry_box.grid(row=1, column=0, columnspan=3, sticky="nsew")
        self.entry_box.bind("<<ListboxSelect>>", lambda e: self._pick_entry())
        self.new_entry = AutoCombo(left, [], width=26)
        self.new_entry.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 3))
        ttk.Button(left, text="Add", command=self._add_entry).grid(row=3, column=0, sticky="ew")
        ttk.Button(left, text="Rename", command=self._rename_entry).grid(row=3, column=1, sticky="ew", padx=3)
        ttk.Button(left, text="Remove", command=self._remove_entry).grid(row=3, column=2, sticky="ew")
        ttk.Label(left, text="A weapon name, @group (see Groups) or *rifle /\n*shotgun / *pistol / *melee / "
                             "*archgun fallback", style="Dim.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")

        # Rolls of the selected entry.
        ttk.Label(tab, text="Rolls", style="Head.TLabel").grid(row=0, column=1, sticky="w")
        mid = ttk.Frame(tab, style="Panel.TFrame")
        mid.grid(row=1, column=1, sticky="nsew", padx=(0, 10))
        mid.rowconfigure(0, weight=1)
        self.roll_box = tk.Listbox(mid, width=20, **listbox_style())
        self.roll_box.grid(row=0, column=0, columnspan=3, sticky="nsew")
        self.roll_box.bind("<<ListboxSelect>>", lambda e: self._pick_roll())
        ttk.Button(mid, text="Add", command=self._add_roll).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(mid, text="Copy", command=self._copy_roll).grid(row=1, column=1, sticky="ew", padx=3, pady=(6, 0))
        ttk.Button(mid, text="Remove", command=self._remove_roll).grid(row=1, column=2, sticky="ew", pady=(6, 0))
        ttk.Label(mid, text="Each riven is scored against\nevery roll; the best one wins.",
                  style="Dim.TLabel").grid(row=2, column=0, columnspan=3, sticky="w")

        # The selected roll.
        ttk.Label(tab, text="Roll", style="Head.TLabel").grid(row=0, column=2, sticky="w")
        right = self._scrollable(tab, row=1, column=2)
        right.columnconfigure(0, weight=1)
        self.roll_frame = right
        row = ttk.Frame(right, style="Panel.TFrame")
        row.grid(row=0, column=0, sticky="ew")
        ttk.Label(row, text="Label (optional):").pack(side="left")
        self.label = ttk.Entry(row, width=36)
        self.label.pack(side="left", padx=6)
        self.label.bind("<KeyRelease>", lambda e: self._set_label())

        ttk.Label(right, text="Wanted stats", style="Head.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(right, text="Required: the riven must have it.   Wanted: a stat you want.   "
                              "Acceptable: nice to have.", style="Dim.TLabel").grid(row=2, column=0, sticky="w")
        self.pos = ttk.Treeview(right, columns=("tier",), height=6, selectmode="browse")
        self.pos.heading("#0", text="Stat")
        self.pos.heading("tier", text="Tier")
        self.pos.column("#0", width=260)
        self.pos.column("tier", width=110, anchor="center")
        self.pos.grid(row=3, column=0, sticky="ew", pady=(2, 4))
        self.pos.bind("<<TreeviewSelect>>", lambda e: self._pick_positive())
        prow = ttk.Frame(right, style="Panel.TFrame")
        prow.grid(row=4, column=0, sticky="w")
        self.pos_stat = AutoCombo(prow, self.stats, width=24)
        self.pos_stat.pack(side="left")
        self.pos_tier = ttk.Combobox(prow, values=list(TIERS), state="readonly", width=11)
        self.pos_tier.set("Wanted")
        self.pos_tier.pack(side="left", padx=6)
        ttk.Button(prow, text="Add / update", command=self._set_positive).pack(side="left", padx=3)
        ttk.Button(prow, text="Remove", command=self._remove_positive).pack(side="left")

        self.roll_bad = RuleList(right, "Unwanted stats", UNWANTED_HINT, self.stats, self.doc_changed)
        self.roll_bad.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.roll_deal = RuleList(right, "Dealbreakers", "Any match scores the riven 0 for this roll, "
                                  "e.g. -Damage > 100 (more than 100% negative Damage).", self.stats, self.doc_changed,
                                  dealbreakers=True)
        self.roll_deal.grid(row=9, column=0, sticky="ew", pady=(10, 0))

    def _scrollable(self, parent, row, column):
        """A frame inside a scrollable area (the roll panel is taller than small screens)."""
        holder = ttk.Frame(parent, style="Panel.TFrame")
        holder.grid(row=row, column=column, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        canvas = tk.Canvas(holder, bg=C.panel, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, style="Panel.TFrame")
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        wheel = lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    # -- Groups tab ---------------------------------------------------------------------------
    def _groups_tab(self, tabs):
        tab = ttk.Frame(tabs, style="Panel.TFrame", padding=10)
        tabs.add(tab, text="Groups")
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text="Groups", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        left = ttk.Frame(tab, style="Panel.TFrame")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        left.rowconfigure(0, weight=1)
        self.group_box = tk.Listbox(left, width=30, **listbox_style())
        self.group_box.grid(row=0, column=0, columnspan=3, sticky="nsew")
        self.group_box.bind("<<ListboxSelect>>", lambda e: self._pick_group())
        ttk.Label(left, text="Group name (new, or new name for Rename):", style="Dim.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.group_name = ttk.Entry(left, width=28)
        self.group_name.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(26, 3))
        ttk.Button(left, text="Add", command=self._add_group).grid(row=2, column=0, sticky="ew")
        ttk.Button(left, text="Rename", command=self._rename_group).grid(row=2, column=1, sticky="ew", padx=3)
        ttk.Button(left, text="Remove", command=self._remove_group).grid(row=2, column=2, sticky="ew")

        ttk.Label(tab, text="Weapons in the group", style="Head.TLabel").grid(row=0, column=1, sticky="w")
        right = ttk.Frame(tab, style="Panel.TFrame")
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="A weapon covers its whole riven family (Rubico also covers Rubico Prime). "
                              "Groups defined here can be used from any roll file.",
                  style="Dim.TLabel", wraplength=600, justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        self.member_box = tk.Listbox(right, **listbox_style())
        self.member_box.grid(row=1, column=0, sticky="nsew", pady=4)
        mctl = ttk.Frame(right, style="Panel.TFrame")
        mctl.grid(row=1, column=1, sticky="n", padx=8, pady=4)
        self.member_pick = AutoCombo(mctl, self.weapons, width=26)
        self.member_pick.pack()
        ttk.Button(mctl, text="Add weapon", command=self._add_member).pack(fill="x", pady=3)
        ttk.Button(mctl, text="Remove weapon", command=self._remove_member).pack(fill="x")
        ttk.Button(mctl, text="Edit this group's rolls", command=self._group_rolls).pack(fill="x", pady=(18, 0))

    # -- File rules tab ---------------------------------------------------------------------------
    def _file_tab(self, tabs):
        tab = ttk.Frame(tabs, style="Panel.TFrame", padding=10)
        tabs.add(tab, text="File rules")
        tab.columnconfigure(0, weight=1)
        self.file_bad = RuleList(tab, "Unwanted stats for every roll in this file",
                                 UNWANTED_HINT + "\nEvery roll gets these as well as its own.", self.stats,
                                 self.doc_changed)
        self.file_bad.grid(row=0, column=0, sticky="ew")
        self.file_deal = RuleList(tab, "Dealbreakers for every roll in this file",
                                  "Any match scores the riven 0. Every roll gets these as well as its own.", self.stats,
                                  self.doc_changed, dealbreakers=True)
        self.file_deal.grid(row=1, column=0, sticky="ew", pady=(16, 0))

    # -- Settings tab ---------------------------------------------------------------------------
    OPTIONS = [
        ("next_step", "Next-step advice",
         "NEXT on each card panel, and BETTER for the card that reaches the Kuva target for less Kuva. Off: no "
         "NEXT, and BETTER simply goes to the card with the higher rating."),
        ("upgrade_overlay", "Upgrade screen overlay", "IDEAL RIVEN on a weapon's upgrade screen."),
        ("config_rolls", "Config-specific rolls",
         "On the upgrade screen, show the roll labelled like the selected config tab (\"Main\", \"CONFIG B\"). "
         "Off: always the weapon's first roll."),
    ]

    def _settings_tab(self, tabs):
        tab = ttk.Frame(tabs, style="Panel.TFrame", padding=10)
        tabs.add(tab, text="Settings")
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text="Editor look", style="Head.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(tab, text="Theme").grid(row=1, column=0, sticky="w", pady=4)
        self.theme_pick = ttk.Combobox(tab, values=sorted(named_themes()), state="readonly", width=24)
        self.theme_pick.set(self.settings["editor_theme"] if self.settings["editor_theme"] in named_themes()
                            else DEFAULT_NAME)
        self.theme_pick.grid(row=1, column=1, sticky="w", pady=4)
        self.theme_pick.bind("<<ComboboxSelected>>", lambda e: self._apply_theme(self.theme_pick.get()))

        ttk.Label(tab, text="Overlay", style="Head.TLabel").grid(row=2, column=0, columnspan=2, sticky="w",
                                                                pady=(18, 0))
        self.options = {}
        for row, (key, text, hint) in enumerate(self.OPTIONS, start=3):
            self.options[key] = tk.BooleanVar(value=bool(self.settings[key]))
            ttk.Checkbutton(tab, text=text, variable=self.options[key]).grid(row=row, column=0, sticky="nw",
                                                                            pady=3, padx=(0, 16))
            ttk.Label(tab, text=hint, style="Dim.TLabel", wraplength=760, justify="left").grid(
                row=row, column=1, sticky="w", pady=3)

        kuva_row = ttk.Frame(tab, style="Panel.TFrame")
        kuva_row.grid(row=6, column=0, sticky="nw", pady=3, padx=(0, 16))
        ttk.Label(kuva_row, text="Kuva target").pack(side="left")
        self.kuva_target = ttk.Spinbox(kuva_row, from_=0, to=100, increment=5, width=5)
        self.kuva_target.set(f"{float(self.settings.get('kuva_target') or 0):g}")
        self.kuva_target.pack(side="left", padx=6)
        ttk.Label(kuva_row, text="%").pack(side="left")
        ttk.Label(tab, text="Each card shows the Kuva you can expect to spend cycling until the riven rates this "
                            "high, and NEXT follows the reroll strategy until it does. 0 hides the Kuva line "
                            "(and NEXT goes by simpler rules).",
                  style="Dim.TLabel", wraplength=760, justify="left").grid(row=6, column=1, sticky="w", pady=3)
        splice_row = ttk.Frame(tab, style="Panel.TFrame")
        splice_row.grid(row=7, column=0, sticky="nw", pady=3, padx=(0, 16))
        ttk.Label(splice_row, text="Splice threshold").pack(side="left")
        self.splice_min = ttk.Spinbox(splice_row, from_=0, to=100, increment=5, width=5)
        self.splice_min.set(f"{float(self.settings.get('splice_min') or 0):g}")
        self.splice_min.pack(side="left", padx=6)
        ttk.Label(splice_row, text="%").pack(side="left")
        ttk.Label(tab, text="When the roll wants a spliced stat (Blast, from Heat + Cold), how well one of its two "
                            "traits must have rolled before NEXT locks it and waits for the other: 0% is the "
                            "lowest roll there is, 100% the highest (0 counts any).",
                  style="Dim.TLabel", wraplength=760, justify="left").grid(row=7, column=1, sticky="w", pady=3)

        ttk.Label(tab, text="Roll lists", style="Head.TLabel").grid(row=8, column=0, columnspan=2, sticky="w",
                                                                   pady=(18, 0))
        ttk.Label(tab, text="Every roll file in these files and folders is used. Added files stay where they are, "
                            "so you can keep editing them there (they also appear in the File list above).",
                  style="Dim.TLabel", wraplength=900, justify="left").grid(row=9, column=0, columnspan=2, sticky="w")
        self.source_box = tk.Listbox(tab, height=6, **listbox_style())
        self.source_box.grid(row=10, column=0, columnspan=2, sticky="ew", pady=4)
        buttons = ttk.Frame(tab, style="Panel.TFrame")
        buttons.grid(row=11, column=0, columnspan=2, sticky="w")
        ttk.Button(buttons, text="Add files…", command=self._add_roll_files).pack(side="left")
        ttk.Button(buttons, text="Add folder…", command=self._add_roll_folder).pack(side="left", padx=4)
        ttk.Button(buttons, text="Remove", command=self._remove_roll_source).pack(side="left")
        self.sources = list(self.settings["roll_files"])
        self._fill_sources()

        ttk.Button(tab, text="Save settings", command=self._save_settings).grid(row=12, column=0, sticky="w",
                                                                              pady=(20, 0))
        ttk.Label(tab, text="Saved to config.json; a running overlay applies them within a second.",
                  style="Dim.TLabel").grid(row=12, column=1, sticky="w", pady=(20, 0))

    def _apply_theme(self, name):
        """Recolour the editor (a preview until Save settings)."""
        C.set_theme(name)
        self._style()
        self.root.configure(bg=C.bg)
        todo = [self.root]
        while todo:
            widget = todo.pop()
            todo += widget.winfo_children()
            if isinstance(widget, tk.Listbox):
                widget.configure(**listbox_style())
            elif isinstance(widget, tk.Canvas):
                widget.configure(bg=C.panel)

    def _fill_sources(self):
        self.source_box.delete(0, "end")
        for src in self.sources:
            path = Path(src) if Path(src).is_absolute() else Path(self.settings["_dir"]) / src
            kind = "folder" if path.is_dir() else "file" if path.exists() else "not found"
            self.source_box.insert("end", f"{src}    ({kind})")

    def _add_source(self, path):
        path = Path(path)
        try:                                        # inside the config's folder: keep it relative
            src = path.resolve().relative_to(Path(self.settings["_dir"]).resolve()).as_posix()
        except ValueError:
            src = path.resolve().as_posix()
        if src not in self.sources:
            self.sources.append(src)

    def _add_roll_files(self):
        for path in filedialog.askopenfilenames(title="Add roll files", filetypes=[("Roll files", "*.json")]):
            self._add_source(path)
        self._fill_sources()

    def _add_roll_folder(self):
        path = filedialog.askdirectory(title="Add a folder of roll files")
        if path:
            self._add_source(path)
            self._fill_sources()

    def _remove_roll_source(self):
        picked = self.source_box.curselection()
        if picked:
            del self.sources[picked[0]]
            self._fill_sources()

    def _save_settings(self):
        try:
            target = float(self.kuva_target.get().strip().rstrip("%"))
        except ValueError:
            target = -1
        if not 0 <= target <= 100:
            messagebox.showwarning("Kuva target", "The Kuva target is a rating from 0 to 100 (0 hides the Kuva line).")
            return
        try:
            splice_min = float(self.splice_min.get().strip().rstrip("%"))
        except ValueError:
            splice_min = -1
        if not 0 <= splice_min <= 100:
            messagebox.showwarning("Splice threshold", "The splice threshold is from 0% (the lowest roll) to "
                                                       "100% (the highest).")
            return
        changes = {key: var.get() for key, var in self.options.items()}
        changes["kuva_target"] = int(target) if target == int(target) else target
        changes["splice_min"] = int(splice_min) if splice_min == int(splice_min) else splice_min
        changes.update(editor_theme=self.theme_pick.get(), roll_files=list(self.sources))
        save_settings(changes, self.settings.get("_path"))
        self.settings = load_config(self.settings.get("_path"))
        self._refresh_files()
        self._say("Settings saved to config.json")

    # -- file actions ---------------------------------------------------------------------------
    def _ask_save(self):
        if not self.doc.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", "Save your changes first?")
        if answer is None:
            return False
        return self.save() if answer else True

    def new(self):
        if not self._ask_save():
            return
        self.doc = RollFile()
        self._show_doc()
        self._say("New file: add a weapon or group on the left, then its wanted stats.")

    def open(self, path):
        if not self._ask_save():
            return
        try:
            self.doc = RollFile(path)
        except Exception as e:
            messagebox.showerror("Open", f"Couldn't open {path}:\n{e}")
            return
        self._show_doc()
        self._say(f"Opened {self.doc.path}")

    def open_dialog(self):
        path = filedialog.askopenfilename(initialdir=ROLLS_DIR, filetypes=[("Roll files", "*.json")])
        if path:
            self.open(path)

    def save(self):
        if not self.doc.path:
            return self.save_as()
        self.doc.save()
        self._refresh_files()
        problems = self.doc.check(self.gamedata, self._other_files())
        self._say(f"Saved {self.doc.path.name}" + (f" - {len(problems)} problem(s), see Check" if problems else
                                                     " - no problems found"))
        self._show_title()
        return True

    def save_as(self):
        path = filedialog.asksaveasfilename(initialdir=ROLLS_DIR, defaultextension=".json",
                                            filetypes=[("Roll files", "*.json")])
        if not path:
            return False
        self.doc.path = Path(path)
        return self.save()

    def check(self):
        problems = self.doc.check(self.gamedata, self._other_files())
        if problems:
            messagebox.showwarning("Check", "The overlay can't use these parts:\n\n" + "\n".join(problems))
        else:
            messagebox.showinfo("Check", "No problems found.")

    def _other_files(self):
        return [p for p in self.files.values() if not self.doc.path or p.resolve() != self.doc.path.resolve()]

    def close(self):
        if self._ask_save():
            self.root.destroy()

    # -- showing the document --------------------------------------------------------------------
    def _inherited(self, kind):
        """[(rule, where from)] of the unwanted stats or dealbreakers ("bad" / "dealbreakers") every roll gets."""
        return ([(r, "all rolls in this file") for r in getattr(self.doc, kind)]
                + [(r, "every roll file (config.json)") for r in self.settings.get(kind, [])])

    def doc_changed(self):
        self.doc.touch()
        self._show_title()

    def _show_title(self):
        name = self.doc.path.name if self.doc.path else "new file"
        self.root.title(f"Riven Roll Editor - {name}{' *' if self.doc.dirty else ''}")
        if self.doc.path and self.doc.path.parent.resolve() == ROLLS_DIR.resolve():
            self.file_pick.set(self.doc.path.name)

    def _say(self, text):
        self.status.configure(text=text)

    def _show_doc(self):
        self.entry = self.roll = self.group = None
        self._fill_entries()
        self._fill_groups()
        self.file_bad.load(self.doc.bad)
        self.file_deal.load(self.doc.dealbreakers)
        self._show_roll()
        self._show_title()

    def _entry_choices(self):
        return (["@" + g for g in self.doc.groups] + ["*" + c for c in CLASSES] + self.weapons)

    def _fill_entries(self, select=None):
        typed = self.filter.get().lower()
        keys = [k for k in self.doc.entries if typed in k.lower()]
        self._entry_keys = sorted(keys, key=lambda k: (k[:1] not in "@*", k.lower()))
        self.entry_box.delete(0, "end")
        for k in self._entry_keys:
            n = len(self.doc.entries[k])
            self.entry_box.insert("end", f"{k}   ({n} roll{'s' if n != 1 else ''})")
        self.new_entry.set_choices(self._entry_choices())
        if select in self._entry_keys:
            i = self._entry_keys.index(select)
            self.entry_box.selection_set(i)
            self.entry_box.see(i)
        self._fill_rolls()

    def _pick_entry(self):
        sel = self.entry_box.curselection()
        self.entry = self._entry_keys[sel[0]] if sel else None
        self.roll = None
        self._fill_rolls()

    def _fill_rolls(self, select=0):
        self.roll_box.delete(0, "end")
        rolls = self.doc.entries.get(self.entry, []) if self.entry else []
        for i, r in enumerate(rolls):
            self.roll_box.insert("end", r.get("label") or f"roll {i + 1}")
        if rolls:
            select = min(select, len(rolls) - 1)
            self.roll_box.selection_set(select)
            self.roll = rolls[select]
        else:
            self.roll = None
        self._show_roll()

    def _pick_roll(self):
        sel = self.roll_box.curselection()
        rolls = self.doc.entries.get(self.entry, [])
        self.roll = rolls[sel[0]] if sel and sel[0] < len(rolls) else None
        self._show_roll()

    def _show_roll(self):
        r = self.roll
        state = "normal" if r else "disabled"
        self.label.configure(state="normal")
        self.label.delete(0, "end")
        if r:
            self.label.insert(0, r.get("label", ""))
        self.label.configure(state=state)
        self.pos.delete(*self.pos.get_children())
        if r:
            # Most important first: by weight, required before others of the same weight, then by name.
            order = sorted(r["positives"], key=lambda s: (-float(r["positives"][s]), s not in r["required"], s))
            for stat in order:
                self.pos.insert("", "end", iid=stat, text=stat, values=(tier_of(r, stat),))
        if r:
            # An inherited "+Stat" doesn't apply to a roll that wants that stat (see rolls.py).
            wanted = {s.lower() for s in r["positives"]}
            self.roll_bad.load(r["bad"], [(rule, where) for rule, where in self._inherited("bad")
                                          if not (is_bad_as_positive(rule) and rule_parts(rule)[1].lower() in wanted)],
                               r["ignore_bad"])
            self.roll_deal.load(r["dealbreakers"], self._inherited("dealbreakers"), r["ignore_dealbreakers"])
        else:
            self.roll_bad.load([])
            self.roll_deal.load([])

    # -- entry / roll actions ----------------------------------------------------------------------
    def _add_entry(self):
        key = self.new_entry.get().strip()
        if key and key[:1] not in "@*":
            match = next((w for w in self.weapons if w.lower() == key.lower()), None)
            if match is None and not messagebox.askyesno(
                    "Unknown weapon", f'"{key}" isn\'t a weapon name the overlay knows. Add it anyway?'):
                return
            key = match or key
        try:
            key = self.doc.add_entry(key)
        except ValueError as e:
            messagebox.showwarning("Add", str(e))
            return
        self.filter.delete(0, "end")
        self.entry = key
        self._fill_entries(select=key)
        self.doc_changed()
        self._say(f"Added {key}: now add the stats you want on the right.")

    def _rename_entry(self):
        if not self.entry:
            return
        new = self.new_entry.get().strip()
        if not new:
            messagebox.showinfo("Rename", "Type the new name in the box below the list first.")
            return
        self.entry = self.doc.rename_entry(self.entry, new)
        self._fill_entries(select=self.entry)
        self.doc_changed()

    def _remove_entry(self):
        if self.entry and messagebox.askyesno("Remove", f'Remove "{self.entry}" and its rolls?'):
            self.doc.remove_entry(self.entry)
            self.entry = None
            self._fill_entries()
            self.doc_changed()

    def _add_roll(self):
        if not self.entry:
            return
        self.doc.entries[self.entry].append(new_roll())
        self._fill_rolls(select=len(self.doc.entries[self.entry]) - 1)
        self._fill_entries(select=self.entry)
        self.doc_changed()

    def _copy_roll(self):
        if not (self.entry and self.roll):
            return
        import copy
        r = copy.deepcopy(self.roll)
        r["label"] = (r.get("label") or "roll") + " (copy)"
        self.doc.entries[self.entry].append(r)
        self._fill_rolls(select=len(self.doc.entries[self.entry]) - 1)
        self.doc_changed()

    def _remove_roll(self):
        rolls = self.doc.entries.get(self.entry, [])
        if self.roll in rolls:
            rolls.remove(self.roll)
            if not rolls:
                rolls.append(new_roll())
            self._fill_rolls()
            self.doc_changed()

    def _set_label(self):
        if self.roll is not None:
            self.roll["label"] = self.label.get()
            sel = self.roll_box.curselection()
            if sel:
                self.roll_box.delete(sel[0])
                self.roll_box.insert(sel[0], self.roll["label"] or f"roll {sel[0] + 1}")
                self.roll_box.selection_set(sel[0])
            self.doc_changed()

    def _canonical_stat(self, text):
        stat = self.gamedata.match_stat(text, cutoff=0.85) if text else None
        if stat is None and text:
            messagebox.showwarning("Stat", f'"{text}" isn\'t a stat name the overlay knows.')
        return stat

    def _pick_positive(self):
        sel = self.pos.selection()
        if sel and self.roll:
            stat = sel[0]
            self.pos_stat.set(stat)
            self.pos_tier.set(tier_of(self.roll, stat))

    def _set_positive(self):
        if self.roll is None:
            return
        stat = self._canonical_stat(self.pos_stat.get().strip())
        if not stat:
            return
        set_tier(self.roll, stat, self.pos_tier.get())
        self._show_roll()
        self.doc_changed()

    def _remove_positive(self):
        sel = self.pos.selection()
        if sel and self.roll:
            self.roll["positives"].pop(sel[0], None)
            if sel[0] in self.roll["required"]:
                self.roll["required"].remove(sel[0])
            self._show_roll()
            self.doc_changed()

    # -- group actions ----------------------------------------------------------------------------
    def _fill_groups(self, select=None):
        self._group_names = sorted(self.doc.groups, key=str.lower)
        self.group_box.delete(0, "end")
        for g in self._group_names:
            self.group_box.insert("end", f"{g}   ({len(self.doc.groups[g])} weapons)")
        if select in self._group_names:
            self.group_box.selection_set(self._group_names.index(select))
        self._fill_members()

    def _pick_group(self):
        sel = self.group_box.curselection()
        self.group = self._group_names[sel[0]] if sel else None
        self._fill_members()

    def _fill_members(self):
        self.member_box.delete(0, "end")
        for m in self.doc.groups.get(self.group, []) if self.group else []:
            self.member_box.insert("end", m)

    def _add_group(self):
        try:
            self.group = self.doc.add_group(self.group_name.get())
        except ValueError as e:
            messagebox.showwarning("Group", str(e))
            return
        self.group_name.delete(0, "end")
        self._fill_groups(select=self.group)
        self.new_entry.set_choices(self._entry_choices())
        self.doc_changed()
        self._say(f'Added group "{self.group}": add its weapons, then "Edit this group\'s rolls".')

    def _rename_group(self):
        if self.group and self.group_name.get().strip():
            self.group = self.doc.rename_group(self.group, self.group_name.get())
            self.group_name.delete(0, "end")
            self._fill_groups(select=self.group)
            self._fill_entries()
            self.doc_changed()

    def _remove_group(self):
        if self.group and messagebox.askyesno("Remove", f'Remove group "{self.group}"? Its rolls (@{self.group}) '
                                                        "stay in the file until you remove them."):
            self.doc.remove_group(self.group)
            self.group = None
            self._fill_groups()
            self.doc_changed()

    def _add_member(self):
        name = self.member_pick.get().strip()
        if not (self.group and name):
            return
        match = next((w for w in self.weapons if w.lower() == name.lower()), None)
        if match is None:
            messagebox.showwarning("Weapon", f'"{name}" isn\'t a weapon name the overlay knows.')
            return
        if match not in self.doc.groups[self.group]:
            self.doc.groups[self.group].append(match)
        self.member_pick.set("")
        self._fill_groups(select=self.group)
        self.doc_changed()

    def _remove_member(self):
        if not self.group:
            return
        for i in reversed(self.member_box.curselection()):
            del self.doc.groups[self.group][i]
        self._fill_groups(select=self.group)
        self.doc_changed()

    def _group_rolls(self):
        if not self.group:
            return
        key = "@" + self.group
        if key not in self.doc.entries:
            self.doc.add_entry(key)
            self.doc_changed()
        self.filter.delete(0, "end")
        self.entry = key
        self._fill_entries(select=key)
        self.tabs.select(0)

    def show_overlay_status(self, text):
        """The overlay's latest message (it runs alongside the editor), shown in the toolbar."""
        self.overlay_status.configure(text=f"Overlay: {text}"[:110])

    def run(self):
        self.root.mainloop()


def main(path=None):
    try:
        Editor(path).run()
    except Exception:
        # Started without a console (pythonw), so show what went wrong instead of just closing.
        import traceback
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Riven Roll Editor", "The editor couldn't start:\n\n" + traceback.format_exc())
        root.destroy()
        raise


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else None)
