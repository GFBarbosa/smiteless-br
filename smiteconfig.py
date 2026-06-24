#!/usr/bin/env python3
"""smiteconfig.py - tiny shared settings store for Smiteless.

Settings live in ~/.claude/smiteless_settings.json (gank/scout tuning, read live by the
overlay and edited by smitesettings.py). Auto-open is a marker file so the AutoHotkey
tray can toggle it without parsing JSON.
"""
import os, json

PATH = os.path.expanduser("~/.claude/smiteless_settings.json")
NOAUTO = os.path.expanduser("~/.claude/smiteless_noautoopen")   # presence = auto-open OFF

# streak_influence: 0..100, 50 = the original/default behavior (a multiplier m = value/50
#   scales the enemy form weight, the streak compounding, and the extreme override).
# gank_threshold: |score| cut for GANK / TOUGH (lower = more lanes tagged).
# scout_games: recent ranked games pulled per player.
DEFAULTS = {"streak_influence": 50, "gank_threshold": 6.0, "scout_games": 10}
RANGES = {"streak_influence": (0, 100), "gank_threshold": (3.0, 12.0), "scout_games": (5, 20)}


def load():
    s = dict(DEFAULTS)
    try:
        raw = json.load(open(PATH, encoding="utf-8"))
        for k in DEFAULTS:
            if k in raw:
                v = type(DEFAULTS[k])(raw[k])
                lo, hi = RANGES[k]
                s[k] = min(hi, max(lo, v))
    except Exception:
        pass
    return s


def save(s):
    clean = {}
    for k in DEFAULTS:
        try:
            v = type(DEFAULTS[k])(s.get(k, DEFAULTS[k]))
        except Exception:
            v = DEFAULTS[k]
        lo, hi = RANGES[k]
        clean[k] = min(hi, max(lo, v))
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = f"{PATH}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
        os.replace(tmp, PATH)
    except Exception:
        pass
    return clean


def auto_open_enabled():
    return not os.path.exists(NOAUTO)


def set_auto_open(on):
    try:
        if on:
            if os.path.exists(NOAUTO):
                os.remove(NOAUTO)
        else:
            open(NOAUTO, "w").close()
    except Exception:
        pass
