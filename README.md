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
| j      | Smooth scroll up (hold)   |
| k      | Smooth scroll down (hold) |

## Files
- `default.conf`: the keyd config. The live copy is `/etc/keyd/default.conf`.
- `keyd-src/`: keyd source used for the install.
- `install.sh`: builds and installs keyd, copies the config, installs the scroll helper, and starts both services.
- `capsnav-scroll.py`: smooth-scroll helper, installed as `/usr/local/bin/capsnav-scroll`.
- `capsnav-scroll.service`: systemd unit that runs the helper.
- `scroll.conf`: scroll speed, easing and event rate. The live copy is `/etc/capsnav/scroll.conf`.
- `tools/scroll-curve.py`: previews scroll settings as a speed curve; no root needed.

## Smooth scrolling
Caps+j / Caps+k send no keys of their own. They switch on the empty keyd layers
`scrollup` / `scrolldown`. `capsnav-scroll` watches those layers via
`keyd listen`, and while one is active it sends high-resolution wheel events
at `tick_hz` (default 120) from a virtual pointer. Speed eases in on press and glides to a stop
on release, like a touchpad.

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

## Common tasks
- Apply config edits: `sudo cp default.conf /etc/keyd/default.conf && sudo keyd reload`
- Uninstall: `sudo systemctl disable --now capsnav-scroll keyd && sudo rm -r /etc/systemd/system/capsnav-scroll.service /usr/local/bin/capsnav-scroll /etc/capsnav && sudo make -C keyd-src uninstall`
- If the keyboard locks up: press Backspace+Escape+Enter together to stop keyd.

## keyd version
`keyd-src/` is vendored from https://github.com/rvaiya/keyd at commit
`f564288ac2b19d2305a5b39023c474805ff8fce5` (v2.6.0, MIT license).
