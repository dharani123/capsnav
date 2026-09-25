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

## Files
- `default.conf`: the keyd config. The live copy is `/etc/keyd/default.conf`.
- `keyd-src/`: keyd source used for the install.
- `install.sh`: builds and installs keyd, copies the config, and starts the service.

## Common tasks
- Apply config edits: `sudo cp default.conf /etc/keyd/default.conf && sudo keyd reload`
- Uninstall: `sudo systemctl disable --now keyd && sudo make -C keyd-src uninstall`
- If the keyboard locks up: press Backspace+Escape+Enter together to stop keyd.

## keyd version
`keyd-src/` is vendored from https://github.com/rvaiya/keyd at commit
`f564288ac2b19d2305a5b39023c474805ff8fce5` (v2.6.0, MIT license).
