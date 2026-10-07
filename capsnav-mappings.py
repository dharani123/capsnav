#!/usr/bin/env python3
"""capsnav mappings window: lists every capsnav binding and lets you move an
action to another key.

Opened from the mouse-mode icon in the top bar (Mappings…), or run directly.
`capsnav-mappings --print` prints the list as text instead.

Reads the live configs each time: /etc/keyd/capsnav-nav, /etc/keyd/default.conf
and ~/.config/keyd/app.conf. Saving writes only those live files (plus the
linked /etc/keyd/capsnav-mousetype and [mousemode+control] lists) and reloads
keyd; the repo is not touched, so install.sh puts its defaults back.

A key moved onto one that's already bound overwrites it: the old line becomes
`# unbound: KEY = ACTION` and shows up under Unbound, where it can be given a
key again.
"""

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

KEYD_DIR = "/etc/keyd"
APP_CONF = os.path.expanduser("~/.config/keyd/app.conf")
KEYD_FILES = ("default.conf", "capsnav-nav", "capsnav-mousetype")

# --- Model (no GTK) ---------------------------------------------------------

# Sections shown, in order: (file, section) -> title. capsnav-nav has no
# section header (section None).
SHOWN = [
    (("capsnav-nav", None), "Caps layer / mouse mode"),
    (("default.conf", "nav"), "Caps layer only"),
    (("default.conf", "mousemode"), "Mouse mode only"),
    (("default.conf", "arrows"), "Caps+Space"),
    (("default.conf", "winswitch:A"), "Window switcher (while open)"),
]
APP_TITLES = {"code": "VS Code"}
APP_LAYERS = ("nav", "mousemode")

# Keys in [mousemode] that are layer/modifier keys, not typed keys, so they
# stay out of capsnav-mousetype and [mousemode+control].
NOT_TYPED = {"capslock", "leftshift", "rightshift", "leftcontrol",
             "rightcontrol", "leftalt", "rightalt", "leftmeta", "rightmeta"}

# Key drop-down choices (keyd names).
CHOICES = (list("abcdefghijklmnopqrstuvwxyz") + list("1234567890")
           + ["semicolon", "comma", "dot", "slash", "apostrophe",
              "leftbrace", "rightbrace", "minus", "equal"])

KEY_LABELS = {
    "semicolon": ";", "comma": ",", "dot": ".", "slash": "/",
    "apostrophe": "'", "leftbrace": "[", "rightbrace": "]", "minus": "-",
    "equal": "=", "grave": "`", "backslash": "\\", "space": "Space",
    "capslock": "Caps", "leftshift": "Left Shift", "rightshift": "Right Shift",
    "tab": "Tab", "esc": "Esc", "enter": "Enter",
}
KEY_NAMES = dict(KEY_LABELS, **{
    "pageup": "Page Up", "pagedown": "Page Down", "home": "Home",
    "end": "End", "up": "Up", "down": "Down", "left": "Left",
    "right": "Right", "sysrq": "PrtSc", "leftmouse": "Left click",
    "rightmouse": "Right click", "middlemouse": "Middle click",
    "delete": "Delete", "backspace": "Backspace", "insert": "Insert",
})
MODS = {"C": "Ctrl", "S": "Shift", "A": "Alt", "M": "Super", "G": "AltGr"}

LAYER_NAMES = {
    "scrollup": "Scroll up (hold)",
    "scrolldown": "Scroll down (hold)",
    "arrows": "Hold: arrow keys / fast scroll",
    "mousetype": "Hold: normal keyboard",
    "shift": "Shift",
    "pointermode": "Cycle pointer mode (move / snap to edges)",
}
for _c in ("ijkl", "esdf"):
    for _d in ("up", "left", "down", "right"):
        LAYER_NAMES[_c + _d] = "Pointer %s" % _d

SECTION_RE = re.compile(r"^\s*\[(.+?)\]\s*$")
BIND_RE = re.compile(r"^\s*([^#\s=\[][^=]*?)\s*=\s*(.*?)\s*$")
UNBOUND_RE = re.compile(r"^\s*#\s*unbound:\s*(\S+?)\s*=\s*(.*?)\s*$")


