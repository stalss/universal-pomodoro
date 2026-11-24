# Universal Pomodoro for Linux

A standalone, distro-agnostic Pomodoro timer. **No Omarchy, Quickshell,
GNOME or KDE dependency** — just Python 3 and the standard library. It runs as
a background daemon on any Linux system and sends desktop notifications via
`notify-send` where available.

This is the portable sibling of the Omarchy shell-bar widget in the parent
directory. It keeps the same enforced rules:

- Focus session **minimum 30 minutes**
- Short / long breaks **maximum 15 minutes**
- Sessions to unblock **minimum 2**

## Requirements

- Linux with Python **3.9+**
- `notify-send` for desktop popups (optional — notifications also print to stdout)
- `systemd --user` for auto-start (optional — you can run the daemon manually)
- A shell command of your choice if you want the "restriction-free" reward

Works on Arch, Fedora, Ubuntu/Debian, openSUSE, Elementary, Pop!_OS, and
others. On non-systemd distros (Alpine, Gentoo, Void) use the manual daemon
option below.

## Install — from clone to running

### 1. Clone

```bash
git clone https://github.com/stalss/universal-pomodoro.git
cd universal-pomodoro
```

### 2. Run the installer

```bash
chmod +x install.sh
./install.sh
```

No root needed. This installs:

- `pomodoro` and `daily-screen-limit` into `~/.local/bin` (or `$XDG_BIN_HOME`)
- systemd user units into `~/.config/systemd/user` (if `systemd --user` works)
- enables `pomodoro.service` and `daily-screen-limit.timer`

If `systemd --user` isn't available, the installer prints manual commands:

```bash
nohup pomodoro daemon >/dev/null 2>&1 &
```

### 3. Verify

```bash
pomodoro status
```

You should see something like:

```
Focus 30:00 (paused) · 0 focus sessions today · 2 more to unblock sites
```

## Desktop / distro notes

| Environment | What you need |
|---|---|
| **GNOME / KDE / XFCE / LXQt** | `notify-send` is already available — nothing extra |
| **i3 / sway / Hyprland / awesome** | Install `libnotify` (`notify-send`) and run a notification daemon such as `dunst` |
| **Headless / server** | No setup needed; notifications print to the terminal |
| **Arch / Manjaro** | `sudo pacman -S libnotify` (and `dunst` if no daemon) |
| **Fedora** | `sudo dnf install libnotify dunst` |
| **Ubuntu / Debian** | `sudo apt install libnotify-bin dunst` |
| **Alpine / Void (no systemd)** | Skip service install; run `pomodoro daemon` manually or from cron |

## Usage

```bash
pomodoro start      # start or resume
pomodoro pause      # pause
pomodoro reset      # reset current phase
pomodoro skip       # next phase (does not count a session)
pomodoro finish     # force-complete current focus (counts + rewards)
pomodoro status     # human readable
pomodoro status --json
```

Keybind them in your window manager, or call them from a shell script / panel
button. Example sway/hyprland binding:

```conf
bind = $mainMod, P, exec, pomodoro toggle   # see note below
```

(There is no `toggle` subcommand — use a small shell wrapper:

```bash
pomodoro status --json | grep -q '"running": true' && pomodoro pause || pomodoro start
```
)

## Configuration

Settings live in `~/.config/pomodoro/config.json` (respects `XDG_CONFIG_HOME`).

```bash
pomodoro config                      # show all
pomodoro config work_minutes 45      # set one (clamped to >= 30)
pomodoro config reward_sessions 3
```

| Key | Default | Enforced |
|---|---|---|
| `work_minutes` | 30 | min 30 |
| `break_minutes` | 5 | max 15 |
| `long_break_minutes` | 15 | max 15 |
| `sessions_before_long` | 4 | 1–12 |
| `auto_start_breaks` | `true` | bool |
| `auto_start_focus` | `false` | bool |
| `reward_sessions` | 2 | min 2 |
| `reward_minutes` | 120 | 5–480 |
| `reward_command` | `""` | shell command, `{minutes}` placeholder |
| `restore_command` | `""` | shell command |
| `daily_limit_minutes` | 360 | 5–360 |

Invalid values are clamped on write, so you cannot set a focus session below
30 minutes or a break above 15.

## Restriction-free reward (optional)

Every `reward_sessions`-th completed focus session runs `reward_command`.
`{minutes}` is replaced with `reward_minutes`. Examples:

```bash
# site-blocker (setup included in site-blocker/)
pomodoro config reward_command 'sudo -n /usr/local/bin/site-blocker pause {minutes}'
pomodoro config restore_command 'sudo -n /usr/local/bin/site-blocker resume'

# Or anything else: a firewall rule, a script, a reminder...
pomodoro config reward_command '~/bin/unblock-distractions {minutes}'
```

If you use site-blocker, install it first or the reward command will fail:

```bash
cd site-blocker
chmod +x install-site-blocker.sh
sudo ./install-site-blocker.sh "$USER"
```

See [`site-blocker/README.md`](site-blocker/README.md) for requirements
(NetworkManager + dnsmasq, passwordless sudo) and verification steps.

Leave both commands empty (the default) to disable the reward entirely — the
timer still counts sessions and shows progress.

You can also grant or end a window manually:

```bash
pomodoro reward
pomodoro restore
```

## Daily screen-time counter (optional)

The included `daily-screen-limit` script counts unlocked desktop time via
`loginctl` (systemd-logind, present on most modern distros), warns 15 minutes
before the configured `daily_limit_minutes`, and ends the session when reached.
It reads the same limit from `~/.config/omarchy/shell.json` if present, falling
back to 180 minutes. On non-systemd systems it safely skips counting.

Check it with:

```bash
daily-screen-limit --status
```

## Files and paths

| Purpose | Path |
|---|---|
| Config | `$XDG_CONFIG_HOME/pomodoro/config.json` (default `~/.config/pomodoro/`) |
| State / PID | `$XDG_STATE_HOME/pomodoro/` (default `~/.local/state/pomodoro/`) |
| Binary | `~/.local/bin/pomodoro` |

## Difference from the Omarchy widget

The parent directory contains a Quickshell/QML widget that lives in the
Omarchy bar and reads `~/.config/omarchy/shell.json`. This `universal/`
version is a standalone daemon with its own config file and CLI. Both enforce
the same bounds; use whichever fits your desktop.
