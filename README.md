# capsnav

Hold Caps Lock for vim-style navigation, using keyd (v2.6.0, built from source).

| Caps + | Sends       |
|--------|-------------|
| u      | Up          |
| n      | Down        |
| h      | Left        |
| l      | Right       |
| m      | Backspace   |
| t      | Ctrl+Home (top of page)    |
| v      | Ctrl+End (bottom of page)  |
| y      | Home (start of line)       |
| o      | End (end of line)          |
| i      | Esc         |
| d      | F12 (VS Code: go to definition) |
| ;      | Ctrl+Shift+O (VS Code: go to symbol in file) |
| 8      | Ctrl+Alt+- (VS Code: go back)    |
| 9      | Ctrl+Shift+- (VS Code: go forward) |
| j      | Smooth scroll up (hold)   |
| k      | Smooth scroll down (hold) |
| p      | Move pointer + focus to the other monitor |
| f      | Click hints: label everything clickable, type a label to click it |
| Alt+h  | Ctrl+PageUp (previous tab)  |
| Alt+l  | Ctrl+PageDown (next tab)    |

## Install
Requires Linux with systemd. On Ubuntu/Debian:

```bash
sudo apt install -y git build-essential python3 xdotool x11-utils x11-xserver-utils
git clone https://github.com/dharani123/capsnav.git
cd capsnav && ./install.sh
```

On Fedora, use `sudo dnf install -y git gcc make python3 xdotool xprop xrandr` for the first line.
`install.sh` builds keyd, installs the config, the smooth-scroll helper and the
switch-monitor script, starts both services, and adds the GNOME shortcuts for
Caps+p and Caps+f. It asks for your `sudo` password. Caps+f also needs
[hints](#click-hints-capsf), installed separately.

Before installing:
- **Existing keyd config is replaced.** `/etc/keyd/default.conf` is
  overwritten, so back it up if you already use keyd. If keyd came from your
  distro's packages, remove that first so two versions don't conflict.
- **Caps Lock no longer toggles capitals.** It becomes the navigation key.
- **Emergency stop:** if the keyboard misbehaves, press Backspace+Escape+Enter
  together to stop keyd.

### Recommended VS Code settings
For smooth Caps+j/k scrolling in VS Code, add these to your VS Code
`settings.json`:

```json
"editor.smoothScrolling": true,
"workbench.list.smoothScrolling": true,
"terminal.integrated.smoothScrolling": true,
```

## Files
- `default.conf`: the keyd config. The live copy is `/etc/keyd/default.conf`.
- `keyd-src/`: keyd source used for the install.
- `install.sh`: builds and installs keyd, copies the config, installs the scroll helper, and starts both services.
- `capsnav-scroll.py`: smooth-scroll helper, installed as `/usr/local/bin/capsnav-scroll`.
- `capsnav-scroll.service`: systemd unit that runs the helper.
- `scroll.conf`: scroll speed, easing and event rate. The live copy is `/etc/capsnav/scroll.conf`.
- `capsnav-switch-monitor.sh`: Caps+p helper, installed as `/usr/local/bin/capsnav-switch-monitor` (see below).
- `hints-config.json`: hints settings for Caps+f, installed to `~/.config/hints/config.json`.
- `tools/scroll-curve.py`: previews scroll settings as a speed curve; no root needed.
- `system/capsnav.quirks`, `system/50-capsnav-scroll.conf`: the libinput and X settings for continuous scrolling (see below).

## Smooth scrolling
Caps+j / Caps+k send no keys of their own. They switch on the empty keyd layers
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

Then edit `scroll.conf` and copy it into place:
`sudo cp scroll.conf /etc/capsnav/scroll.conf`
It takes effect on the next scroll with no restart.

## Switching monitors
keyd runs as root with no access to your X session, so Caps+p can't run the
script directly. It sends Super+Alt+O instead, and `install.sh` adds a GNOME
custom shortcut ("capsnav: switch monitor") that runs
`capsnav-switch-monitor`. The script moves the pointer to the centre of the
next monitor and focuses the topmost window there. It reads the layout from
`xrandr` each time, so it follows monitor changes. X11 only; on another
desktop, bind Super+Alt+O to the script yourself.

## Click hints (Caps+f)
Caps+f sends Super+Alt+F, which `install.sh` binds to
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

hints is not vendored here. Install it once (tested with 0.1.1):

```bash
sudo apt install -y libcairo2-dev pkg-config cmake libdbus-1-dev libgirepository1.0-dev gcc
curl -fsSL https://raw.githubusercontent.com/AlfredoSequeida/hints/main/install.sh | bash -s -- --version 0.1.1
sudo env XDG_SESSION_TYPE=$XDG_SESSION_TYPE XDG_CURRENT_DESKTOP=$XDG_CURRENT_DESKTOP ~/.local/bin/hints --setup
```

Then reboot. `--setup` turns on accessibility in `/etc/environment` and
`~/.xprofile` so apps report their buttons, adds you to the `input` group (any
program you run can then read raw keyboard input), and starts the `hintsd` user
service. Apps that expose no accessibility info fall back to image detection,
which is less precise.

## Common tasks
- Apply config edits: `sudo cp default.conf /etc/keyd/default.conf && sudo keyd reload`
- Uninstall: `sudo systemctl disable --now capsnav-scroll keyd && sudo rm -r /etc/systemd/system/capsnav-scroll.service /usr/local/bin/capsnav-scroll /etc/capsnav /etc/X11/xorg.conf.d/50-capsnav-scroll.conf /usr/local/bin/capsnav-switch-monitor && sudo make -C keyd-src uninstall`, then delete the `[capsnav smooth scroll]` section from `/etc/libinput/local-overrides.quirks` and the "capsnav: switch monitor" and "capsnav: hints" shortcuts in Settings → Keyboard → Custom Shortcuts
- If the keyboard locks up: press Backspace+Escape+Enter together to stop keyd.

## keyd version
`keyd-src/` is vendored from https://github.com/rvaiya/keyd at commit
`f564288ac2b19d2305a5b39023c474805ff8fce5` (v2.6.0, MIT license).
