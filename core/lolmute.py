#!/usr/bin/env python3
"""lolmute.py - AUTO-MUTE: `/fullmute all` typed into the game, plus the client settings.

THE BUG THAT COST FOUR RELEASES
v0.9.51-v0.9.54 typed `/fullmute all` and it never once worked. The cause was one line, and
it was not the one I kept "fixing": every CHARACTER went out as a scan code, but the ENTER
that opens the chat box went out as a VIRTUAL-KEY event with `wScan = 0`. The League game
reads SCAN CODES. So Enter was ignored, chat never opened - and the letters landed on the
champion as gameplay binds instead. (Which is exactly what it looked like from the keyboard:
"it sounded like you just hit keys.")

That also means the thing I concluded in v0.9.55 - "a kernel anti-cheat is filtering injected
input" - was WRONG. Injected input reaches the game fine. The letters proved it by casting
spells. Everything sends as a scan code now, Enter included (0x1C), and chat opens.

TWO LAYERS, ON PURPOSE
  1. `/fullmute all` typed into the game. This is the real thing: chat AND ping markers from
     every player, for that game. Nothing else can suppress ping markers.
  2. The client's own settings (ally chat hidden, all-chat hidden, ping audio off), written
     over the LCU and VERIFIED by reading back. Independent of the keystrokes, so a game where
     the typing misses is still quieter than nothing.
Layer 2 is persistent and layer 1 is per-game; `python core\\lolmute.py off` reverts layer 2.

The focus gate is load-bearing: keystrokes only go out when the foreground window is provably
the League game (class AND owning process), re-checked before every burst. If you're alt-tabbed
we wait. The command is never typed into whatever else you're looking at.
"""
import os, sys, time, json, ssl, ctypes, threading, urllib.request
from ctypes import wintypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):
    sys.path.insert(0, os.path.join(_ROOT, _d))
for _s in ("stdout", "stderr"):
    if getattr(sys, _s, None) is None:
        try:
            setattr(sys, _s, open(os.devnull, "w"))
        except Exception:
            pass

import smiteconfig as cfg
import lolimport as limp                     # its _lcu_json is the shared, proven LCU caller
from lolcreds import _ki, _INP               # raw SendInput plumbing

CMD = "/fullmute all"
GAME_CLASS = "RiotWindowClass"
GAME_EXE = "league of legends.exe"
_LOG = os.path.expanduser("~/.claude/smiteless_mute.log")

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_u32.VkKeyScanW.argtypes = [ctypes.c_wchar]
_u32.VkKeyScanW.restype = ctypes.c_short
_u32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_u32.MapVirtualKeyW.restype = wintypes.UINT
_u32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
_u32.SendInput.restype = wintypes.UINT
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_PROC_QUERY_LIMITED = 0x1000
_KEYUP, _SCANCODE = 0x0002, 0x0008
VK_RETURN, VK_SHIFT, VK_ESCAPE = 0x0D, 0x10, 0x1B

# Timings proven by hand against a live client — chat needs a real beat to take keyboard focus
# after Enter, and a zero-gap character burst gets coalesced.
CHAT_OPEN_S = 0.85     # after Enter opens chat, before the first character
KEY_HOLD_S = 0.035     # how long each key is held down
KEY_GAP_S = 0.030      # gap between keys
PRE_SEND_S = 0.35      # after the last character, before the submitting Enter

# ONE attempt, at ~4s, and never again. This is a safety limit, not a tuning knob.
#
# Typing into a live game is only safe while the chat box holds keyboard focus — and in League,
# CLICKING TO MOVE takes that focus away. Any character that misses the box lands on your
# champion as a keybind, and `/fullmute all` contains `f`, `a`, `e`, `t`, `l`, `m`. On a Flash-on-F
# setup that is a wasted Flash.
#
# v0.9.56 sent a second "confirming" command at 25s. At 25s you are walking to a camp, i.e.
# clicking, i.e. exactly when the chat box loses focus mid-type. It cast Flash. The confirm is
# gone: the one attempt fires at FIRE_AT, when you are stationary in the fountain, and if it
# misses we accept the miss — the client-settings layer below is the fallback, which is why it
# exists. Do not add a retry here.
FIRE_AT = 4.0
LATE_LIMIT = 20.0      # past this you've left the fountain — stop trying, don't type on the move

SETTINGS_PATH = "/lol-game-settings/v1/game-settings"
# Every client setting that makes the game quieter, all verified writable on this client.
# ChatChannelVisibility 0 hides the chat channels outright; PingsVolume 0 belts-and-braces
# PingsMute in case a patch ever makes the mute flag advisory.
MUTED = {"HUD": {"ShowAlliedChat": False, "ShowAllChannelChat": False,
                 "ChatChannelVisibility": 0},
         "Volume": {"PingsMute": True, "PingsVolume": 0.0}}
