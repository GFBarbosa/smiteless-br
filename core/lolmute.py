#!/usr/bin/env python3
"""lolmute.py - AUTO-MUTE: chat off and pings silent, set through the client's own settings.

WHY THIS IS NOT `/fullmute all` ANY MORE
v0.9.51-v0.9.54 tried to TYPE `/fullmute all` into the game. It never once worked, and the
diagnosis is conclusive rather than a hunch: with the game window focused, SendInput reports
every event accepted (2/2 inserted, GetLastError 0), our process and the game's are both at
MEDIUM integrity so UIPI isn't dropping anything - the OS delivers the keystrokes and the game
discards them. That is what a kernel anti-cheat filtering injected input looks like, and no
amount of unicode-vs-scan-code or timing tuning changes it.

It was also the wrong thing to build. Every other surface in this app states plainly that it
never sends an input to the game (see loldead.py, smitedead.py) - that's the line the project
draws, and typing into a live match crossed it.

WHAT IT DOES INSTEAD
The League client exposes its own game settings over the LCU, readable AND writable:
    HUD.ShowAlliedChat      -> False   (ally chat text hidden)
    HUD.ShowAllChannelChat  -> False   (all-chat text hidden)
    Volume.PingsMute        -> True    (ping AUDIO silenced)
No keystrokes, no injection, nothing typed into the game, and - the part the old one could
never do - the result is READ BACK and verified.

HONEST LIMIT: this is not identical to `/fullmute all`. Chat text is gone and pings make no
sound, but ping MARKERS still draw on the minimap and screen; the client has no setting for
those. It is also PERSISTENT (a client setting, not a per-game command) - which is arguably
what you wanted anyway: decide once, not at 0:15 every game. `python core\\lolmute.py off`
puts all three back.
"""
import os, sys, time

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
import lolimport as limp          # its _lcu_json is the shared, proven LCU caller

SETTINGS_PATH = "/lol-game-settings/v1/game-settings"
# The mute state, and the state that undoes it. Every key here is verified against the live
# client by tools/selftest.py — a renamed setting must fail loudly, not silently do nothing.
MUTED = {"HUD": {"ShowAlliedChat": False, "ShowAllChannelChat": False},
         "Volume": {"PingsMute": True}}
UNMUTED = {"HUD": {"ShowAlliedChat": True, "ShowAllChannelChat": True},
           "Volume": {"PingsMute": False}}
_LOG = os.path.expanduser("~/.claude/smiteless_mute.log")


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def read_state():
    """{'HUD.ShowAlliedChat': False, ...} as the client reports it right now, or None if the
    client isn't up / doesn't expose these keys."""
    try:
        cur = limp._lcu_json("GET", SETTINGS_PATH)
    except Exception:
        return None
    if not isinstance(cur, dict):
        return None
    out = {}
    for grp, keys in MUTED.items():
        for k in keys:
            if grp not in cur or k not in (cur.get(grp) or {}):
                return None                  # a key we depend on is gone -> say so, don't guess
            out[f"{grp}.{k}"] = cur[grp][k]
    return out


def apply(on=True):
    """Write the mute state and VERIFY it by reading back. Returns (ok, detail). The read-back
    is the whole point: the old implementation's fatal flaw was that it could never tell the
    difference between working and not, so it claimed success for four releases."""
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


def main():
    if not cfg.load().get("auto_mute", True):
        return
    ok, detail = apply(True)
    _log(f"{'MUTED' if ok else 'FAILED'} via client settings - {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
    if arg in ("off", "unmute"):
        ok, detail = apply(False)
        print(f"{'unmuted' if ok else 'FAILED'} - {detail}")
    elif arg in ("state", "status"):
        st = read_state()
        print("client not reachable" if st is None else
              "\n".join(f"  {k} = {v}" for k, v in st.items()))
    else:
        ok, detail = apply(True)
        print(f"{'muted' if ok else 'FAILED'} - {detail}")
        _log(f"{'MUTED' if ok else 'FAILED'} (manual) - {detail}")
