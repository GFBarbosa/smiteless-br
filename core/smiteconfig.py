#!/usr/bin/env python3
"""smiteconfig.py - tiny shared settings store for Smiteless.

Settings live in ~/.claude/smiteless_settings.json (gank/scout tuning, read live by the
overlay and edited by smitesettings.py). Auto-open is a marker file (so it can be toggled
without parsing JSON), and "start with Windows" is a registry Run key.
"""
import os, sys, json

PATH = os.path.expanduser("~/.claude/smiteless_settings.json")
NOAUTO = os.path.expanduser("~/.claude/smiteless_noautoopen")   # presence = auto-open OFF
NOHOME = os.path.expanduser("~/.claude/smiteless_nohomeonstart")  # presence = open profile/home at startup OFF
HERE = os.path.dirname(os.path.abspath(__file__))

# streak_influence: 0..100, 50 = the original/default behavior (a multiplier m = value/50
#   scales the enemy form weight, the streak compounding, and the extreme override).
# gank_threshold: |score| cut for GANK / TOUGH (lower = more lanes tagged).
# scout_games: recent ranked games pulled per player.
DEFAULTS = {"streak_influence": 50, "gank_threshold": 6.0, "scout_games": 10, "profile_games": 30,
            "dragon_volume": 30}
RANGES = {"streak_influence": (0, 100), "gank_threshold": (3.0, 12.0), "scout_games": (5, 20),
          "profile_games": (5, 60), "dragon_volume": (0, 100)}
# Feature toggles (read live by the relevant module).
BOOLS = {"matchup_tips": True,    # generate the AI lane tip in champ-select/in-game
         "gank_kit": True,        # factor YOUR champ's CC/engage into the gank ratings
         "duo_detection": True,   # show the duo / premade markers
         "item_widget": True,     # the floating in-game item helper
         "game_intel": True,      # widget: live win read + objective timers + spike alerts
         "dragon_audio": True,    # widget: audio beeps 45/30/15s before a drake spawns
         "dodge_alerts": True,    # champ select: high-confidence "consider dodging" banner
         "dock_champ_select": True,  # champ select helper docks as a tall panel LEFT of the client
         "auto_accept": False,    # auto-accept queue ready checks
         "flash_on_d": True}      # import puts Flash on D (off = put Flash on F)


def load():
    s = dict(DEFAULTS)
    s.update(BOOLS)
    try:
        raw = json.load(open(PATH, encoding="utf-8"))
        for k in DEFAULTS:
            if k in raw:
                v = type(DEFAULTS[k])(raw[k])
                lo, hi = RANGES[k]
                s[k] = min(hi, max(lo, v))
        for k in BOOLS:
            if k in raw:
                s[k] = bool(raw[k])
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
    for k in BOOLS:
        clean[k] = bool(s.get(k, BOOLS[k]))
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


def home_on_start_enabled():
    return not os.path.exists(NOHOME)


def set_home_on_start(on):
    try:
        if on:
            if os.path.exists(NOHOME):
                os.remove(NOHOME)
        else:
            open(NOHOME, "w").close()
    except Exception:
        pass


# ---------- start with Windows (registry Run key) ----------
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP = "Smiteless"


def autostart_command():
    """The command Windows runs at login. Prefer the AutoHotkey tray (the reliable shell);
    fall back to the pure-Python tray if AutoHotkey isn't installed."""
    ahk = os.path.expanduser(r"~/AppData/Local/Programs/AutoHotkey/v2/AutoHotkey64.exe")
    ahk_script = os.path.join(HERE, "smiteless.ahk")
    if os.path.exists(ahk) and os.path.exists(ahk_script):
        return f'"{ahk}" "{ahk_script}"'
    pyw = sys.executable
    cand = os.path.join(os.path.dirname(pyw), "pythonw.exe")
    if os.path.exists(cand):
        pyw = cand
    return f'"{pyw}" "{os.path.join(HERE, "smiteless_tray.py")}"'


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _APP)
        return True
    except Exception:
        return False


def set_autostart(on):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, _APP, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, _APP)
                except FileNotFoundError:
                    pass
    except Exception:
        pass
