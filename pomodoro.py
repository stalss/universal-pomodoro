#!/usr/bin/env python3
"""Universal Pomodoro timer for Linux.

No Omarchy, Quickshell, GNOME or KDE dependency — Python 3 standard library
only. Works on any Linux desktop that has notify-send (optional) and, for the
background daemon, either systemd --user or a plain shell background job.

Commands:
    start       start / resume the current phase
    pause       pause the current phase
    reset       reset the current phase to full length
    skip        move to the next phase without counting a focus session
    finish      force-complete the current focus session (counts + rewards)
    status      print the current state (add --json for machine-readable)
    daemon      run the ticking engine (normally managed by systemd)
    config      show the effective config, or set a key: config <key> <value>
    reward      grant the unblock reward manually
    restore     run the restore command manually

All paths honour XDG_CONFIG_HOME / XDG_STATE_HOME and fall back to the usual
~/.config and ~/.local/state. Enforced bounds match the Omarchy widget:
focus >= 30 min, breaks <= 15 min, sessions-to-unblock >= 2.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Any

APP = "pomodoro"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
CONFIG_FILE = CONFIG_HOME / APP / "config.json"
STATE_FILE = STATE_HOME / APP / "state.json"
PID_FILE = STATE_HOME / APP / "daemon.pid"

DEFAULTS: dict[str, Any] = {
    "work_minutes": 30,
    "break_minutes": 5,
    "long_break_minutes": 15,
    "sessions_before_long": 4,
    "auto_start_breaks": True,
    "auto_start_focus": False,
    "reward_sessions": 2,
    "reward_minutes": 120,
    # Shell commands for the "restriction free" window. {minutes} is replaced.
    # Leave empty to disable the reward integration.
    "reward_command": "",
    "restore_command": "",
    "daily_limit_minutes": 360,
}

PHASES = ("focus", "short", "long")


# --------------------------------------------------------------------------- helpers

def clamp_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a config with every value validated and within enforced bounds."""
    cfg = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in raw:
            cfg[key] = raw[key]

    def integer(key: str, minimum: int, maximum: int | None = None) -> int:
        try:
            value = int(cfg[key])
        except (TypeError, ValueError):
            value = int(DEFAULTS[key])
        if maximum is not None:
            value = min(maximum, value)
        return max(minimum, value)

    cfg["work_minutes"] = integer("work_minutes", 30)
    cfg["break_minutes"] = integer("break_minutes", 1, 15)
    cfg["long_break_minutes"] = integer("long_break_minutes", 1, 15)
    cfg["sessions_before_long"] = integer("sessions_before_long", 1, 12)
    cfg["reward_sessions"] = integer("reward_sessions", 2)
    cfg["reward_minutes"] = integer("reward_minutes", 5, 480)
    cfg["daily_limit_minutes"] = integer("daily_limit_minutes", 5, 360)
    for key in ("auto_start_breaks", "auto_start_focus"):
        cfg[key] = cfg[key] is True or cfg[key] == "true"
    for key in ("reward_command", "restore_command"):
        cfg[key] = str(cfg[key] or "")
    return cfg


def load_config() -> dict[str, Any]:
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    cfg = clamp_config(raw)
    if cfg != raw:
        save_config(cfg)  # normalise invalid values in place
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def today() -> str:
    return date.today().isoformat()


def fresh_state() -> dict[str, Any]:
    return {
        "date": today(),
        "phase": "focus",
        "remaining": DEFAULTS["work_minutes"] * 60,
        "running": False,
        "end_at": 0,
        "cycle": 0,
        "daily_completed": 0,
        "reward_until": 0,
    }


def load_state(cfg: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError):
        return fresh_state()

    state = fresh_state()
    state.update({k: v for k, v in data.items() if k in state})

    # A new day clears the daily reward count but keeps the current phase.
    if state.get("date") != today():
        state["date"] = today()
        state["daily_completed"] = 0

    if state.get("phase") not in PHASES:
        state["phase"] = "focus"
    if state.get("running") and not isinstance(state.get("end_at"), (int, float)):
        state["running"] = False

    # Re-derive the phase length when settings changed while idle/paused.
    if not state["running"]:
        state["remaining"] = phase_seconds(state["phase"], cfg)
    else:
        state["remaining"] = max(0, math.ceil((state["end_at"] - time.time())))
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