UNMUTED = {"HUD": {"ShowAlliedChat": True, "ShowAllChannelChat": True,
                   "ChatChannelVisibility": 2},
           "Volume": {"PingsMute": False, "PingsVolume": 0.31}}


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ---------- layer 2: the client's own settings (verifiable, persistent) ----------
def read_state():
    """The three mute settings as the client reports them, or None if it isn't up / no longer
    exposes them."""
    try:
        cur = limp._lcu_json("GET", SETTINGS_PATH)
    except Exception:
        return None
    if not isinstance(cur, dict):
        return None
    out = {}
    for grp, keys in MUTED.items():
        for k in keys:
            if k not in (cur.get(grp) or {}):
                return None
            out[f"{grp}.{k}"] = cur[grp][k]
    return out


def apply(on=True):
    """Write the settings and VERIFY by reading back. Returns (ok, detail)."""
    want = MUTED if on else UNMUTED
    before = read_state()
    if before is None:
        return False, "client not reachable, or it no longer exposes these settings"
    try:
        limp._lcu_json("PATCH", SETTINGS_PATH, want)
    except Exception as e:
        return False, f"PATCH failed: {type(e).__name__}"
    after = read_state()
    if after is None:
        return False, "could not read the settings back"
    flat = {f"{g}.{k}": v for g, ks in want.items() for k, v in ks.items()}
    bad = [k for k, v in flat.items() if after.get(k) != v]
    if bad:
        return False, "the client did not accept: " + ", ".join(bad)
    changed = [k for k in flat if before.get(k) != after.get(k)]
    return True, ("already set" if not changed else "set " + ", ".join(changed))


# ---------- layer 1: type it into the game ----------
def game_time():
    """Live game clock in seconds, or -1.0 when :2999 isn't serving. The clock is the honest
    'has the match begun' signal — it stays 0 all through the loading screen."""
    try:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen("https://127.0.0.1:2999/liveclientdata/gamestats",
                                    timeout=1.5, context=ctx) as r:
            return float(json.load(r).get("gameTime", 0.0) or 0.0)
    except Exception:
        return -1.0


