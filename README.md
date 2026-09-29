# capsnav

Hold Caps Lock for arrow keys on i/j/k/l and more, using keyd (v2.6.0, built from source).

| Caps + | Sends       |
|--------|-------------|
| i      | Up          |
| j      | Left        |
| k      | Down        |
| l      | Right       |
| u      | Esc         |
| h      | Backspace   |
| t      | Ctrl+Home (top of page)    |
| v      | Ctrl+End (bottom of page)  |
| y      | Home (start of line)       |
| o      | End (end of line)          |
| d      | F12 (VS Code: go to definition) |
| ;      | Ctrl+Shift+O (VS Code: go to symbol in file) |
| 8      | Ctrl+Alt+- (VS Code: go back)    |
| 9      | Ctrl+Shift+- (VS Code: go forward) |
| n      | Smooth scroll up (hold)   |
| m      | Smooth scroll down (hold) |
| Space+i/j/k/l | Move the mouse pointer up/left/down/right (hold; combine for diagonals) |
| Space+n | Left click (hold while moving to drag) |
| Space+m | Right click |
| p      | Move pointer + focus to the other monitor |
| g      | Click hints: label everything clickable, type a label to click it |
| b      | Window switcher (Alt+Tab): hold Caps, tap b to cycle, j/l to move, release to pick |
| Alt+j  | Ctrl+PageUp (previous tab)  |
| Alt+l  | Ctrl+PageDown (next tab)    |

## Install
Requires Linux with systemd; the Caps+p and Caps+g shortcuts need GNOME on X11.
Ubuntu/Debian and Fedora are supported:

```bash
git clone https://github.com/dharani123/capsnav.git
cd capsnav && ./install.sh
```

