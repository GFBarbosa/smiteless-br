#!/usr/bin/env python3
"""smiteconfig.py - tiny shared settings store for Smiteless.

Settings live in ~/.claude/smiteless_settings.json (gank/scout tuning, read live by the
overlay and edited by smitesettings.py). Auto-open is a marker file (so it can be toggled
without parsing JSON), and "start with Windows" is a registry Run key.
"""
import os, sys, json

PATH = os.path.expanduser("~/.claude/smiteless_settings.json")


# ---------- tie every surface's lifetime to the tray (no orphan windows on force-close) ----------
# The tray (AHK or pystray) holds the "Global\SmitelessTray" mutex for its whole life. Each
# surface polls it: seen-alive-then-gone => the tray was force-closed/crashed => close myself.
_TRAY_MUTEX = "Global\\SmitelessTray"
_tray_seen = [False]


def _tray_alive():
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenMutexW(0x00100000, False, _TRAY_MUTEX)     # SYNCHRONIZE
        if h:
            k.CloseHandle(h)                                 # never RETAIN it (that'd keep it alive)
            return True
    except Exception:
        return True                                          # can't tell -> never false-kill a window
    return False


def tray_gone():
    """True only once the tray has been seen alive and has since vanished. Always False when
    there was never a tray (a surface launched standalone in dev), so `python ui/x.py` still runs."""
    if _tray_alive():
        _tray_seen[0] = True
        return False
    return _tray_seen[0]


def watch_tray(root, interval=700):
    """Tk helper: self-close `root` within ~<1s of the Smiteless tray going away, so no
    overlay/widget is left orphaned when you force-close Smiteless. Call once after the window
    is built. Snappy and cheap (a single OpenMutex probe per tick)."""
    def tick():
        if tray_gone():
            try:
                root.destroy()
            except Exception:
                pass
            return
        try:
            root.after(interval, tick)
        except Exception:
            pass
    tray_gone()                                              # latch 'seen' now — tray is up at spawn
    try:
        root.after(interval, tick)
    except Exception:
        pass
NOAUTO = os.path.expanduser("~/.claude/smiteless_noautoopen")   # presence = auto-open OFF
NOHOME = os.path.expanduser("~/.claude/smiteless_nohomeonstart")  # presence = open profile/home at startup OFF
HERE = os.path.dirname(os.path.abspath(__file__))

SWAP_ROLES = ("top", "jungle", "mid", "adc", "support")   # valid targets for auto-accept role swap
# auto_pick_swap: "" off / "any" accept-all / "first" / "last" / a specific pick slot "1".."5".
PICK_SWAP_VALUES = ("any", "first", "last", "1", "2", "3", "4", "5")

# streak_influence: 0..100, 50 = the original/default behavior (a multiplier m = value/50
#   scales the enemy form weight, the streak compounding, and the extreme override).
# gank_threshold: |score| cut for GANK / TOUGH (lower = more lanes tagged).
# scout_games: recent ranked games pulled per player.
DEFAULTS = {"streak_influence": 50, "gank_threshold": 6.0, "scout_games": 10, "profile_games": 30,
            "dragon_volume": 30, "board_size": 70}
RANGES = {"streak_influence": (0, 100), "gank_threshold": (3.0, 12.0), "scout_games": (5, 20),
          "profile_games": (5, 60), "dragon_volume": (0, 100), "board_size": (40, 100)}
# Feature toggles (read live by the relevant module).
BOOLS = {"matchup_tips": True,    # generate the AI lane tip in champ-select/in-game
         "gank_kit": True,        # factor YOUR champ's CC/engage into the gank ratings
         "duo_detection": True,   # show the duo / premade markers
         "item_widget": True,     # the floating in-game item helper
         "game_intel": True,      # widget: live win read + objective timers + spike alerts
         "tempo_coach": True,     # widget: TEMPO engine — objective-setup directives (farm/base/move/take-give)
         "free_alarm": True,      # widget: FREE — alarm when the enemy jungler provably can't contest an objective
         "tempo_voice": True,     # widget: spoken TEMPO callouts (Windows TTS: "Base now", "Take it", ...)
         "dragon_audio": True,    # widget: audio beeps 45/30/15s before a drake spawns
         "ghost_race": True,      # widget: GHOST — live pace race vs your best game on this champ
         "respawn_plan": True,    # widget: RESPAWN — death screen becomes countdown + comeback plan
         "death_brief": True,     # fullscreen see-through DEATH BRIEF overlay while you're dead
         "loading_overlay": False,  # RETIRED — folded into DraftBoard's live scout (shared web
                                    #   page). Default off; no launcher spawns it. On = deliberately
                                    #   revive the native on-monitor loading overlay. (Replaces the
                                    #   old `loading_brief` key, which is now ignored.)
         "dodge_alerts": True,    # champ select: high-confidence "consider dodging" banner
         "dock_champ_select": True,  # champ select helper docks as a tall panel LEFT of the client
         "board_topmost": True,   # live board/scoreboard stays above other windows (untick to allow covering)
         "auto_import": False,    # import runes+summs AUTOMATICALLY when you lock a champ
         "auto_ban": False,       # champ select: auto-lock the top recommended ban on your ban turn
         "auto_accept": False,    # auto-accept queue ready checks
         "flash_on_d": True,      # import puts Flash on D (off = put Flash on F)
         "solo_coaching": True,   # profile/climb/session coaching from RANKED SOLO games only
         "draft_link": True,      # champ select: publish the live draft board + post the link in chat
         "draft_autoopen": True,  # champ select: also OPEN the draft board in your own browser
         "legend_seen": False}    # widget: LEGEND card already auto-opened once (state, not a toggle)

