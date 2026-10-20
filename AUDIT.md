# Security and safety audit

A manual audit of Riven Reroll Helper, done by the project author on **2026-10-20** following the
checklist below, after an AI-assisted review of the same code. **Result: every check came out as
expected.** The program only reads the screen, makes no network connections, writes only its own files,
and its low-level Windows code is sound.

To repeat the audit, work through the steps in order (about two to three hours) and note anything that
doesn't hold. Places are named by file and function, so they stay findable as the code changes.

## What was checked

1. It never touches the game: no memory access, no injected code, no input sent to it.
2. It makes no network connections and runs no other programs.
3. Files it reads, including roll files from other people, can't make it run code.
4. It writes only `config.json`, roll files and `debug/` snapshots, and never leaves them half-written.
5. Its low-level Windows code can't corrupt memory.
6. Installing it only fetches what it says it fetches.

## Checklist

### 1. Nothing risky is used anywhere — passed

```bash
git grep -nE "urllib|requests|http\.client|socket|subprocess|os\.system|os\.popen|eval\(|exec\(|pickle|marshal|__import__|webbrowser" -- riven_helper
```

Nothing in `riven_helper/`. Network code exists only in the two developer tools (`tools/`), which don't
ship to players.

### 2. Interaction with the game — passed

- Finding the game (`capture.py`, `find_game`): `FindWindowW`, `GetForegroundWindow`, `GetClientRect`,
  `ClientToScreen` only. No process is opened.
- Screenshots (`capture.py`, `Screen.grab`): `mss` copies screen pixels.
- OCR (`capture.py`, `Ocr`): Windows' built-in OCR on the screenshot.
- Hotkeys (`app.py`, `_pressed`): `GetAsyncKeyState` checks whether the three configured keys are held;
  nothing is recorded or sent.
- Panels (`winpanel.py`, `Panel.__init__`): click-through (`WS_EX_TRANSPARENT`), never take focus
  (`WS_EX_NOACTIVATE`), hidden from capture (`WDA_EXCLUDEFROMCAPTURE`).

```bash
git grep -nE "SendInput|keybd_event|mouse_event|PostMessage|SendMessage|OpenProcess|ReadProcessMemory|WriteProcessMemory|CreateRemoteThread" -- riven_helper
```

Nothing found.

### 3. Files it reads — passed

- Roll files (`rolls.py`, `roll_paths` and `RollLibrary.reload`) and the editor (`editor_model.py`,
  `RollFile.load`) only parse JSON with `json.loads`, and check every field before use.
- Rules (`rolls.py`, `parse_rules`, `RULE_RE`) are matched as text, never evaluated.
- Settings (`config.py`, `load_config`): a damaged `config.json` falls back to the defaults.

A malicious roll file can at worst give bad ratings, or (with an enormous rule string) slow the program
down. It can't run code.

### 4. Files it writes — passed

```bash
git grep -nE "write_text|write_bytes|\.save\(|os\.replace|shutil\.(copy|move)|unlink|rmtree|mkdir" -- riven_helper
```

Only `config.json` (`config.py`, `save_settings` / `write_atomic`), roll files with a `.bak` of the
previous version (`editor_model.py`, `RollFile.save`), F10 snapshots in `debug/` (`app.py`, `snapshot`),
`--image --out`, and a temporary file for the editor's Check. Nothing deletes files. Saves go to a
temporary file that is then swapped in, so they're never left half-written.

### 5. Low-level Windows code — passed

`winpanel.py` is the only place handling raw memory. Every Windows function has exact `argtypes` /
`restype`. `set_image` copies exactly `width × height × 4` bytes into a bitmap made with that size, stops
if the bitmap couldn't be created, and releases every handle it gets.

### 6. Threads — passed

The worker thread (`app.py`, `worker`) and the window thread (`tick`) only hand data over through the
`events` queue. Shared objects are replaced whole, never changed while the other thread reads them:
`RollLibrary.reload` builds new dictionaries and swaps them in, and lookups read one `_state` snapshot.

### 7. Install and supply chain — passed

- `setup.bat` installs only `requirements.txt` from PyPI, and Python 3.12 through winget only after the
  user answers Y. No administrator rights needed.
- `requirements.txt` and `requirements-build.txt` pin exact versions.
- `tools/make_release.py` ships only the PyInstaller output, a default `config.json`, the market rolls,
  the README and the AI disclaimer.
- The developer tools download over HTTPS only, from warframe.market and the WFCD data CDN.

### 8. Behaviour while running — passed

1. Network (Resource Monitor / TCPView): no connections.
2. Files (Process Monitor, *WriteFile*): writes only in the program's folder.
3. Game access (Process Monitor / Process Explorer): no handle to the game's process.
4. CPU (Task Manager, during a mission): about 0–3% of one core.
5. Tests: `.venv\Scripts\python -m unittest discover tests` passes.

## Findings

### Fixed during the review

| Finding | Fix |
|---|---|
| Reloading roll files while a panel was drawn could leave a weapon with no rolls until the next reload | Reload into new dictionaries, swapped in at once; lookups use one snapshot |
| "Roll source not found" was added to the warnings once a second, growing without limit | Reported once per load |
| Saving settings briefly emptied the shared settings | Updated in place |
| Saves could be left half-written; a damaged `config.json` stopped the program | Atomic saves, `.bak` of roll files, defaults when `config.json` can't be read (kept as `config.json.damaged`) |
| A half-saved roll file was skipped until the next edit | Read again shortly after |
| A refused panel bitmap would crash the whole program | Checked; the old picture stays |
| OCR ran once a second during missions (about 20% of one core) | Skipped unless a menu header is on screen (about 3%) |
| Dependency versions weren't pinned | Exact versions; Python 3.12+ for source installs |

### Found during the manual audit (fixed)

- A stat in a `"+Stat"` bad rule (bad as a positive) counted only as a *neutral* negative. It's now a
  harmless negative for the roll: having it as the negative spends the riven's curse on something you
  don't want. That applies wherever the rule is written (a roll, a file, or `config.json`), unless the
  roll wants that stat as a positive. Later the two were merged the other way round too: a harmless
  negative is bad as a positive, and the editor shows them as one list of bad stats.

### Open

- **The exe isn't signed,** so Windows warns on first start and users have to click through. Plan: sign
  it (SignPath Foundation or a Certum open-source certificate).
- **No published checksum.** Until the exe is signed, publish the zip's SHA-256 with each release
  (`Get-FileHash dist\Riven-Helper-*.zip -Algorithm SHA256`).
- **F10 snapshots can be personal.** They're full screenshots of the game window (the whole monitor if
  `window_title` is `null`) and can show your in-game name, chat or other windows. They stay on your
  computer, but check them before sharing.
- **Slow rule strings.** A deliberately enormous rule string in a roll file could make the rule pattern
  very slow, freezing only the program itself. Low risk: it only matters for roll files from someone
  untrustworthy.
