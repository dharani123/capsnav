# Mappings window: view and move capsnav bindings

Date: 2026-10-06

## Goal

From the mouse-mode icon in the top bar, open a window that lists every
current capsnav binding and lets you move an action to a different key. The
change takes effect immediately.

## Entry point

`capsnav-indicator.py` adds a **Mappings…** item to its menu, under the
existing "Mouse mode on" line. The menu opens on either click, because the
Ubuntu AppIndicator extension makes no difference between them. The item
launches `capsnav-mappings` as a separate process. If a mappings window is
already open, it is raised instead of opening a second one (a single
instance through `Gtk.Application`).

## Sources (live files, read every time the window opens)

| File | Sections used |
|---|---|
| `/etc/keyd/capsnav-nav` | whole file (Caps layer and mouse mode share it) |
| `/etc/keyd/default.conf` | `[nav]`, `[mousemode]`, `[arrows]`, `[winswitch:A]`, `[nav+alt]`, `[mousemode+alt]` |
| `~/.config/keyd/app.conf` | `[code]` (VS Code): `nav.X` / `mousemode.X` pairs shown as one row |

Never shown or edited directly: `[mousetype]` / `capsnav-mousetype`,
`[mousemode+control]`, `[mousemode+mousetype+alt]`, `[main]`, `[global]`,
`[ids]`, and the empty layers watched by the helper.

## Parsing

- A binding is a `key = action` line. Its **group** is the comment block
  directly above it. A run of bindings with no blank line or new comment
  between them shares that group. The comment text is the group heading.
- `include` lines are skipped. The included file is read as its own source.
- Lines of the form `# unbound: KEY = ACTION` are bindings that were
  overwritten. They are collected into an **Unbound** section.
- Actions are made readable:
  - modifier prefixes: `C-` Ctrl, `S-` Shift, `A-` Alt, `M-` Super
  - key names: `pageup` → Page Up, `f12` → F12, `sysrq` → PrtSc, `minus` → -,
    single letters upper-cased
  - known layers (fixed table): `ijklup/left/down/right` and `esdf…` →
    "Pointer up/left/down/right (or snap)", `scrollup/down` → "Scroll
    up/down", `pointermode` → "Cycle pointer mode", `arrows` → "Hold: arrow
    keys / fast scroll", `mousetype` → "Hold: normal keyboard"
  - `leftmouse` / `rightmouse` → Left / Right click
  - `swapm(winswitch, A-tab)` / `layerm(winswitch, A-tab)` → "Window
    switcher"; `togglem(mousemode, X)` → "Leave mouse mode, then X";
    `overload(shift, …)` → "Tap: toggle mouse mode, hold: Shift"
  - anything not recognised is shown raw, so nothing is hidden

## Window

A GTK 3 window titled "capsnav mappings", scrollable, closed with Esc.
Sections in this order:

1. Caps layer / mouse mode (`capsnav-nav`)
2. Caps layer only (`[nav]`) and mouse mode only (`[mousemode]`)
3. Caps+Space (`[arrows]`)
4. Caps+Alt (`[nav+alt]`, `[mousemode+alt]`)
5. Window switcher (`[winswitch:A]`)
6. VS Code (`app.conf [code]`)
7. Unbound (only if there are any)

Each row has the group heading above it, followed by **Key** (a drop-down)
and **Does** (readable action). The drop-down lists a–z, 0–9 and
`; , . / ' [ ] - =` (keyd names: semicolon, comma, …), plus the row's
current key if it isn't one of those (e.g. `space`). Keys already bound
in the same section are labelled with what they do, e.g. `q — Previous tab`.
Unbound rows start with an empty selection. An **Apply** button is
enabled while there are unsaved changes, and a status line shows the result
or the error. The key can't be captured by pressing it, because in mouse
mode keyd has already remapped what the window receives.

## Moving a key (edit rules)

All edits are text edits on copies of the files, one section at a time.

1. **Move:** in the row's section, `old = ACTION` becomes `new = ACTION`.
   The comment and line position stay the same.
2. **Overwrite:** if the section already has `new = OTHER`, that line becomes
   `# unbound: new = OTHER` (same position), and OTHER appears in Unbound.
3. **Rebinding from Unbound:** `# unbound: old = ACTION` becomes
   `new = ACTION`, with rule 2 applied to whatever holds `new`.
4. **Linked lists** (only for `capsnav-nav` rows, the keys mouse mode takes
   over):
   - `capsnav-mousetype`: remove `old = old` if no capsnav-nav binding is
     left on `old`; add `new = new` if it is missing.
   - `[mousemode+control]` in default.conf: the same, with `old = C-old` /
     `new = C-new`.
   - The same applies to the `[mousemode]`-only rows `b` and `0`. Its
     `capslock` and `leftshift` rows aren't in the linked lists (they're
     modifier/layer keys, not typed keys), so moving them changes only their
     own line. `[nav]` rows (Caps+b) don't touch the lists.
5. **VS Code rows:** `nav.old` and `mousemode.old` both become `.new`.
6. Several moves can be queued before Apply. They are applied in order.

## Saving (live files only; the repo is not touched)

1. Copy the three `/etc/keyd` files into a temporary directory, apply the
   edits, and run `keyd check` on the staged `default.conf` (with includes
   resolving to the staged copies). If the check fails, stop, show the error,
   and change nothing.
2. Install the changed staged files into `/etc/keyd` in a single privileged
   command: `sudo -A install -m644 …` when `SUDO_ASKPASS` is set, otherwise
   `pkexec install …`. Then run `keyd reload` (no root needed for a user in
   the keyd group; check during implementation).
3. If app.conf changed, write it with an atomic rename, then run
   `systemctl --user restart capsnav-appmap`.
4. Re-read everything and redraw, so the window always shows what is live.
5. If the user cancels the password prompt, nothing is installed and the
   status line says so.

The README notes that `install.sh` copies the repo files over these, which
undoes changes made in the window.

## Code layout

- `capsnav-mappings.py`, with two parts:
  - **Model** (no GTK): `parse(text, source)` → sections, groups and
    bindings; `move(files, row, new_key)` → new file texts; readable action
    formatting.
  - **UI**: the GTK window, and saving through the steps above.
  - `capsnav-mappings --print`: prints the parsed view as text and exits
    (used for checking, no GTK needed).
- `capsnav-indicator.py`: the menu item; spawns `capsnav-mappings` with
  `subprocess.Popen` (it doesn't wait for it).
- `install.sh`: `sudo install -m755 capsnav-mappings.py /usr/local/bin/capsnav-mappings`.
- `README.md`: a file-list entry and a short "Mappings window" section.

## Testing

- `tests/test_mappings.py` (stdlib unittest), run on copies of the repo
  configs:
  - every `key = action` in the shown sections appears exactly once in the
    parsed view
  - move to a free key: only that line changes, and the linked lists update
  - overwrite: the target becomes `# unbound:` and shows up in Unbound;
    rebinding from Unbound works
  - VS Code pair moves together
  - the staged result passes `keyd check`
- Manual: open the window from the icon, move a key, confirm the new key
  works in the Caps layer and mouse mode, then move it back.

## Out of scope

- Changing what a key does (its action).
- Writing to the repo or committing.
- Updating the pointer-mode names in the helper when e/s/d/f or i/j/k/l move.