Run it as your normal user; it asks for your `sudo` password. It installs the
system packages (build tools, xdotool, hints' build deps), builds keyd, installs
the config, the smooth-scroll helper, the switch-monitor script and
[hints](#click-hints-capsg), starts the services, and adds the GNOME shortcuts.
Reboot once when it says so. Re-running it is safe and applies any changes.

On other distros, install the equivalent of the apt package list at the top of
`install.sh` first; the script then skips that step.

Before installing:
- **Existing keyd config is replaced.** `/etc/keyd/default.conf` is
  overwritten, so back it up if you already use keyd. If keyd came from your
  distro's packages, remove that first so two versions don't conflict.
- **Caps Lock no longer toggles capitals.** It becomes the navigation key.
- **Emergency stop:** if the keyboard misbehaves, press Backspace+Escape+Enter
  together to stop keyd.

### Recommended VS Code settings
For smooth Caps+n/m scrolling in VS Code, add these to your VS Code
`settings.json`:

```json
"editor.smoothScrolling": true,
"workbench.list.smoothScrolling": true,
"terminal.integrated.smoothScrolling": true,
```

## Files
- `default.conf`: the keyd config. The live copy is `/etc/keyd/default.conf`.
- `keyd-src/`: keyd source used for the install.
- `install.sh`: installs everything above (packages, keyd, config, scroll helper, switch-monitor, hints, GNOME shortcuts). Safe to re-run.
- `capsnav-scroll.py`: smooth-scroll helper, installed as `/usr/local/bin/capsnav-scroll`.
- `capsnav-scroll.service`: systemd unit that runs the helper.
- `capsnav-mouse.service`: systemd user unit that runs the same helper with `--mouse` for pointer motion.
- `mouse.conf`: scroll and pointer speed, easing and event rate. The live copy is `/etc/capsnav/mouse.conf`.
- `capsnav-switch-monitor.sh`: Caps+p helper, installed as `/usr/local/bin/capsnav-switch-monitor` (see below).
- `hintsd.service`: systemd user unit for the hints daemon, installed to `~/.config/systemd/user/`.
- `hints-config.json`: hints settings for Caps+g, installed to `~/.config/hints/config.json`.
- `tools/scroll-curve.py`: previews scroll settings as a speed curve; no root needed.
- `system/keyd-restart.conf`: systemd drop-in that restarts keyd if it crashes (not after the emergency stop).
- `system/capsnav.quirks`, `system/50-capsnav-scroll.conf`: the libinput and X settings for continuous scrolling (see below).

## Smooth scrolling
Caps+n / Caps+m send no keys of their own. They switch on the empty keyd layers
`scrollup` / `scrolldown`. `capsnav-scroll` watches those layers via
`keyd listen`, and while one is active it sends small scroll steps at
`tick_hz` from a virtual pointer. Speed eases in on press and glides to a stop
on release, like a touchpad.

### Why the libinput and X settings
For wheel devices, libinput holds back the first half click of any scroll that
starts after 500 ms of no scrolling (a filter against wheel jitter), then
releases it at once. Chrome animates scrolling and hides that jump, but VS Code
and terminals show it as a jerk at the start. To avoid it, capsnav:
- marks its virtual device as a Lenovo ScrollPoint in
  `/etc/libinput/local-overrides.quirks`, so libinput treats its scroll as
  continuous, like a touchpad, with no hold-back;
- sets `ScrollPixelDistance` to 50 in
  `/etc/X11/xorg.conf.d/50-capsnav-scroll.conf`, so 50 units make one click,
  the finest steps the X driver allows.

libinput reads these settings only when the display server starts, so reboot
once after installing. Until then, `capsnav-scroll` safely falls back to
high-resolution wheel events (with the jerk). `journalctl -u capsnav-scroll`
shows which mode is active: `scroll mode: continuous` or `scroll mode: wheel`.

### How the easing works
Motion looks smooth when position, speed *and acceleration* all change without
jumps. Starting at full speed jumps the speed (a thud); a simple exponential
ease jumps the acceleration (a kick). capsnav drives the speed with a
critically damped spring, so speed builds and fades along an S-curve. It never
overshoots, and it carries on smoothly if you release or reverse mid-glide.

Other details that keep it fluid:
- **Even steps:** events go out on fixed deadlines at `tick_hz`, each the
  same size at steady speed; uneven steps between frames read as judder.
- **Clean tail:** a glide ends once steps fall below half a unit, before
  rounding would flicker 1, 0, 1, 0.
- **Short ease-in, longer ease-out:** under ~100 ms feels instant on press,
  and a softer stop lets your eyes keep their place.
- **Modest values:** Chrome and VS Code (with `smoothScrolling`) add their own
  animation on top.

### Tuning
Preview settings without installing, as curves and numbers:
`tools/scroll-curve.py 50/100 100/200 --hz 60`

Then edit `mouse.conf` and copy it into place:
`sudo cp mouse.conf /etc/capsnav/mouse.conf`
It takes effect on the next scroll with no restart.

## Pointer motion (Caps+Space)
Hold Caps+Space, then i/j/k/l (up/left/down/right) to move the pointer; hold
two for a diagonal. n left-clicks and m right-clicks (keyd sends the buttons
itself); the button stays down while the key is held, so hold n and move to
drag. (So while Space is held, n/m click rather than scroll.)
It eases in and glides to a stop on the same spring as scrolling. In
`mouse.conf`, `pointer_speed` sets the top speed in pixels per second and
`pointer_ease_in_ms` the ease-in (slower than scrolling's by default, so a quick
tap nudges the pointer a few pixels); the glide and rate share `ease_out_ms`
and `tick_hz` with scrolling.

keyd turns on the empty layers `mouseleft` / `mouseright` / `mouseup` /
`mousedown`, and `capsnav-scroll --mouse` (the user service
`capsnav-mouse`) watches them. It moves the pointer with XTest rather than a
virtual mouse, because GNOME applies pointer acceleration to every mouse,
which would bend the curve; XTest moves exact pixels. XTest needs your X
session, so this part runs as you rather than root, and `install.sh` adds you
to the `keyd` group so it can read `keyd listen` (takes effect at next login).
X11 only.

## Switching monitors
keyd runs as root with no access to your X session, so Caps+p can't run the
script directly. It sends Super+Alt+O instead, and `install.sh` adds a GNOME
custom shortcut ("capsnav: switch monitor") that runs
`capsnav-switch-monitor`. The script moves the pointer to the centre of the
next monitor and focuses the topmost window there. It reads the layout from
`xrandr` each time, so it follows monitor changes. X11 only; on another
desktop, bind Super+Alt+O to the script yourself.

## Click hints (Caps+g)
Caps+g sends Super+Alt+F, which `install.sh` binds to
[hints](https://github.com/AlfredoSequeida/hints) (Vimium for the whole
desktop). Every clickable element gets a label; type it to click.
Shift+label right-clicks, Ctrl+label hovers, Esc cancels.

`hints-config.json` (installed to `~/.config/hints/config.json`) turns off
Alt+label drag. Drag holds the mouse button down and silently captures the
keyboard until Esc, which looks like a frozen desktop if you hit it by accident
(easy after Caps+Alt tab switching).

**If the desktop seems stuck:** press Esc. If that fails, press Ctrl+Alt+F3,
log in, run `pkill -f hints; systemctl --user restart hintsd`, and return with
Ctrl+Alt+F2 (or F1).

hints is not vendored: `install.sh` installs the pinned version (0.1.1) with
[uv](https://docs.astral.sh/uv/) into `~/.local`, fetching uv temporarily if you
don't have it. Instead of `hints --setup` (which duplicates lines on re-runs),
`install.sh` does the same steps itself: turns on accessibility in
`/etc/environment` and `~/.xprofile` so apps report their buttons, loads
`uinput`, adds a udev rule, adds you to the `input` group (any program you run
can then read raw keyboard input), and starts the `hintsd` user service
(`hintsd.service`). Apps that expose no accessibility info fall back to image detection,
which is less precise.

## Common tasks
- Apply config edits: `sudo cp default.conf /etc/keyd/default.conf && sudo keyd reload`
- Uninstall: `sudo systemctl disable --now capsnav-scroll keyd && sudo rm -r /etc/systemd/system/capsnav-scroll.service /usr/local/bin/capsnav-scroll /etc/capsnav /etc/X11/xorg.conf.d/50-capsnav-scroll.conf /usr/local/bin/capsnav-switch-monitor && systemctl --user disable --now capsnav-mouse && rm ~/.config/systemd/user/capsnav-mouse.service && sudo gpasswd -d $USER keyd && sudo rm -r /etc/systemd/system/keyd.service.d/capsnav-restart.conf && sudo make -C keyd-src uninstall`, then delete the `[capsnav smooth scroll]` section from `/etc/libinput/local-overrides.quirks` and the "capsnav: switch monitor" and "capsnav: hints" shortcuts in Settings → Keyboard → Custom Shortcuts. To remove hints too: `systemctl --user disable --now hintsd; rm ~/.config/systemd/user/hintsd.service; rm -r ~/.config/hints; uv tool uninstall hints` (or delete `~/.local/share/uv/tools/hints` and `~/.local/bin/hints*`), `sudo rm /etc/udev/rules.d/80-hints.rules /etc/modules-load.d/uinput.conf`, `sudo gpasswd -d $USER input`, and delete the accessibility lines from `/etc/environment` and `~/.xprofile`
- If the keyboard locks up: press Backspace+Escape+Enter together to stop keyd.

## keyd version
`keyd-src/` is vendored from https://github.com/rvaiya/keyd at commit
`f564288ac2b19d2305a5b39023c474805ff8fce5` (v2.6.0, MIT license).