@dataclass
class Binding:
    file: str
    section: object        # section name, None for capsnav-nav
    key: str               # keyd key name (layer prefix stripped in app.conf)
    action: str
    group: str             # comment heading above it
    unbound: bool = False
    lines: list = field(default_factory=list)   # line indices in the file


@dataclass
class Section:
    title: str
    file: str
    section: object
    intro: str = ""
    groups: list = field(default_factory=list)  # [(heading, [Binding])]


def key_label(key):
    return KEY_LABELS.get(key, key)


def _key_name(name):
    if name in KEY_NAMES:
        return KEY_NAMES[name]
    if re.fullmatch(r"f\d+", name):
        return name.upper()
    if len(name) == 1:
        return name.upper()
    return name


def _split_call(action):
    m = re.fullmatch(r"(\w+)\((.*)\)", action)
    if not m:
        return None, None
    args, depth, cur = [], 0, ""
    for ch in m.group(2):
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    args.append(cur.strip())
    return m.group(1), args


def describe(action):
    """A readable form of a keyd action; unknown ones come back unchanged."""
    fn, args = _split_call(action)
    if fn:
        if fn == "layer" and len(args) == 1 and args[0] in LAYER_NAMES:
            return LAYER_NAMES[args[0]]
        if fn in ("swapm", "layerm") and args[0] == "winswitch":
            return "Window switcher"
        if fn == "toggle" and args == ["mousemode"]:
            return "Toggle mouse mode"
        if fn == "togglem" and len(args) == 2 and args[0] == "mousemode":
            return "Leave mouse mode, then " + describe(args[1])
        if fn == "overload" and len(args) == 2:
            hold = LAYER_NAMES.get(args[0], args[0])
            return "Hold: %s, tap: %s" % (hold, describe(args[1]).lower()
                                          if args[1].startswith("toggle")
                                          else describe(args[1]))
        return action
    mods, rest = [], action
    while len(rest) > 2 and rest[1] == "-" and rest[0] in MODS:
        mods.append(MODS[rest[0]])
        rest = rest[2:]
    name = _key_name(rest)
    if name == rest and not mods and not re.fullmatch(r"\w", rest):
        return action
    return "+".join(mods + [name])


def _parse_file(text, file):
    """{section: [intro, [(heading, [Binding])]]} for one file. A group is
    the run of bindings under one comment block; the comment directly above a
    section header is that section's intro."""
    out = {}
    section = None
    pending = []           # comment lines waiting for a binding / header
    group = None           # current (heading, [bindings]) list, or None

    def sec(name):
        return out.setdefault(name, ["", []])

    for i, line in enumerate(text.split("\n")):
        s = line.strip()
        m = SECTION_RE.match(line)
        if m:
            section = m.group(1)
            sec(section)[0] = " ".join(pending)
            pending, group = [], None
            continue
        if not s or s.startswith("include "):
            pending, group = [], None
            continue
        um = UNBOUND_RE.match(line)
        if s.startswith("#") and not um:
            group = None                   # a comment ends the run
            pending.append(s.lstrip("#").strip())
            continue
        m = um or BIND_RE.match(line)
        if not m:
            continue
        key, action = m.groups()
        if pending or group is None:
            group = (" ".join(pending), [])
            sec(section)[1].append(group)
            pending = []
        group[1].append(Binding(file, section, key, action, group[0],
                                unbound=bool(um), lines=[i]))
    return out


def _app_rows(groups):
    """Merge app.conf nav.X / mousemode.X lines into one Binding per key."""
    rows = {}
    order = []
    for heading, binds in groups:
        for b in binds:
            layer, _, key = b.key.partition(".")
            if layer not in APP_LAYERS or not key:
                continue
            ident = (key, b.unbound)
            if ident not in rows:
                rows[ident] = Binding(b.file, b.section, key, b.action,
                                      heading, b.unbound, [])
                order.append(ident)
            r = rows[ident]
            r.lines += b.lines
            if layer == "nav":
                r.action = b.action
    return [rows[i] for i in order]


