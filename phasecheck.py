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


def main():
    lf = _lockfile()
    ctx = ssl._create_unverified_context()
    if not lf:
        # client not found via lockfile, but maybe the game is running (live client)?
        try:
            urllib.request.urlopen("https://127.0.0.1:2999/liveclientdata/gamestats",
                                   timeout=1, context=ctx)
            print("InProgress")
        except Exception:
            print("")
        return
    try:
        _n, _p, port, pw, _proto = open(lf).read().split(":")
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase",
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3, context=ctx) as r:
            print(json.load(r))          # e.g. "ChampSelect"
    except Exception:
        print("")


if __name__ == "__main__":
    main()
