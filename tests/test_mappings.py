#!/usr/bin/env python3
"""Tests for the model half of capsnav-mappings (parsing and moving keys).

Run from the repo root: python3 -m unittest discover tests
They read the repo's config files and never touch /etc/keyd.
"""

import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader(
    "capsnav_mappings", os.path.join(ROOT, "capsnav-mappings.py"))
_spec = importlib.util.spec_from_loader("capsnav_mappings", _loader)
cm = importlib.util.module_from_spec(_spec)
_loader.exec_module(cm)

BINDING = re.compile(r"^\s*([^#\s=][^=]*?)\s*=\s*(.+?)\s*$")


def repo_texts():
    texts = {}
    for name in ("capsnav-nav", "default.conf", "capsnav-mousetype",
                         "app.conf"):
        with open(os.path.join(ROOT, name)) as f:
            texts[name] = f.read()
    return texts


def section_lines(text, name):
    """The lines of [name] in an ini text (the whole text for name=None)."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            cur = m.group(1)
            continue
        if cur == name:
            out.append(line)
    return out


def find(sections, title_part, key, unbound=False):
    for sec in sections:
        if title_part in sec.title:
            for _heading, binds in sec.groups:
                for b in binds:
                    if b.key == key and b.unbound == unbound:
                        return b
    raise AssertionError("no %s binding for %r" % (title_part, key))


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.texts = repo_texts()
        self.sections = cm.parse_all(self.texts)

    def shown(self):
        return [(b.file, b.section, b.key) for s in self.sections
                for _h, bs in s.groups for b in bs]

    def test_every_capsnav_nav_binding_once(self):
        shown = self.shown()
        for line in self.texts["capsnav-nav"].splitlines():
            m = BINDING.match(line)
            if m:
                self.assertEqual(
                    shown.count(("capsnav-nav", None, m.group(1))), 1, line)

    def test_every_shown_default_section_binding_once(self):
        shown = self.shown()
        for sec in ("nav", "mousemode", "arrows", "winswitch:A"):
            for line in section_lines(self.texts["default.conf"], sec):
                m = BINDING.match(line)
                if m and not line.strip().startswith("include"):
                    self.assertEqual(
                        shown.count(("default.conf", sec, m.group(1))), 1,
                        (sec, line))

    def test_hidden_sections_not_shown(self):
        secs = {s for (_f, s, _k) in self.shown()}
        for hidden in ("mousemode+control", "mousetype", "main", "global"):
            self.assertNotIn(hidden, secs)
        self.assertNotIn("capsnav-mousetype", {f for (f, _s, _k) in self.shown()})

    def test_vscode_pairs_are_one_row(self):
        code = [b for s in self.sections for _h, bs in s.groups for b in bs
                if b.file == "app.conf"]
        self.assertEqual(sorted(b.key for b in code),
                         sorted(["q", "w", "s", "d", "f", "e"]))

    def test_group_heading_is_comment_above(self):
        b = find(self.sections, "Caps", "t")
        self.assertIn("Tabs", b.group)
        # The file header isn't glued onto the first group.
        b = find(self.sections, "Caps", "i")
        self.assertTrue(b.group.startswith("Mouse:"), b.group)

    def test_describe(self):
        self.assertEqual(cm.describe("C-S-c"), "Ctrl+Shift+C")
        self.assertEqual(cm.describe("C-pageup"), "Ctrl+Page Up")
        self.assertEqual(cm.describe("M-l"), "Super+L")
        self.assertEqual(cm.describe("sysrq"), "PrtSc")
        self.assertEqual(cm.describe("leftmouse"), "Left click")
        self.assertIn("Scroll up", cm.describe("layer(scrollup)"))
        self.assertIn("Pointer up", cm.describe("layer(ijklup)"))
        self.assertEqual(cm.describe("weird(thing)"), "weird(thing)")

    def test_key_label(self):
        self.assertEqual(cm.key_label("semicolon"), ";")
        self.assertEqual(cm.key_label("space"), "Space")
        self.assertEqual(cm.key_label("t"), "t")


class TabsTest(unittest.TestCase):
    def setUp(self):
        self.sections = cm.parse_all(repo_texts())
        self.tabs = cm.tabs(self.sections)

    def tab_of(self, file, section, key):
        hits = [name for name, secs in self.tabs for s in secs
                for _h, bs in s.groups for b in bs
                if (b.file, b.section, b.key) == (file, section, key)]
        self.assertEqual(len(hits), 1, (file, section, key, hits))
        return hits[0]

    def test_every_binding_in_exactly_one_tab(self):
        for s in self.sections:
            for _h, bs in s.groups:
                for b in bs:
                    if b.action != "layer(arrows)":   # hidden: Space
                        self.tab_of(b.file, b.section, b.key)

    def test_tab_order_and_no_empty_tabs(self):
        names = [n for n, _ in self.tabs]
        self.assertEqual(names, ["Mouse", "Scroll", "Browser", "VS Code",
                                 "Windows", "Text", "Other"])
        for _n, secs in self.tabs:
            self.assertTrue(secs)

    def test_examples(self):
        nav = ("capsnav-nav", None)
        for key in "ijklesdfgh":
            self.assertEqual(self.tab_of(*nav, key), "Mouse", key)
        for key, tab in [("semicolon", "Mouse"), ("u", "Mouse"),
                         ("p", "Mouse"), ("n", "Scroll"), ("m", "Scroll"),
                         ("q", "Browser"), ("w", "Browser"), ("t", "Browser"),
                         ("y", "Browser"), ("0", "Windows"), ("7", "Windows"),
                         ("c", "Other"), ("v", "Other")]:
            self.assertEqual(self.tab_of(*nav, key), tab, key)
        dc = "default.conf"
        self.assertEqual(self.tab_of(dc, "nav", "b"), "Windows")
        self.assertEqual(self.tab_of(dc, "mousemode", "b"), "Windows")
        self.assertEqual(self.tab_of(dc, "winswitch:A", "j"), "Windows")
        self.assertEqual(self.tab_of(dc, "mousemode", "0"), "Windows")
        self.assertEqual(self.tab_of(dc, "arrows", "i"), "Text")
        self.assertEqual(self.tab_of(dc, "mousemode", "leftshift"), "Other")
        self.assertEqual(self.tab_of(dc, "mousemode", "capslock"), "Other")
        self.assertEqual(self.tab_of("app.conf", "code", "s"), "VS Code")

    def test_clicks_grouped(self):
        b = find(self.sections, "Caps", "g")
        self.assertTrue(b.group.startswith("Clicks"), b.group)
        self.assertEqual(find(self.sections, "Caps", "h").group, b.group)
        self.assertEqual(find(self.sections, "Caps", "semicolon").group,
                         b.group)

    def test_scroll_combo(self):
        self.assertEqual(cm.combos(self.sections), {
            "Scroll": [("Space + ", "n / m",
                        "Scroll 6x faster (hold Space while scrolling)")],
            "Text": [("Space + ", "n", "Scroll up, 6x faster"),
                     ("Space + ", "m", "Scroll down, 6x faster")]})

    def test_scroll_combo_follows_moved_keys(self):
        texts = repo_texts()
        b = find(self.sections, "Caps", "n")
        secs = cm.parse_all(cm.move(texts, b, "z"))
        self.assertEqual(cm.combos(secs)["Scroll"][0][1], "z / m")
        self.assertEqual(cm.combos(secs)["Text"][0][1], "z")

    def test_text_tab_is_one_section_with_space_prefix(self):
        text = dict(self.tabs)["Text"]
        self.assertEqual([s.title for s in text], ["Caps layer / mouse mode"])
        rows = [(cm.prefix(b, self.sections), b.key, b.action)
                for _h, bs in text[0].groups for b in bs]
        self.assertEqual(rows, [("Space + ", "i", "up"),
                                ("Space + ", "j", "left"),
                                ("Space + ", "k", "down"),
                                ("Space + ", "l", "right")])

    def test_unbound_tab(self):
        texts = repo_texts()
        b = find(self.sections, "Caps", "t")
        tabs = cm.tabs(cm.parse_all(cm.move(texts, b, "q")))
        self.assertEqual(tabs[-1][0], "Unbound")
        self.assertEqual(
            [x.key for s in tabs[-1][1] for _h, bs in s.groups for x in bs],
            ["q"])


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.texts = repo_texts()
        self.sections = cm.parse_all(self.texts)

    def test_move_to_free_key(self):
        b = find(self.sections, "Caps", "t")      # new tab
        new = cm.move(self.texts, b, "z")
        nav = new["capsnav-nav"]
        self.assertIn("\nz = C-t\n", nav)
        self.assertNotRegex(nav, r"(?m)^t = ")
        # Only that line changed in capsnav-nav.
        old_lines = self.texts["capsnav-nav"].splitlines()
        new_lines = nav.splitlines()
        self.assertEqual(len(old_lines), len(new_lines))
        self.assertEqual(sum(a != c for a, c in zip(old_lines, new_lines)), 1)
        # Linked lists follow.
        mt = new["capsnav-mousetype"]
        self.assertRegex(mt, r"(?m)^z = z$")
        self.assertNotRegex(mt, r"(?m)^t = t$")
        ctrl = section_lines(new["default.conf"], "mousemode+control")
        self.assertIn("z = C-z", ctrl)
        self.assertNotIn("t = C-t", ctrl)

    def test_overwrite_makes_unbound(self):
        b = find(self.sections, "Caps", "t")
        new = cm.move(self.texts, b, "q")          # q was previous tab
        nav = new["capsnav-nav"]
        self.assertRegex(nav, r"(?m)^q = C-t$")
        self.assertRegex(nav, r"(?m)^# unbound: q = C-pageup$")
        secs = cm.parse_all(new)
        u = find(secs, "Unbound", "q", unbound=True)
        self.assertEqual(u.action, "C-pageup")
        # t is free now, q still typed by mouse mode: lists drop t, keep q.
        self.assertNotRegex(new["capsnav-mousetype"], r"(?m)^t = t$")
        self.assertRegex(new["capsnav-mousetype"], r"(?m)^q = q$")

    def test_rebind_from_unbound(self):
        b = find(self.sections, "Caps", "t")
        step1 = cm.move(self.texts, b, "q")
        u = find(cm.parse_all(step1), "Unbound", "q", unbound=True)
        step2 = cm.move(step1, u, "t")
        nav = step2["capsnav-nav"]
        self.assertRegex(nav, r"(?m)^t = C-pageup$")
        self.assertRegex(nav, r"(?m)^q = C-t$")
        self.assertNotIn("# unbound:", nav)
        self.assertRegex(step2["capsnav-mousetype"], r"(?m)^t = t$")

    def test_vscode_pair_moves_together(self):
        b = next(b for s in self.sections for _h, bs in s.groups for b in bs
                 if b.file == "app.conf" and b.key == "s")
        new = cm.move(self.texts, b, "z")["app.conf"]
        self.assertRegex(new, r"(?m)^nav\.z = C-f$")
        self.assertRegex(new, r"(?m)^mousemode\.z = C-f$")
        self.assertNotRegex(new, r"(?m)^(nav|mousemode)\.s = ")

    def test_section_local_move(self):
        b = find(self.sections, "Caps+Space", "i")
        new = cm.move(self.texts, b, "u")
        self.assertIn("u = up", section_lines(new["default.conf"], "arrows"))
        # Not a mouse-mode key: lists untouched.
        self.assertEqual(new["capsnav-mousetype"],
                         self.texts["capsnav-mousetype"])

    def test_mousemode_leftshift_skips_lists(self):
        b = find(self.sections, "Mouse mode only", "leftshift")
        new = cm.move(self.texts, b, "rightshift")
        self.assertEqual(new["capsnav-mousetype"],
                         self.texts["capsnav-mousetype"])

    @unittest.skipUnless(shutil.which("keyd"), "keyd not installed")
    def test_staged_result_passes_keyd_check(self):
        b = find(self.sections, "Caps", "t")
        new = cm.move(self.texts, b, "q")
        with tempfile.TemporaryDirectory() as d:
            for name in ("default.conf", "capsnav-nav", "capsnav-mousetype"):
                with open(os.path.join(d, name), "w") as f:
                    f.write(new[name])
            r = subprocess.run(["keyd", "check", os.path.join(d, "default.conf")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