def parse_all(texts):
    """texts: {"capsnav-nav", "default.conf", "app.conf": text}. Returns the
    shown Sections in order, with an Unbound section last if needed."""
    parsed = {f: _parse_file(texts[f], f)
              for f in ("capsnav-nav", "default.conf") if f in texts}
    sections, unbound = [], []

    def add(title, file, section, intro, groups):
        sec = Section(title, file, section, intro)
        for heading, binds in groups:
            bound = [b for b in binds if not b.unbound]
            unbound.extend((title, b) for b in binds if b.unbound)
            if bound:
                sec.groups.append((heading, bound))
        if sec.groups:
            sections.append(sec)

    for (file, section), title in SHOWN:
        if file in parsed and section in parsed[file]:
            intro, groups = parsed[file][section]
            add(title, file, section, intro, groups)

    if "app.conf" in texts:
        for section, (intro, groups) in _parse_file(texts["app.conf"],
                                                    "app.conf").items():
            if section is None:
                continue
            rows = _app_rows(groups)
            title = APP_TITLES.get(section, section) + " (per-app)"
            add(title, "app.conf", section, intro, [("", rows)])

    if unbound:
        sec = Section("Unbound", None, None,
                      "Actions whose key was taken by another. Pick a key to "
                      "bind them again.")
        for title, b in unbound:
            b.group = "From " + title
            if sec.groups and sec.groups[-1][0] == b.group:
                sec.groups[-1][1].append(b)
            else:
                sec.groups.append((b.group, [b]))
        sections.append(sec)
    return sections


TABS = ["Mouse", "Scroll", "Browser", "VS Code", "Windows", "Text", "Other"]
POINTER_ACTIONS = {"leftmouse", "rightmouse", "middlemouse",
                   "M-A-u",    # centre the pointer (capsnav-switch-monitor)
                   "M-A-o"}    # pointer + focus to the other monitor
BROWSER_ACTIONS = {"C-pageup", "C-pagedown", "C-t", "C-w"}
WINDOW_ACTIONS = {"M-l", "togglem(mousemode, M-l)", "sysrq"}
TEXT_ACTIONS = {"backspace"}


def category(b):
    """Which tab a binding belongs in, decided by what it does (so a moved
    key keeps its tab); None for one not shown in the tabs."""
    fn, args = _split_call(b.action)
    if b.action == "layer(arrows)":
        return None      # Space: shown through its "Space + " rows instead
    layer = args[0] if fn == "layer" else None
    if b.file == "app.conf":
        return "VS Code"
    if b.section == "winswitch:A" or b.action in WINDOW_ACTIONS \
            or (fn in ("swapm", "layerm") and args[0] == "winswitch"):
        return "Windows"
    if b.action in POINTER_ACTIONS or (layer and layer[4:] in
                                        ("up", "down", "left", "right")
                                        and layer[:4] in ("ijkl", "esdf")
                                        or layer == "pointermode"):
        return "Mouse"
    if layer in ("scrollup", "scrolldown"):
        return "Scroll"
    if b.section == "arrows" or layer == "arrows" \
            or b.action in TEXT_ACTIONS:     # Caps+Space, Caps+o
        return "Text"
    if b.action in BROWSER_ACTIONS:
        return "Browser"
    return "Other"


# The "How to use" tab.
HOW_TO_USE = """\
In my opinion the Caps Lock key is wasted, since we hardly use it. capsnav \
uses it as a super key that turns the keyboard into a mouse and helps you \
navigate things faster.

Use all these mappings by holding Caps Lock.

Or tap left Shift to toggle mouse mode, and use the same bindings without \
holding Caps Lock. The top-bar icon is a mouse while mouse mode \
is on and a keyboard while it's off; tap left Shift again to leave it."""

# Sections shown inside another in the tabs: Caps+Space keys sit under the
# layer that holds Space, each with a "Space + " prefix (see prefix()).
FOLD_INTO = {("default.conf", "arrows"): "Caps layer / mouse mode"}


def prefix(b, sections):
    """Text shown before a binding's key button: "Space + " for the
    Caps+Space keys (whatever key holds the arrows layer)."""
    if (b.file, b.section) not in FOLD_INTO:
        return ""
    for sec in sections:
        for _h, bs in sec.groups:
            for x in bs:
                if x.file == "capsnav-nav" and x.action == "layer(arrows)":
                    return key_label(x.key).capitalize() + " + "
    return ""