# Free-text settings (trimmed strings, no validation beyond str()).
# draft_db: the user's own Firebase RTDB url ('' = draft link feature dormant); see docs/DRAFTLINK.md.
# draft_page: where the static draft board is hosted (GitHub Pages serves /docs on main).
# draft_msg: the champ-select chat line the link is posted with ('' = the branded default).
STRINGS = {"draft_db": "",
           "draft_page": "https://bobbyroylee.github.io/smiteless/draft/",
           "draft_msg": ""}


def load():
    s = dict(DEFAULTS)
    s.update(BOOLS)
    s.update(STRINGS)
    s["fav_champs"] = []          # ordered favourite picks: ["Kha'Zix", "Ahri, mid", ...]
    s["ban_list"] = ["Shyvana"]   # ordered PERMA-BAN priority: highest still-available gets banned
    s["auto_swap_roles"] = []     # champ select: role (position) swaps to auto-accept INTO
    s["auto_pick_swap"] = ""      # champ select pick order: "" off / "any" / "first" / "last"
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
        for k in STRINGS:
            if k in raw:
                s[k] = str(raw[k]).strip()
        if isinstance(raw.get("fav_champs"), list):
            s["fav_champs"] = [str(x).strip() for x in raw["fav_champs"] if str(x).strip()][:20]
        if isinstance(raw.get("ban_list"), list):
            s["ban_list"] = [str(x).strip() for x in raw["ban_list"] if str(x).strip()][:10]
        if isinstance(raw.get("auto_swap_roles"), list):
            s["auto_swap_roles"] = [r for r in (str(x).strip().lower() for x in raw["auto_swap_roles"])
                                    if r in SWAP_ROLES]
        pk = str(raw.get("auto_pick_swap", "")).strip().lower()
        s["auto_pick_swap"] = pk if pk in PICK_SWAP_VALUES else ""
    except Exception:
        pass
    return s


def save(s):
    # MERGE onto whatever's already on disk: only keys present in `s` are updated, everything
    # else is preserved. Rebuilding from DEFAULTS used to mean a save that didn't carry every
    # key (e.g. a partial update) silently reverted the rest — that's how Flash-on-D kept
    # coming back. Missing-from-both keys fall back to their default.
    try:
        cur = json.load(open(PATH, encoding="utf-8"))
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    clean = dict(cur)
    for k in DEFAULTS:
        if k in s:
            try:
                v = type(DEFAULTS[k])(s[k])
            except Exception:
                v = cur.get(k, DEFAULTS[k])
            lo, hi = RANGES[k]
            clean[k] = min(hi, max(lo, v))
        elif k not in clean:
            clean[k] = DEFAULTS[k]
    for k in BOOLS:
        if k in s:
            clean[k] = bool(s[k])
        elif k not in clean:
            clean[k] = BOOLS[k]
    for k in STRINGS:
        if k in s:
            clean[k] = str(s[k]).strip()
        elif k not in clean:
            clean[k] = STRINGS[k]
    if "fav_champs" in s:
        clean["fav_champs"] = [str(x).strip() for x in (s.get("fav_champs") or []) if str(x).strip()][:20]
    elif "fav_champs" not in clean:
        clean["fav_champs"] = []
    if "ban_list" in s:
        clean["ban_list"] = [str(x).strip() for x in (s.get("ban_list") or []) if str(x).strip()][:10]
    elif "ban_list" not in clean:
        clean["ban_list"] = ["Shyvana"]
    if "auto_swap_roles" in s:
        clean["auto_swap_roles"] = [r for r in (str(x).strip().lower() for x in (s.get("auto_swap_roles") or []))
                                    if r in SWAP_ROLES]
    elif "auto_swap_roles" not in clean:
        clean["auto_swap_roles"] = []
    if "auto_pick_swap" in s:
        pk = str(s.get("auto_pick_swap", "")).strip().lower()
        clean["auto_pick_swap"] = pk if pk in PICK_SWAP_VALUES else ""
    elif "auto_pick_swap" not in clean:
        clean["auto_pick_swap"] = ""
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
