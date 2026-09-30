#!/usr/bin/env bash
# capsnav diagnostics: checks that everything install.sh sets up is in place
# and working. Read-only: changes nothing and needs no sudo. Run it as the
# desktop user, in a terminal inside the graphical session, and share the
# whole output when asking for help.
cd "$(dirname "$0")"
ok=0 warn=0 fail=0
pass() { echo "[ OK ] $*"; ok=$((ok + 1)); }
warn() { echo "[WARN] $*"; warn=$((warn + 1)); }
bad()  { echo "[FAIL] $*"; fail=$((fail + 1)); }
info() { echo "       $*"; }
section() { echo; echo "== $*"; }
have() { command -v "$1" >/dev/null; }

echo "capsnav check.sh — $(date '+%F %T')"

section "System"
. /etc/os-release 2>/dev/null
info "distro:  ${PRETTY_NAME:-unknown}"
info "kernel:  $(uname -r)"
info "desktop: ${XDG_CURRENT_DESKTOP:-unknown}, session: ${XDG_SESSION_TYPE:-unknown}, DISPLAY=${DISPLAY:-unset}"
info "capsnav: $(git log -1 --format='%h %s' 2>/dev/null || echo 'not a git checkout')"
case "$XDG_SESSION_TYPE" in
	x11) pass "X11 session (mouse movement, Caps+p/u need X11)" ;;
	wayland) bad "Wayland session: mouse movement and Caps+p/u only work on X11. Keys, scrolling and copy/paste still work. Fix: log out, pick 'Ubuntu on Xorg' (gear icon on the login screen)." ;;
	*) warn "Unknown session type '$XDG_SESSION_TYPE' (run this from a terminal inside the desktop)" ;;
esac
[[ "$XDG_CURRENT_DESKTOP" == *GNOME* ]] && pass "GNOME desktop (Caps+p/u shortcuts)" \
	|| warn "Not GNOME: bind Super+Alt+O / Super+Alt+U to capsnav-switch-monitor yourself for Caps+p/u"

section "Dependencies"
for cmd in python3 xdotool xprop xrandr gsettings; do
	have "$cmd" && pass "$cmd found" || bad "$cmd missing (install it; see README)"
done

section "keyd"
if [ -x /usr/local/bin/keyd ]; then
	pass "keyd installed: $(/usr/local/bin/keyd -v 2>&1 | head -1)"
else
	bad "/usr/local/bin/keyd missing: run ./install.sh"
fi
others=$(type -ap keyd | grep -v '^/usr/local/bin/keyd$')
[ -n "$others" ] && warn "another keyd found: $others (a distro package can conflict; remove it)"
if have dpkg && dpkg -l keyd 2>/dev/null | grep -q '^ii'; then
	warn "distro keyd package installed (conflicts with the source build): sudo apt remove keyd"
fi
systemctl is-active --quiet keyd && pass "keyd service running" || bad "keyd service not running: sudo systemctl restart keyd; journalctl -u keyd -b"
systemctl is-enabled --quiet keyd 2>/dev/null && pass "keyd enabled at boot" || warn "keyd not enabled at boot: sudo systemctl enable keyd"
[ -f /etc/systemd/system/keyd.service.d/capsnav-restart.conf ] && pass "keyd auto-restart drop-in present" || warn "keyd auto-restart drop-in missing: run ./install.sh"
if [ -f /etc/keyd/default.conf ]; then
	if cmp -s default.conf /etc/keyd/default.conf; then pass "/etc/keyd/default.conf matches repo"
	else warn "/etc/keyd/default.conf differs from repo default.conf (edited, or not reinstalled)"; fi
	if have keyd; then
		out=$(keyd check /etc/keyd/default.conf 2>&1 | tail -1)
		[[ "$out" == *"No errors"* ]] && pass "keyd config parses" || bad "keyd config errors: $out"
	fi
else
	bad "/etc/keyd/default.conf missing: run ./install.sh"
fi
[ -e /dev/uinput ] && pass "/dev/uinput exists" || bad "/dev/uinput missing (kernel uinput module): sudo modprobe uinput"
crashes=$(journalctl -u keyd -b -o cat --no-pager 2>/dev/null | grep -c 'SEGV')
[ "$crashes" -gt 0 ] 2>/dev/null && warn "keyd crashed $crashes time(s) this boot (auto-restarted)"
matched=$(journalctl -u keyd -b -o cat --no-pager 2>/dev/null | grep 'DEVICE: match' | sed 's/.*(\(.*\))/\1/' | sort -u | paste -sd, -)
if [ -n "$matched" ]; then info "keyboards keyd uses: $matched"
else info "keyboards keyd uses: (can't read keyd's log; add yourself to 'adm' or 'systemd-journal' to see it)"; fi

section "Groups (the mouse helper reads 'keyd listen')"
if getent group keyd | grep -qw "$USER"; then
	if id -nG | grep -qw keyd; then pass "$USER is in the keyd group"
	else bad "$USER was added to keyd but this login predates it: log out and back in (or reboot)"; fi