def tabs(sections):
    """[(tab, [Section])] in TABS order (empty tabs left out), each Section
    holding only that tab's bindings; Unbound last as its own tab."""
    out = []
    for tab in TABS:
        secs = []
        for sec in sections:
            if sec.title == "Unbound":
                continue
            groups = [(h, [b for b in bs if category(b) == tab])
                      for h, bs in sec.groups]
            groups = [(h, bs) for h, bs in groups if bs]
            if not groups:
                continue
            into = FOLD_INTO.get((sec.file, sec.section))
            if into:
                # Its intro becomes the heading of its first group.
                if sec.intro and not groups[0][0]:
                    groups[0] = (sec.intro, groups[0][1])
                host = next((s for s in secs if s.title == into), None)
                if host:
                    host.groups += groups
                else:
                    secs.append(Section(into, sec.file, sec.section, "",
                                        groups))
                continue
            secs.append(Section(sec.title, sec.file, sec.section,
                                sec.intro, groups))
        if secs:
            out.append((tab, secs))
    out += [("Unbound", [sec]) for sec in sections if sec.title == "Unbound"]
    return out


# Space speeds up scrolling in capsnav-scroll (SCROLL_SPEED_LAYERS there).
SCROLL_BOOST = 6


def combos(sections):
    """Read-only rows for key combinations the helper handles rather than
    keyd: {tab: [(prefix, keys, does)]}, using the keys currently bound."""
    keys = {}      # action -> labels of every key bound to it, in file order
    for sec in sections:
        if (sec.file, sec.section) != ("capsnav-nav", None):
            continue
        for _h, bs in sec.groups:
            for b in bs:
                keys.setdefault(b.action, []).append(key_label(b.key))
    up, down = keys.get("layer(scrollup)"), keys.get("layer(scrolldown)")
    boost = keys.get("layer(arrows)")
    if not (up and down and boost):
        return {}
    pre = boost[0] + " + "
    rows = [(pre, ", ".join(up), "Scroll up, %dx faster" % SCROLL_BOOST),
            (pre, ", ".join(down), "Scroll down, %dx faster" % SCROLL_BOOST)]
    return {"Scroll": rows, "Text": rows}


def _section_range(lines, name):
    """(start, end) line indices of [name]; name None = before any header."""
    start = 0 if name is None else None
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if m:
            if start is not None:
                return start, i
            if m.group(1) == name:
                start = i + 1
    return (start, len(lines)) if start is not None else (len(lines),) * 2


def _bound_keys(lines, rng):
    keys = []
    for line in lines[rng[0]:rng[1]]:
        if line.strip().startswith(("#", "include ")):
            continue
        m = BIND_RE.match(line)
        if m:
            keys.append(m.group(1))
    return keys


def _typed_keys(texts):
    """Keys mouse mode takes over: capsnav-nav plus [mousemode] bindings."""
    nav = texts["capsnav-nav"].split("\n")
    dc = texts["default.conf"].split("\n")
    keys = set(_bound_keys(nav, _section_range(nav, None)))
    keys |= set(_bound_keys(dc, _section_range(dc, "mousemode")))
    return keys - NOT_TYPED


def _sync_list(lines, rng, key, value, want):
    """Make `key = value` present (want) or absent in lines[rng]."""
    pat = re.compile(r"^\s*%s\s*=" % re.escape(key))
    hits = [i for i in range(*rng) if pat.match(lines[i])]
    if want and not hits:
        last = max((i for i in range(*rng) if BIND_RE.match(lines[i])
                    and not lines[i].strip().startswith("#")),
                   default=rng[0] - 1)
        lines.insert(last + 1, "%s = %s" % (key, value))
    elif not want:
        for i in reversed(hits):
            del lines[i]


