#!/usr/bin/env python3
"""loldead.py - assembles the DEATH BRIEF: the dense read you get on the grey screen.

Being dead is the one zero-cost reading window in League - full attention, nothing to click.
This gathers everything the scattered in-game HUD already knows and packages it for the
fullscreen see-through brief (ui/smitedead.py): your respawn clock + the one tempo verdict,
what to buy on respawn, the win read, the scariest enemy spike, the enemy jungler, the next
objectives, and a kill/objective feed of what you missed while dead.

Everything here is READ-ONLY off the live-client feed (:2999) - no input automation, no camera
control (that needs simulating input into the game and is bannable; not happening). brief()
returns None unless the active player is dead right now, so the overlay only shows on death.
"""
import loltempo as lt
import lollive as ll
import lolitems as li
import lolgame as lg

FEED_WINDOW = 40          # seconds of history for "what you missed"


def _gname(p):
    return lg._gname(p.get("riotId") or p.get("summonerName") or "")


def _recent_feed(data, ally_names, gt):
    """Compact kill/objective feed for the last FEED_WINDOW seconds, newest first.
    Each row: {text, ally} where ally True = our team did it (tint green vs red)."""
    rows = []
    evs = (data.get("events") or {}).get("Events") or []
    for e in evs:
        t = float(e.get("EventTime") or 0.0)
        if gt - t > FEED_WINDOW or gt - t < 0:
            continue
        nm = e.get("EventName")
        killer = lg._gname(e.get("KillerName") or "")
        ally = killer in ally_names
        ago = max(0, int(gt - t))
        if nm == "ChampionKill":
            vic = e.get("VictimName") or "?"
            vic_ally = lg._gname(vic) in ally_names
            # "ally kills enemy" is good for us; "enemy kills ally" is bad
            rows.append({"t": t, "ago": ago, "ally": (not vic_ally),
                         "text": f"{_short(e.get('KillerName'))}  killed  {_short(vic)}"})
        elif nm == "DragonKill":
            dt = (e.get("DragonType") or "").replace("Elder", "Elder ").strip().lower()
            rows.append({"t": t, "ago": ago, "ally": ally,
                         "text": f"{'you' if ally else 'they'} took {dt or 'drake'}"})
        elif nm == "BaronKill":
            rows.append({"t": t, "ago": ago, "ally": ally,
                         "text": f"{'you' if ally else 'they'} took BARON"})
        elif nm == "HeraldKill":
            rows.append({"t": t, "ago": ago, "ally": ally,
                         "text": f"{'you' if ally else 'they'} took Herald"})
        elif nm in ("TurretKilled", "FirstBrick"):
            rows.append({"t": t, "ago": ago, "ally": ally, "text": "tower down"})
        elif nm == "InhibKilled":
            rows.append({"t": t, "ago": ago, "ally": ally, "text": "inhibitor down"})
    rows.sort(key=lambda r: r["t"], reverse=True)
    return rows[:6]


def _short(name):
    """Trim a Riot ID ('Name#TAG') to just the name for the feed."""
    return (name or "?").split("#")[0][:14]


_ROLE = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "BOTTOM": "BOT", "UTILITY": "SUP"}


def _scoreboard(dd, data, gt):
    """Full live rundown of all ten: champ, role, level, KDA, CS, est gold, completed items.
    Gold is the fog-proof estimate so a farmed enemy in fog doesn't read as poor."""
    split = ll.team_split(data)
    if not split:
        return None
    me, allies, enemies, _t = split
    myg = _gname(me) if me else ""

    def row(p):
        sc = p.get("scores") or {}
        items = [it.get("itemID") for it in (p.get("items") or []) if it.get("itemID")]
        try:
            nit, _g = ll._completed_items(dd, items)
        except Exception:
            nit = 0
        champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](p.get("championName", "")), 0),
                                  p.get("championName", "?"))
        return {"champ": champ, "role": _ROLE.get((p.get("position") or "").upper(), ""),
                "lvl": int(p.get("level", 1)), "k": int(sc.get("kills", 0)),
                "d": int(sc.get("deaths", 0)), "a": int(sc.get("assists", 0)),
                "cs": int(sc.get("creepScore", 0)), "gold": int(ll.est_gold(p, gt)),
                "items": nit, "dead": bool(p.get("isDead")), "me": _gname(p) == myg}
    al = [row(p) for p in allies]
    en = [row(p) for p in enemies]
    lead = sum(r["gold"] for r in al) - sum(r["gold"] for r in en)
    return {"allies": al, "enemies": en, "gold_lead": lead}


def brief(dd, data):
    """The full death brief, or None unless the active player is dead right now."""
    dead = lt.respawn_plan(dd, data)          # None unless YOU are dead -> the whole trigger
    if not dead:
        return None
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
    out = {"secs": dead.get("secs"), "tone": dead.get("tone"),
           "verdict": dead.get("line") or "", "verdict_sub": dead.get("sub") or "",
           "gametime": gt, "buy": None, "winprob": None, "spike": None,
           "jungle": None, "objectives": [], "feed": []}
    try:
        rc = li.recall_advice(dd, data)
        out["buy"] = rc.get("text") if rc else None
    except Exception:
        pass
    try:
        p = ll.pulse(dd, data)
    except Exception:
        p = None
    if p:
        out["winprob"] = p.get("winprob")
        out["spike"] = p.get("spike")
        out["jungle"] = p.get("jungle")
        out["objectives"] = [o for o in (p.get("objectives") or []) if o.get("secs") is not None][:3]
    try:
        split = ll.team_split(data)
        allies = split[1] if split else []
        out["feed"] = _recent_feed(data, {_gname(a) for a in allies}, gt)
    except Exception:
        pass
    try:
        out["board"] = _scoreboard(dd, data, gt)
    except Exception:
        out["board"] = None
    return out
