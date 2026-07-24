#!/usr/bin/env python3
"""phasecheck.py - prints the current League gameflow phase and exits fast.

Minimal stdlib only (no PIL/op.gg imports) so the AHK watcher can poll it cheaply
to decide when to auto-open Smiteless. Prints one of: Lobby, Matchmaking,
ChampSelect, GameStart, InProgress, Reconnect, WaitingForStats, PreEndOfGame,
EndOfGame, None, or "" (client not running).
"""
import os, base64, json, ssl, string, urllib.request


def _lockfile():
    paths = [
        r"F:\Riot Games\League of Legends\lockfile",
        r"C:\Riot Games\League of Legends\lockfile",
        r"C:\Program Files\Riot Games\League of Legends\lockfile",
        r"D:\Riot Games\League of Legends\lockfile",
        os.path.expanduser(r"~/Riot Games/League of Legends/lockfile"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    for d in string.ascii_uppercase:
        p = f"{d}:\\Riot Games\\League of Legends\\lockfile"
        if os.path.exists(p):
            return p
    return None


def phase():
    """Current League phase string (e.g. 'ChampSelect', 'InProgress', '' if no client)."""
    ctx = ssl._create_unverified_context()
    # Check the live-client / replay API (port 2999) FIRST: if it answers, an actual game
    # OR a replay/spectator session is running -> treat as InProgress. This is what makes
    # the overlay open during replays (the gameflow phase reads "None" during a replay).
    try:
        urllib.request.urlopen("https://127.0.0.1:2999/liveclientdata/gamestats",
                               timeout=1, context=ctx)
        return "InProgress"
    except Exception:
        pass
    lf = _lockfile()
    if not lf:
        return ""
    try:
        _n, _p, port, pw, _proto = open(lf).read().split(":")
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase",
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3, context=ctx) as r:
            return str(json.load(r))     # e.g. "ChampSelect"
    except Exception:
        return ""


def game_time():
    """Live game clock in seconds from :2999, or -1.0 when it isn't serving. The clock only
    ADVANCES once the game has actually begun — :2999 already answers with gameTime ~0 while
    you're still sitting on the loading screen — so this is the honest 'are we playing yet?'."""
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen("https://127.0.0.1:2999/liveclientdata/gamestats",
                                    timeout=1, context=ctx) as r:
            return float(json.load(r).get("gameTime", 0.0) or 0.0)
    except Exception:
        return -1.0


def phase_detailed():
    """phase(), except the LOADING SCREEN reports as 'Loading' instead of 'InProgress'.

    phase() deliberately says InProgress the moment :2999 answers (that's what makes the
    overlay work in replays), but :2999 starts answering while the loading screen is still
    up — so callers that used it to mean 'the game is being played' were firing early, which
    is how the in-game widget ended up painted over the loading scout. Anything that needs
    'the match is actually running' should use this; the phase() contract is unchanged."""
    ph = phase()
    if ph == "InProgress":
        gt = game_time()
        # 0..1 = the clock exists but hasn't started -> still loading. A -1 (:2999 blipped on
        # THIS call, though it answered a moment ago for phase()) is 'unknown', not 'loading':
        # treating it as loading would yank the widget mid-game on a transient hiccup.
        if 0.0 <= gt <= 1.0:
            return "Loading"
    return ph


def main():
    import sys
    print(phase_detailed() if "--detailed" in sys.argv[1:] else phase())


if __name__ == "__main__":
    main()