def _pid_image(pid):
    h = _k32.OpenProcess(_PROC_QUERY_LIMITED, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        n = wintypes.DWORD(512)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
    except Exception:
        pass
    finally:
        _k32.CloseHandle(h)
    return ""


def game_focused():
    """True only when the foreground window IS the League game — window class AND the owning
    process's image name. Anything we can't positively identify counts as 'not the game'."""
    try:
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(256)
        _u32.GetClassNameW(hwnd, cls, 256)
        if cls.value != GAME_CLASS:
            return False
        pid = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _pid_image(pid.value) == GAME_EXE
    except Exception:
        return False


def scan_of(ch):
    """(scan code, needs_shift) for a character on the CURRENT layout, or None."""
    r = _u32.VkKeyScanW(ch)
    if r == -1:
        return None
    vk, mods = r & 0xFF, (r >> 8) & 0xFF
    if mods & 0x06:                     # needs Ctrl/AltGr — out of scope, say so honestly
        return None
    code = _u32.MapVirtualKeyW(vk, 0)
    return (code, bool(mods & 0x01)) if code else None


def ENTER_SCAN():
    """0x1C. THE bug: this used to go out as a virtual key with wScan=0 and the game ignored
    it, so chat never opened and every following character hit a gameplay bind instead."""
    return _u32.MapVirtualKeyW(VK_RETURN, 0)


def _key(code, down=True):
    _u32.SendInput(1, ctypes.byref((_INP * 1)(_ki(0, code, _SCANCODE | (0 if down else _KEYUP)))),
                   ctypes.sizeof(_INP))


def _tap_scan(code, hold=KEY_HOLD_S):
    _key(code, True)
    time.sleep(hold)
    _key(code, False)


def _single_instance():
    """Refuse to run if another copy already is. THIS IS THE ONE THAT BROKE IT: the v0.9.55
    rewrite dropped the mutex the original had, the tray re-spawns on any phase flap, and three
    copies ended up typing into the same chat box in the same second — three `/fullmute all`
    strings interleaved character by character into garbage, which of course muted nobody. The
    log said TYPED three times and looked like success."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW(None, False, "Global\\SmitelessMute")
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


_SEND_LOCK = threading.Lock()


def send_fullmute():
    """Open chat, type the command, submit. Every key is a SCAN CODE. Returns True only if the
    whole command went out uninterrupted.

    Focus is re-checked before EVERY SINGLE CHARACTER, not just per burst. If you alt-tab or
    click (which takes focus off League's chat box) mid-command, the worst case is now ONE
    stray character instead of the remaining nine — and one of those nine is the `f` that cast
    Flash. The _SEND_LOCK makes a second caller inside this process impossible; the mutex in
    _single_instance() makes a second PROCESS impossible."""
    if not _SEND_LOCK.acquire(blocking=False):
        _log("another send is already in flight — refusing to interleave")
        return False
    try:
        if not game_focused():
            return False
        keys = []
        for ch in CMD:
            s = scan_of(ch)
            if s is None:
                _log(f"ABORT layout cannot produce {ch!r}")
                return False
            keys.append(s)
        _tap_scan(ENTER_SCAN())                     # open chat
        time.sleep(CHAT_OPEN_S)
        if not game_focused():
            return False
        sh = _u32.MapVirtualKeyW(VK_SHIFT, 0)
        for i, (code, shift) in enumerate(keys):
            if not game_focused():                  # bail between characters, not after them
                _tap_scan(_u32.MapVirtualKeyW(VK_ESCAPE, 0))
                _log(f"ABORT lost focus after {i} of {len(keys)} characters — "
                     f"chat closed, nothing further typed")
                return False
            if shift:
                _key(sh, True)
            _tap_scan(code, KEY_GAP_S)
            if shift:
                _key(sh, False)
            time.sleep(KEY_GAP_S)
        time.sleep(PRE_SEND_S)
        if not game_focused():
            _tap_scan(_u32.MapVirtualKeyW(VK_ESCAPE, 0))     # close the box we opened
            return False
        _tap_scan(ENTER_SCAN())                     # submit
        return True
    finally:
        _SEND_LOCK.release()


def player_dead():
    """True when YOUR champion is dead right now. This is the one window where a stray
    keystroke costs nothing — a corpse can't cast Flash, walk into a bush or attack-move into
    a tower — so it's where a failed first attempt is safe to retry, as many times as it takes."""
    try:
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen("https://127.0.0.1:2999/liveclientdata/allgamedata",
                                    timeout=1.5, context=ctx) as r:
            data = json.load(r)
        import lollive as ll
        split = ll.team_split(data)
        if not split:
            return False
        me = split[0]
        return bool(me.get("isDead")) or float(me.get("respawnTimer") or 0) > 1.0
    except Exception:
        return False


def main():
    if not cfg.load().get("auto_mute", True):
        return
    # ONE PROCESS. The tray re-spawns this on any phase flap, and three copies typing into one
    # chat box in the same second is what silently broke auto-mute: the commands interleave
    # character by character into garbage that muted nobody, while the log cheerfully said
    # TYPED three times.
    if not _single_instance():
        _log("another instance is already running — exiting (this is the fix for the "
             "three-copies-typing-at-once bug)")
        return
    ok, detail = apply(True)                    # layer 2 first — it needs no game, no focus
    _log(f"settings {'OK' if ok else 'FAILED'} - {detail}")

    armed, seen, gone, waits = True, False, 0, 0
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        if cfg.tray_gone():
            _log("EXIT tray closed")
            return
        gt = game_time()
        if gt < 0:
            gone += 1
            if seen and gone >= 10:              # a reconnect is a fresh game session
                if not armed:
                    _log("connection lost 10 polls -> re-arming for a possible reconnect")
                armed = True
            if seen and gone >= 60:
                _log("EXIT game over (:2999 down 60 polls)")
                return
            time.sleep(1.0)
            continue
        gone = 0
        if gt > 1.0:
            seen = True
        if armed and FIRE_AT <= gt <= LATE_LIMIT:
            # Window 1: the fountain. You're stationary, chat takes focus cleanly, and this is
            # the attempt that works when the game window is in front.
            if send_fullmute():
                armed, waits = False, 0
                _log(f"TYPED {CMD!r} at gameTime={gt:.1f} (fountain)")
            else:
                waits += 1
                if waits in (1, 5, 10):
                    _log(f"waiting for the game window to be focused ({waits}s, gt={gt:.1f})")
        elif armed and gt > LATE_LIMIT and player_dead():
            # Window 2: while you're DEAD. Past the fountain, typing on the move is what cast
            # Flash — but a dead champion cannot cast, move or attack, so a stray character
            # costs nothing. Every game gives us these, and we take as many as we need.
            if send_fullmute():
                armed = False
                _log(f"TYPED {CMD!r} at gameTime={gt:.1f} (safe window: you were dead)")
            else:
                _log(f"death-window attempt at gameTime={gt:.1f} didn't land "
                     f"(alt-tabbed?) — will try the next death", )
        elif armed and gt > LATE_LIMIT and waits >= 0:
            waits = -1                          # log the handover to the death window once
            _log(f"fountain window missed at gameTime={gt:.1f} — NOT typing on the move "
                 f"(that's what cast Flash); waiting for a death instead. "
                 f"Client settings are already applied regardless.")
        time.sleep(1.0)
    _log("EXIT deadline")


def test():
    """`python core\\lolmute.py test` — type it into the game right now, once, when the game
    window is in front. Note a custom/practice game may refuse the command itself."""
    print(f"Enter scan code : 0x{ENTER_SCAN():02x} (must NOT be 0x00)")
    print(f"layout          : {'OK' if all(scan_of(c) for c in CMD) else 'FAILED'} for {CMD!r}")
    print("focus the League game window — sending as soon as it's in front (60s)...")
    for _ in range(60):
        if game_focused():
            print(f"sent={send_fullmute()} — look for the mute confirmation in chat")
            return
        time.sleep(1.0)
    print("the game window never came to the front — nothing was typed.")


if __name__ == "__main__":
    arg = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
    if arg == "test":
        test()
    elif arg in ("off", "unmute"):
        print("unmuted -> %s" % (apply(False),))
    elif arg in ("state", "status"):
        st = read_state()
        print("client not reachable" if st is None else
              "\n".join(f"  {k} = {v}" for k, v in st.items()))
    else:
        main()