else
	bad "$USER is not in the keyd group: run ./install.sh (then log out and back in)"
fi
if have keyd && id -nG | grep -qw keyd; then
	out=$(timeout 1 keyd listen 2>&1 | head -1)
	[[ "$out" == *"Failed to connect"* ]] && bad "can't read keyd socket: $out" || pass "keyd socket readable"
fi

section "Smooth scroll (capsnav-scroll, root service)"
cmp -s capsnav-scroll.py /usr/local/bin/capsnav-scroll && pass "capsnav-scroll installed and matches repo" \
	|| { [ -f /usr/local/bin/capsnav-scroll ] && warn "/usr/local/bin/capsnav-scroll differs from repo (not reinstalled)" || bad "capsnav-scroll not installed: run ./install.sh"; }
systemctl is-active --quiet capsnav-scroll && pass "capsnav-scroll service running" || bad "capsnav-scroll not running: journalctl -u capsnav-scroll -b"
if [ -f /etc/capsnav/mouse.conf ]; then
	cmp -s mouse.conf /etc/capsnav/mouse.conf && pass "/etc/capsnav/mouse.conf matches repo" || warn "/etc/capsnav/mouse.conf differs from repo (your own tuning?)"
else
	bad "/etc/capsnav/mouse.conf missing: run ./install.sh"
fi
mode=$(journalctl -u capsnav-scroll -b -o cat --no-pager 2>/dev/null | grep 'scroll mode' | tail -1)
case "$mode" in
	*continuous*) pass "scroll mode: continuous" ;;
	*wheel*) warn "scroll mode: wheel (a reboot after install switches to smoother continuous mode)" ;;
	*) info "scroll mode: unknown (can't read the service log)" ;;
esac
grep -qs "capsnav smooth scroll" /etc/libinput/local-overrides.quirks && pass "libinput quirk present" || warn "libinput quirk missing: run ./install.sh"
[ -f /etc/X11/xorg.conf.d/50-capsnav-scroll.conf ] && pass "Xorg scroll setting present" || warn "Xorg scroll setting missing (/etc/X11/xorg.conf.d/50-capsnav-scroll.conf)"

section "Mouse movement (capsnav-mouse, user service)"
[ -f "$HOME/.config/systemd/user/capsnav-mouse.service" ] && pass "capsnav-mouse unit installed" || bad "capsnav-mouse unit missing: run ./install.sh"
if systemctl --user is-active --quiet capsnav-mouse; then pass "capsnav-mouse running"
else bad "capsnav-mouse not running: systemctl --user restart capsnav-mouse; journalctl --user -u capsnav-mouse -b"; fi
errs=$(journalctl --user -u capsnav-mouse -b -o cat --no-pager 2>/dev/null | grep -E 'Error|Traceback|cannot open|Failed to connect' | sort | uniq -c | tail -3)
[ -n "$errs" ] && { warn "capsnav-mouse logged errors this boot:"; echo "$errs" | sed 's/^/         /'; }
env=$(systemctl --user show-environment 2>/dev/null)
grep -q '^DISPLAY=' <<<"$env" && pass "user services see DISPLAY ($(grep '^DISPLAY=' <<<"$env" | cut -d= -f2))" \
	|| bad "user services have no DISPLAY: the mouse helper can't reach X (log out and back in)"

section "X11 access"
if have xdotool && [ -n "$DISPLAY" ]; then
	loc=$(xdotool getmouselocation 2>&1) && pass "pointer readable: $loc" || bad "xdotool can't read the pointer: $loc"
fi
have xrandr && [ -n "$DISPLAY" ] && info "monitors: $(xrandr --listmonitors 2>/dev/null | tail -n +2 | awk '{print $4, $3}' | paste -sd'; ' -)"

section "Caps+p / Caps+u (GNOME shortcuts)"
[ -x /usr/local/bin/capsnav-switch-monitor ] && pass "capsnav-switch-monitor installed" || bad "capsnav-switch-monitor missing: run ./install.sh"
if have gsettings; then
	schema=org.gnome.settings-daemon.plugins.media-keys
	list=$(gsettings get $schema custom-keybindings 2>/dev/null)
	for want in 'capsnav: switch monitor|<Super><Alt>o' 'capsnav: center pointer|<Super><Alt>u'; do
		name=${want%%|*} key=${want##*|} found=
		for p in $(echo "$list" | grep -o "'[^']*'" | tr -d "'"); do
			if [ "$(gsettings get $schema.custom-keybinding:"$p" name)" = "'$name'" ]; then
				found=$(gsettings get $schema.custom-keybinding:"$p" binding)
			fi
		done
		if [ "$found" = "'$key'" ]; then pass "shortcut '$name' = $key"
		elif [ -n "$found" ]; then warn "shortcut '$name' bound to $found, expected $key"
		else bad "shortcut '$name' missing: run ./install.sh"; fi
	done
fi

section "Summary"
echo "$ok ok, $warn warnings, $fail failures"
[ "$fail" -eq 0 ] && [ "$warn" -eq 0 ] && echo "Everything looks good."
echo "Share this whole output when asking for help."