def phase_seconds(phase: str, cfg: dict[str, Any]) -> int:
    if phase == "focus":
        return cfg["work_minutes"] * 60
    if phase == "long":
        return cfg["long_break_minutes"] * 60
    return cfg["break_minutes"] * 60


def phase_label(phase: str) -> str:
    return {"focus": "Focus", "short": "Break", "long": "Long break"}[phase]


def clock(seconds: int | float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def notify(title: str, message: str) -> None:
    """Desktop notification; silently no-op where notify-send is absent."""
    try:
        subprocess.run(
            ["notify-send", "-a", APP, title, message],
            check=False, capture_output=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    print(f"[{title}] {message}", flush=True)


def run_hook(command: str) -> bool:
    if not command:
        return True
    try:
        return subprocess.run(
            command, shell=True, check=False, timeout=30,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def reward_command(cfg: dict[str, Any]) -> str:
    return cfg["reward_command"].replace("{minutes}", str(cfg["reward_minutes"]))


def grant_reward(cfg: dict[str, Any], state: dict[str, Any]) -> None:
    cmd = reward_command(cfg)
    if not cmd:
        return
    if run_hook(cmd):
        state["reward_until"] = int(time.time()) + cfg["reward_minutes"] * 60
        notify(
            "Focus reward: sites unblocked",
            f"{state['daily_completed']} focus sessions today. "
            f"Blocking is lifted for {cfg['reward_minutes']} minutes.",
        )
    else:
        notify("Focus reward failed", f"Command failed: {cmd}")


# --------------------------------------------------------------------------- engine

def advance(state: dict[str, Any], cfg: dict[str, Any], *, count: bool) -> None:
    """Move to the next phase. count=True means a focus session was completed."""
    if state["phase"] == "focus":
        if count:
            state["cycle"] += 1
            state["daily_completed"] += 1
            long_break = state["cycle"] % cfg["sessions_before_long"] == 0
            if state["daily_completed"] % cfg["reward_sessions"] == 0:
                grant_reward(cfg, state)
        else:
            long_break = False
        state["phase"] = "long" if long_break else "short"
        notify(
            "Focus complete: long break" if long_break else "Focus complete: break time",
            f"Step away for {phase_seconds(state['phase'], cfg) // 60} minutes.",
        )
        autostart = cfg["auto_start_breaks"]
    else:
        state["phase"] = "focus"
        notify("Break over", f"Ready for the next {cfg['work_minutes']}-minute focus session.")
        autostart = cfg["auto_start_focus"]

    state["remaining"] = phase_seconds(state["phase"], cfg)
    state["running"] = False
    state["end_at"] = 0
    if autostart:
        state["running"] = True
        state["end_at"] = time.time() + state["remaining"]


def tick(state: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Process one tick. Returns True if the state changed."""
    changed = False
    if state["date"] != today():
        state["date"] = today()
        state["daily_completed"] = 0
        changed = True

    if state["running"] and state["end_at"] and time.time() >= state["end_at"]:
        advance(state, cfg, count=True)
        changed = True
    elif state["running"]:
        left = math.ceil(state["end_at"] - time.time())
        if left != state["remaining"]:
            state["remaining"] = left
            changed = True

    if state["reward_until"] and time.time() >= state["reward_until"]:
        state["reward_until"] = 0
        changed = True
    return changed


def daemon() -> int:
    cfg = load_config()
    state = load_state(cfg)
    save_state(state)
    print(f"{APP} daemon started (pid {os.getpid()})", flush=True)

    def stop(_signum: int, _frame: Any) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while True:
        before = json.dumps(state, sort_keys=True)
        if tick(state, cfg):
            save_state(state)
        if json.dumps(state, sort_keys=True) != before:
            save_state(state)
        time.sleep(0.5)


# --------------------------------------------------------------------------- CLI

def cmd_start(cfg: dict[str, Any]) -> None:
    state = load_state(cfg)
    if not state["running"]:
        if state["remaining"] <= 0:
            state["remaining"] = phase_seconds(state["phase"], cfg)
        state["end_at"] = time.time() + state["remaining"]
        state["running"] = True
        save_state(state)
    status(cfg)


def cmd_pause(cfg: dict[str, Any]) -> None:
    state = load_state(cfg)
    if state["running"]:
        # Deadline may have passed between daemon ticks; complete the session
        # instead of leaving it stuck paused at 00:00.
        if state["end_at"] and time.time() >= state["end_at"]:
            advance(state, cfg, count=True)
        else:
            state["remaining"] = max(0, math.ceil(state["end_at"] - time.time()))
            state["running"] = False
            state["end_at"] = 0
        save_state(state)
    status(cfg)


def cmd_reset(cfg: dict[str, Any]) -> None:
    state = load_state(cfg)
    state["running"] = False
    state["end_at"] = 0
    state["remaining"] = phase_seconds(state["phase"], cfg)
    save_state(state)
    status(cfg)


def cmd_skip(cfg: dict[str, Any]) -> None:
    state = load_state(cfg)
    advance(state, cfg, count=False)
    save_state(state)
    status(cfg)


def cmd_finish(cfg: dict[str, Any]) -> None:
    state = load_state(cfg)
    advance(state, cfg, count=True)
    save_state(state)
    status(cfg)


def status(cfg: dict[str, Any], as_json: bool = False) -> None:
    state = load_state(cfg)
    if state["running"]:
        left = math.ceil(state["end_at"] - time.time())
        state["remaining"] = max(0, left)
    unblocked = max(0, state["reward_until"] - int(time.time()))
    info = {
        "phase": state["phase"],
        "label": phase_label(state["phase"]),
        "remaining": state["remaining"],
        "clock": clock(state["remaining"]),
        "running": state["running"],
        "daily_completed": state["daily_completed"],
        "sessions_to_reward": cfg["reward_sessions"]
        - (state["daily_completed"] % cfg["reward_sessions"]),
        "unblocked_seconds": unblocked,
    }
    if as_json:
        print(json.dumps(info))
        return
    line = (
        f"{info['label']} {info['clock']} "
        f"({'running' if info['running'] else 'paused'}) · "
        f"{info['daily_completed']} focus sessions today"
    )
    if unblocked:
        line += f" · sites unblocked, {clock(unblocked)} left"
    else:
        line += f" · {info['sessions_to_reward']} more to unblock sites"
    print(line)


def cmd_config(argv: list[str]) -> None:
    cfg = load_config()
    if not argv:
        print(json.dumps(cfg, indent=2))
        return
    key, value = argv[0], " ".join(argv[1:])
    if key not in DEFAULTS:
        print(f"Unknown key: {key}", file=sys.stderr)
        print("Keys: " + ", ".join(DEFAULTS), file=sys.stderr)
        raise SystemExit(2)
    if not value:
        print(f"{key} = {cfg[key]!r}")
        return
    raw = dict(cfg)
    if isinstance(DEFAULTS[key], bool):
        raw[key] = value.lower() in ("1", "true", "yes", "on")
    elif isinstance(DEFAULTS[key], int):
        try:
            raw[key] = int(value)
        except ValueError:
            print(f"{key} must be a number", file=sys.stderr)
            raise SystemExit(2)
    else:
        raw[key] = value
    cfg = clamp_config(raw)
    save_config(cfg)
    print(f"{key} = {cfg[key]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    for name in ("start", "pause", "reset", "skip", "finish", "daemon"):
        sub.add_parser(name)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    sub.add_parser("config")
    sub.add_parser("reward")
    sub.add_parser("restore")
    args, extra = parser.parse_known_args()

    command = args.command or "status"
    if command == "daemon":
        return daemon()

    cfg = load_config()
    if command == "start":
        cmd_start(cfg)
    elif command == "pause":
        cmd_pause(cfg)
    elif command == "reset":
        cmd_reset(cfg)
    elif command == "skip":
        cmd_skip(cfg)
    elif command == "finish":
        cmd_finish(cfg)
    elif command == "status":
        status(cfg, getattr(args, "json", False))
    elif command == "config":
        cmd_config(extra)
    elif command == "reward":
        state = load_state(cfg)
        grant_reward(cfg, state)
        save_state(state)
    elif command == "restore":
        ok = run_hook(cfg["restore_command"])
        notify("Site blocking", "Restored." if ok else "Restore command failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