def move(texts, b, new_key):
    """Return a copy of texts with binding b moved onto new_key. Whatever was
    on new_key in the same section becomes `# unbound: …`."""
    texts = dict(texts)
    if new_key == b.key and not b.unbound:
        return texts
    lines = texts[b.file].split("\n")
    rng = _section_range(lines, b.section)
    if b.file == "app.conf":
        pairs = [("%s.%s" % (l, b.key), "%s.%s" % (l, new_key))
                 for l in APP_LAYERS]
    else:
        pairs = [(b.key, new_key)]

    for _old, new in pairs:
        pat = re.compile(r"^\s*%s\s*=" % re.escape(new))
        for i in range(*rng):
            if i not in b.lines and pat.match(lines[i]) \
                    and not lines[i].strip().startswith("#"):
                lines[i] = "# unbound: " + lines[i].strip()

    for i in b.lines:
        line = lines[i]
        um = UNBOUND_RE.match(line)
        old, action = um.groups() if um else BIND_RE.match(line).groups()
        new = dict(pairs).get(old, new_key)
        indent = re.match(r"^\s*", line).group(0)
        lines[i] = "%s%s = %s" % (indent, new, action)
    texts[b.file] = "\n".join(lines)

    linked = b.file == "capsnav-nav" or (
        b.file == "default.conf" and b.section == "mousemode"
        and b.key not in NOT_TYPED)
    if linked:
        typed = _typed_keys(texts)
        mt = texts["capsnav-mousetype"].split("\n")
        dc = texts["default.conf"].split("\n")
        for key in (b.key, new_key):
            want = key in typed
            _sync_list(mt, (0, len(mt)), key, key, want)
            _sync_list(dc, _section_range(dc, "mousemode+control"), key,
                       "C-" + key, want)
        # Keep a single trailing newline in capsnav-mousetype.
        while len(mt) > 1 and mt[-1] == "" and mt[-2] == "":
            mt.pop()
        if mt[-1] != "":
            mt.append("")
        texts["capsnav-mousetype"] = "\n".join(mt)
        texts["default.conf"] = "\n".join(dc)
    return texts


# --- Live files ---------------------------------------------------------------

def read_live():
    texts = {}
    for name in KEYD_FILES:
        with open(os.path.join(KEYD_DIR, name)) as f:
            texts[name] = f.read()
    try:
        with open(APP_CONF) as f:
            texts["app.conf"] = f.read()
    except FileNotFoundError:
        pass
    return texts


def _privileged(cmd):
    askpass = os.environ.get("SUDO_ASKPASS") or os.path.expanduser(
        "~/.local/bin/sudo-askpass")
    if os.access(askpass, os.X_OK):
        env = dict(os.environ, SUDO_ASKPASS=askpass)
        return subprocess.run(["sudo", "-A"] + cmd, env=env,
                              capture_output=True, text=True)
    return subprocess.run(["pkexec"] + cmd, capture_output=True, text=True)


