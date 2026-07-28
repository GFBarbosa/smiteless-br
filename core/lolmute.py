#!/usr/bin/env python3
"""lolmute.py - AUTO-MUTE: `/fullmute all` the instant the game actually starts.

Ping spam and chat are the two things in a solo-q game you cannot outplay, and the decision
to mute is one you always make the same way - so make it once, in Settings, instead of every
game at 0:15 while you're trying to path. `/fullmute all` is Riot's own command: it hides
chat AND pings from every player for that game only, so nothing is changed permanently and
your own pings still work.

Typing into the game is the only way in (there's no API for muting), which makes the FOCUS
CHECK load-bearing: keystrokes go out only when the foreground window is provably the League
game window - right class, and its process is really `League of Legends.exe`. If you're
alt-tabbed we wait; the command is never sent blind into whatever else you're looking at.

Gated on the `auto_mute` setting (Settings -> In-game automation).
"""
import os, sys, time, json, ssl, ctypes, urllib.request
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
from lolcreds import _type, _tap, VK_RET       # the proven SendInput path (unicode + vk taps)

CMD = "/fullmute all"                          # chat + pings, every player, this game only
GAME_CLASS = "RiotWindowClass"
GAME_EXE = "league of legends.exe"
_LOG = os.path.expanduser("~/.claude/smiteless_mute.log")
_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_PROC_QUERY_LIMITED = 0x1000


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def game_time():
    """Live game clock in seconds, or -1.0 when :2999 isn't serving. The clock is the honest
    'has the match begun' signal - :2999 answers with gameTime 0 all through the loading
    screen, and muting there would type into a screen that has no chat box."""
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
    """True only when the foreground window IS the League game. Two independent checks - the
    window class and the owning process's image name - because this gate is the only thing
    standing between a keystroke burst and whatever app the user actually has in front of
    them. Anything we can't positively identify counts as 'not the game'."""
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


def send_fullmute():
    """Open chat, type the command, send it. Returns True if the keystrokes went out.
    Re-checks focus immediately before each burst: the user can alt-tab between our poll and
    our keypress, and a half-typed command must never land somewhere else."""
    if not game_focused():
        return False
    _tap(VK_RET)                    # Enter opens the in-game chat input (not rebindable)
    time.sleep(0.25)
    if not game_focused():          # focus lost between opening chat and typing -> abort
        return False
    _type(CMD)
    time.sleep(0.10)
    if not game_focused():
        return False
    _tap(VK_RET)                    # send it
    return True


def _single_instance():
    k = ctypes.WinDLL("kernel32", use_last_error=True)   # get_last_error needs its own handle
    k.CreateMutexW(None, False, "Global\\SmitelessMute")
    return ctypes.get_last_error() != 183                # ERROR_ALREADY_EXISTS


def main():
    if not cfg.load().get("auto_mute", True):
        return
    if not _single_instance():
        return
    try:
        open(_LOG, "w").close()                     # fresh log per launch
    except Exception:
        pass
    _log(f"LAUNCH auto_mute=on cmd={CMD!r}")

    armed = True                 # waiting to fire for the current game session
    seen = False                 # the clock has been observed running at least once
    gone = 0                     # consecutive polls with :2999 down
    waits = 0                    # polls spent waiting for the game to be focused
    deadline = time.monotonic() + 1800          # champ select + loading + a long game
    while time.monotonic() < deadline:
        if cfg.tray_gone():
            _log("EXIT tray closed")
            return
        gt = game_time()
        if gt < 0:
            gone += 1
            # A LONG silence after we'd been playing means the game is over (or we were
            # dropped). Re-arm on the way out so a RECONNECT - which comes back as a fresh
            # game session, with the old mutes cleared - gets muted again.
            if seen and gone >= 10:
                if not armed:
                    _log("connection lost for 10 polls -> re-arming for a possible reconnect")
                armed = True
            if seen and gone >= 60:
                _log("EXIT game over (:2999 down 60 polls)")
                return
            time.sleep(1.0)
            continue
        gone = 0
        if gt > 1.0:
            seen = True
            if armed:
                if send_fullmute():
                    armed = False
                    waits = 0
                    _log(f"SENT {CMD!r} at gameTime={gt:.1f}")
                else:
                    waits += 1
                    if waits in (1, 15, 60) or waits % 120 == 0:
                        _log(f"waiting for the game window to be focused ({waits}s, gt={gt:.1f})")
        time.sleep(1.0)
    _log("EXIT deadline")


if __name__ == "__main__":
    main()
