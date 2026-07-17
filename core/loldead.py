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
import loltags as ltag

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
        cid = dd["name2id"].get(dd["norm"](p.get("championName", "")))
        champ = dd["id2name"].get(cid, p.get("championName", "?"))
        k, dth = int(sc.get("kills", 0)), int(sc.get("deaths", 0))
        return {"champ": champ, "role": _ROLE.get((p.get("position") or "").upper(), ""),
                "lvl": int(p.get("level", 1)), "k": k, "d": dth, "a": int(sc.get("assists", 0)),
                "cs": int(sc.get("creepScore", 0)), "gold": int(ll.est_gold(p, gt)),
                "items": nit, "dead": bool(p.get("isDead")), "me": _gname(p) == myg,
                "cid": cid or 0, "tag": ltag.short(dd, cid) if cid else "",
                "fed": (k - dth >= 5 and nit >= 2)}     # snowballing & itemized -> flag it
    al = [row(p) for p in allies]
    en = [row(p) for p in enemies]
    lead = sum(r["gold"] for r in al) - sum(r["gold"] for r in en)
    return {"allies": al, "enemies": en, "gold_lead": lead}


def _cls(dd, cid):
    tags = dd.get("id2tags", {}).get(cid, []) or []
    return tags[0] if tags else ""


# how to play AGAINST a fed enemy of each class — the counterplay, not just "watch him"
_COUNTER = {
    "Assassin": "buy Zhonya's / GA, never walk alone, group tight — he deletes you solo",
    "Marksman": "he's squishy — hard-engage / CC him first, blow him up before he DPS's",
    "Mage": "don't stand in his poke; flank or dive him, buy MR",
    "Fighter": "don't 1v1 him — kite with your team, buy armor, focus him down together",
    "Tank": "ignore him in fights, buy %HP / armor-pen, kill the carries behind him",
    "Support": "he enables them — CC/kill him first to open the fight",
}


def _death_cause(dd, data, me, enemies, gt):
    """Why you just died + the takeaway, from the kill event where YOU were the victim."""
    myg = _gname(me)
    kill = None
    for e in reversed((data.get("events") or {}).get("Events") or []):
        if e.get("EventName") == "ChampionKill" and lg_gname(e.get("VictimName")) == myg \
                and gt - float(e.get("EventTime") or 0) <= 25:
            kill = e
            break
    if not kill:
        return None
    kg = lg_gname(kill.get("KillerName") or "")
    killer = next((p for p in enemies if _gname(p) == kg), None)
    assists = len(kill.get("Assisters") or [])
    if not killer:                                     # executed / turret / minion
        return {"line": "You died with no killer credited", "sub": "reset, respawn clean"}
    sc = killer.get("scores") or {}
    kk, kd = int(sc.get("kills", 0)), int(sc.get("deaths", 0))
    champ = dd["id2name"].get(dd["name2id"].get(dd["norm"](killer.get("championName", "")), 0),
                              killer.get("championName", "?"))
    cid = dd["name2id"].get(dd["norm"](killer.get("championName", "")))
    cls = _cls(dd, cid)
    fed = kk - kd >= 3
    if assists >= 2:
        line = f"Collapsed on by {champ} +{assists}"
        sub = "you were caught out of position — group up, ward flanks, stop face-checking"
    elif fed and cls == "Assassin":
        line = f"Solo-killed by {champ} ({kk}/{kd})"
        sub = "he one-shots you now — " + _COUNTER["Assassin"]
    else:
        line = f"Solo-killed by {champ} ({kk}/{kd})"
        sub = _COUNTER.get(cls, "lost the trade — don't take even fights into him without summs")
    return {"line": line, "sub": sub}


def _scalers(dd, rows):
    n = 0
    for p in rows:
        cid = dd["name2id"].get(dd["norm"](p.get("championName", "")))
        if _cls(dd, cid) == "Marksman" or dd["id2name"].get(cid) in ("Kassadin", "Vayne", "Jax", "Kayle", "Nasus", "Veigar"):
            n += 1
    return n


def _wincon(dd, data, me, allies, enemies, wp, board):
    """How YOU win this specific game — the strategic anchor to hold onto on the grey screen."""
    ahead = bool(wp and wp.get("ahead"))
    my_s, en_s = _scalers(dd, allies), _scalers(dd, enemies)
    myrow = next((r for r in (board.get("allies") or []) if r.get("me")), None)
    if myrow and myrow.get("fed"):
        return "You're the win condition — take objectives with your lead and close before they scale."
    if ahead and my_s <= en_s:
        return "You're ahead — force tempo NOW: take towers and objectives, end before it evens out."
    if my_s > en_s:
        return "You out-scale — survive the early game, farm, take neutrals; your power is 3 items each."
    if not ahead and en_s >= my_s:
        return "Behind vs a scaling comp — you MUST make plays early: force objectives, don't let it go late."
    return "Even game — win the next neutral objective; group and trade cross-map, don't coinflip."


def _threat(dd, board):
    """The enemy carrying the game + how to deal with them (not just 'watch him')."""
    ens = board.get("enemies") or []
    cand = [r for r in ens if (r["k"] - r["d"]) >= 3 and r["items"] >= 2]
    if not cand:
        return None
    r = max(cand, key=lambda x: (x["k"] - x["d"]) + x["items"])
    cls = _cls(dd, r.get("cid", 0))
    return {"line": f"{r['champ']} {r['k']}/{r['d']}/{r['a']} is carrying",
            "sub": _COUNTER.get(cls, "shut him down — deny him kills, group and focus him")}


def lg_gname(name):
    return lg._gname(name or "")


def brief(dd, data):
    """The full death brief, or None unless the active player is dead right now."""
    dead = lt.respawn_plan(dd, data)          # None unless YOU are dead -> the whole trigger
    if not dead:
        return None
    gt = float((data.get("gameData") or {}).get("gameTime") or 0.0)
    out = {"secs": dead.get("secs"), "tone": dead.get("tone"),
           "verdict": dead.get("line") or "", "verdict_sub": dead.get("sub") or "",
           "gametime": gt, "buy": None, "winprob": None, "spike": None,
           "jungle": None, "objectives": [], "feed": [], "board": None,
           "why": None, "wincon": None, "threat": None}
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
    split = None
    try:
        split = ll.team_split(data)
    except Exception:
        split = None
    me, allies, enemies = (split[0], split[1], split[2]) if split else (None, [], [])
    try:
        out["feed"] = _recent_feed(data, {_gname(a) for a in allies}, gt)
    except Exception:
        pass
    try:
        out["board"] = _scoreboard(dd, data, gt)
    except Exception:
        out["board"] = None
    # ---- the coaching (the whole point of the overhaul): why you died, how you win, the threat ----
    if me is not None and out.get("board"):
        try:
            out["why"] = _death_cause(dd, data, me, enemies, gt)
        except Exception:
            out["why"] = None
        try:
            out["wincon"] = _wincon(dd, data, me, allies, enemies, out.get("winprob"), out["board"])
        except Exception:
            out["wincon"] = None
        try:
            out["threat"] = _threat(dd, out["board"])
        except Exception:
            out["threat"] = None
    return out
