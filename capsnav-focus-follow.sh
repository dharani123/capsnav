#!/usr/bin/env bash
# Pointer follows keyboard focus: when another window becomes active (Caps+b,
# a new window or dialog, closing a window) and the pointer isn't already
# inside it, move the pointer to the window's centre. Clicking a window never
# moves the pointer, since it's already inside. X11 only; runs as the user
# service capsnav-focus-follow.
# stdbuf: xprop block-buffers into a pipe, which would delay every event.
# The first line is the current value at startup, not a change, so skip it.
first=1
stdbuf -oL xprop -spy -root _NET_ACTIVE_WINDOW | while read -r line; do
    win=${line##* }
    if [ -n "$first" ]; then first=; continue; fi
    [ "$win" = 0x0 ] && continue
    geo=$(xdotool getwindowgeometry --shell "$win" 2>/dev/null) || continue
    eval "$geo"   # X Y WIDTH HEIGHT of the window
    wx=$X wy=$Y
    eval "$(xdotool getmouselocation --shell)"   # X Y of the pointer
    if (( X < wx || X >= wx + WIDTH || Y < wy || Y >= wy + HEIGHT )); then
        xdotool mousemove $((wx + WIDTH / 2)) $((wy + HEIGHT / 2))
    fi
done
