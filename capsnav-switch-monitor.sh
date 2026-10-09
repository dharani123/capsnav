#!/usr/bin/env bash
# Move the pointer to the next monitor and focus the topmost window on it.
# With --center, just move the pointer to the centre of the current monitor.
# X11 only. Caps+p sends Super+Alt+O and Caps+u Super+Alt+U, which install.sh
# binds to this script as GNOME custom shortcuts.
center=
[ "$1" = --center ] && center=1
eval "$(xdotool getmouselocation --shell)"   # sets X, Y

# Monitor geometries: w h x y
mapfile -t mons < <(xrandr --listmonitors | awk 'NR>1 {split($3,a,/[\/x+]/); print a[1], a[3], a[5], a[6]}')
n=${#mons[@]}
cur=0
for i in "${!mons[@]}"; do
    read -r w h x y <<<"${mons[i]}"
    if (( X >= x && X < x + w && Y >= y && Y < y + h )); then cur=$i; fi
done
if [ -n "$center" ]; then
    read -r w h x y <<<"${mons[cur]}"
    xdotool mousemove $((x + w / 2)) $((y + h / 2))
    exit
fi
read -r w h x y <<<"${mons[(cur + 1) % n]}"

# Topmost visible, non-minimised window whose centre is on the target monitor,
# on the current workspace (or on all of them: 4294967295), since activating
# a window on another workspace switches to it.
desk=$(xdotool get_desktop)
stack=$(xprop -root _NET_CLIENT_LIST_STACKING | grep -o '0x[0-9a-f]*' | tac)
for win in $stack; do
    wdesk=$(xprop -id "$win" _NET_WM_DESKTOP | awk '{print $3}')
    [ "$wdesk" = "$desk" ] || [ "$wdesk" = 4294967295 ] || continue
    xprop -id "$win" _NET_WM_STATE | grep -q HIDDEN && continue
    xprop -id "$win" _NET_WM_WINDOW_TYPE | grep -q -e DESKTOP -e DOCK && continue
    eval "$(xdotool getwindowgeometry --shell "$win")"   # sets X Y WIDTH HEIGHT
    cx=$((X + WIDTH / 2)) cy=$((Y + HEIGHT / 2))
    if (( cx >= x && cx < x + w && cy >= y && cy < y + h )); then
        xdotool windowactivate "$win" 2>/dev/null
        break
    fi
done

xdotool mousemove $((x + w / 2)) $((y + h / 2))