def save(old, new):
    """Write the changed live files and reload. Raises RuntimeError with a
    message on failure (nothing installed)."""
    root_changed = [n for n in KEYD_FILES if new[n] != old[n]]
    if root_changed:
        with tempfile.TemporaryDirectory(prefix="capsnav-") as d:
            for name in KEYD_FILES:
                with open(os.path.join(d, name), "w") as f:
                    f.write(new[name])
            r = subprocess.run(["keyd", "check", os.path.join(d, "default.conf")],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError("keyd check failed, nothing saved:\n"
                                   + (r.stdout + r.stderr).strip())
            r = _privileged(["install", "-m644"]
                            + [os.path.join(d, n) for n in root_changed]
                            + [KEYD_DIR + "/"])
            if r.returncode != 0:
                raise RuntimeError("Not saved (password cancelled or install "
                                   "failed). " + r.stderr.strip())
        r = subprocess.run(["keyd", "reload"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("Saved, but keyd reload failed: "
                               + (r.stdout + r.stderr).strip())
    if "app.conf" in new and new["app.conf"] != old.get("app.conf"):
        tmp = APP_CONF + ".capsnav-tmp"
        with open(tmp, "w") as f:
            f.write(new["app.conf"])
        os.replace(tmp, APP_CONF)
        subprocess.run(["systemctl", "--user", "restart", "capsnav-appmap"],
                       capture_output=True)


def print_view(sections):
    extra = combos(sections)
    for tab, secs in tabs(sections):
        print("##### " + tab)
        for sec in secs:
            print("== " + sec.title)
            for heading, binds in sec.groups:
                if heading:
                    print("  # " + heading)
                for b in binds:
                    print("    %-12s %s" % (prefix(b, sections)
                                            + key_label(b.key),
                                            describe(b.action)))
        if tab in extra:
            if tab == "Scroll":
                print("== Combinations")
            for pre, keys, does in extra[tab]:
                print("    %-12s %s" % (pre + keys, does))
        print()


# --- Window -------------------------------------------------------------------

def run_window():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    class Window(Gtk.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="capsnav mappings")
            self.set_default_size(820, 760)
            self.connect("key-press-event", self.on_key)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.add(box)
            self.notebook = Gtk.Notebook()
            self.notebook.set_vexpand(True)
            box.pack_start(self.notebook, True, True, 0)
            bar = Gtk.Box(spacing=8, margin=8)
            self.status = Gtk.Label(xalign=0)
            self.status.set_line_wrap(True)
            self.status.set_selectable(True)
            bar.pack_start(self.status, True, True, 0)
            self.revert_btn = Gtk.Button(label="Discard")
            self.revert_btn.connect("clicked", lambda _b: self.reload())
            self.apply_btn = Gtk.Button(label="Apply")
            self.apply_btn.get_style_context().add_class("suggested-action")
            self.apply_btn.connect("clicked", self.on_apply)
            bar.pack_end(self.apply_btn, False, False, 0)
            bar.pack_end(self.revert_btn, False, False, 0)
            box.pack_end(bar, False, False, 0)
            self.reload()

        def on_key(self, _w, ev):
            if ev.keyval == Gdk.KEY_Escape:
                self.close()
                return True
            return False

        def reload(self, message=""):
            try:
                self.live = read_live()
            except OSError as e:
                self.live = None
                self.status.set_text("Can't read the configs: %s" % e)
                return
            self.pending = dict(self.live)
            self.draw()
            self.set_dirty(False)
            self.status.set_text(message)

        def set_dirty(self, dirty):
            self.apply_btn.set_sensitive(dirty)
            self.revert_btn.set_sensitive(dirty)

        def draw(self):
            """Rebuild the tabs, keeping the current tab and its scroll."""
            page = self.notebook.get_current_page()
            tab = (self.notebook.get_tab_label_text(
                self.notebook.get_nth_page(page)) if page >= 0 else None)
            scroll = {}
            while self.notebook.get_n_pages():
                child = self.notebook.get_nth_page(0)
                scroll[self.notebook.get_tab_label_text(child)] = \
                    child.get_vadjustment().get_value()
                self.notebook.remove_page(0)
            sections = parse_all(self.pending)
            taken = {(s.file, s.section): {b.key: describe(b.action)
                                           for _h, bs in s.groups for b in bs}
                     for s in sections if s.title != "Unbound"}
            extra = combos(sections)
            for name, secs in tabs(sections):
                scroller = Gtk.ScrolledWindow()
                scroller.set_policy(Gtk.PolicyType.NEVER,
                                    Gtk.PolicyType.AUTOMATIC)
                scroller.add(self.grid(name, secs, taken,
                                       extra.get(name, []), sections))
                scroller.show_all()
                n = self.notebook.append_page(scroller, Gtk.Label(label=name))
                if name == tab:
                    self.notebook.set_current_page(n)
                if name in scroll:
                    GLib.idle_add(scroller.get_vadjustment().set_value,
                                  scroll[name])
            help_text = Gtk.Label(label=HOW_TO_USE, xalign=0, yalign=0,
                                  margin=24)
            help_text.set_line_wrap(True)
            help_text.set_max_width_chars(80)
            help_page = Gtk.ScrolledWindow()
            help_page.set_policy(Gtk.PolicyType.NEVER,
                                 Gtk.PolicyType.AUTOMATIC)
            help_page.add(help_text)
            help_page.show_all()
            n = self.notebook.append_page(help_page,
                                          Gtk.Label(label="How to use"))
            if tab == "How to use":
                self.notebook.set_current_page(n)

        def grid(self, tab, secs, taken, extra, sections):
            grid = Gtk.Grid(column_spacing=16, row_spacing=4, margin=16)
            row = 0
            for sec in secs:
                row = self.title(grid, row, sec.title)
                if sec.intro:
                    row = self.note(grid, row, sec.intro)
                for heading, binds in sec.groups:
                    if heading:
                        row = self.note(grid, row, heading)
                    for b in binds:
                        # Keys already used in the binding's own section (for
                        # an unbound one, the section it came from).
                        here = taken.get((b.file, b.section), {})
                        key = self.key_button(b, here)
                        pre = prefix(b, sections)
                        if pre:
                            box = Gtk.Box(spacing=6)
                            box.pack_start(Gtk.Label(label=pre), False,
                                           False, 0)
                            box.pack_start(key, False, False, 0)
                            key = box
                        grid.attach(key, 0, row, 1, 1)
                        does = Gtk.Label(label=describe(b.action), xalign=0)
                        does.set_line_wrap(True)
                        does.set_hexpand(True)
                        does.set_tooltip_text(b.action)
                        grid.attach(does, 1, row, 1, 1)
                        row += 1
            if extra:
                # In Text these continue the Space + rows; elsewhere they get
                # their own heading.
                if tab != "Text":
                    row = self.title(grid, row, "Combinations")
                for pre, keys, does in extra:
                    key = Gtk.Button(label=keys)
                    key.set_size_request(90, -1)
                    key.set_sensitive(False)
                    key.set_tooltip_text("Follows the scroll keys; move "
                                         "those in the Scroll tab.")
                    box = Gtk.Box(spacing=6)
                    box.pack_start(Gtk.Label(label=pre), False, False, 0)
                    box.pack_start(key, False, False, 0)
                    grid.attach(box, 0, row, 1, 1)
                    grid.attach(Gtk.Label(label=does, xalign=0), 1, row, 1, 1)
                    row += 1
            return grid

        def title(self, grid, row, text):
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<big><b>%s</b></big>"
                           % GLib.markup_escape_text(text))
            lab.set_margin_top(12 if row else 0)
            grid.attach(lab, 0, row, 2, 1)
            return row + 1

        def note(self, grid, row, text):
            lab = Gtk.Label(label=text, xalign=0)
            lab.set_line_wrap(True)
            lab.set_max_width_chars(100)
            lab.get_style_context().add_class("dim-label")
            lab.set_margin_top(6)
            grid.attach(lab, 0, row, 2, 1)
            return row + 1

        def key_button(self, b, taken):
            """A narrow button showing the key; its menu lists every key,
            labelled with what it does if taken."""
            btn = Gtk.MenuButton(label="—" if b.unbound else key_label(b.key))
            btn.set_size_request(90, -1)
            btn.set_halign(Gtk.Align.START)
            btn.set_valign(Gtk.Align.CENTER)
            menu = Gtk.Menu()
            keys = list(CHOICES)
            if not b.unbound and b.key not in keys:
                keys.insert(0, b.key)
            for k in keys:
                label = key_label(k)
                if not b.unbound and k == b.key:
                    label += "  (current)"
                elif k in taken:
                    label += "  — " + taken[k]
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _i, k=k: self.on_pick(k, b))
                menu.append(item)
            menu.show_all()
            btn.set_popup(menu)
            return btn

        def on_pick(self, new_key, b):
            if new_key == b.key and not b.unbound:
                return
            self.pending = move(self.pending, b, new_key)
            self.set_dirty(self.pending != self.live)
            GLib.idle_add(self.draw)
            self.status.set_text("%s → %s: not saved yet, press Apply."
                                 % (describe(b.action), key_label(new_key)))

        def on_apply(self, _btn):
            self.status.set_text("Saving…")
            self.apply_btn.set_sensitive(False)
            while Gtk.events_pending():
                Gtk.main_iteration()
            try:
                save(self.live, self.pending)
            except (RuntimeError, OSError) as e:
                self.status.set_text(str(e))
                self.set_dirty(True)
                return
            self.reload("Saved and reloaded.")

    app = Gtk.Application(application_id="io.github.capsnav.mappings",
                          flags=Gio.ApplicationFlags.FLAGS_NONE)

    def activate(a):
        win = a.get_active_window() or Window(a)
        win.show_all()
        win.present()

    app.connect("activate", activate)
    return app.run([sys.argv[0]])


def main():
    if "--print" in sys.argv[1:]:
        print_view(parse_all(read_live()))
        return 0
    return run_window()


if __name__ == "__main__":
    sys.exit(main())
