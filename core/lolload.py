#!/usr/bin/env python3
"""lolload.py - the LOADING-SCREEN brief: know the matchup before the game starts.

The loading screen is dead time you can use. Riot only exposes PLACEHOLDER player ids here
(so no live rank/form scout - lolscout.roster() says as much), but the LCU gameflow session
DOES carry the ten champions and the teams. That's enough for the read that actually matters
pre-game: what each champ does well/badly, the damage split to itemize against, and a plain
game-plan for the comp you're about to face. All read-only off the local client.
"""
import lolgame as lg
import lolbuild as lb
import loltags as ltag

_ROLE = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "MID": "MID", "BOTTOM": "BOT",
         "BOT": "BOT", "UTILITY": "SUP", "SUPPORT": "SUP"}


def _roster():
    """(allies, enemies) as lists of {champ_id, role}, from the gameflow session during
    loading. Returns (None, None) if there's no game roster to read yet."""
    lc = lg._lcu()
    if not lc:
        return None, None
    port, hdr = lc
    try:
        s = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/session",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None, None
    gd = (s or {}).get("gameData") or {}
    t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
    if not (t1 and t2):
        return None, None
    # which team is mine? match my display name (puuids are placeholders during loading)
    myname = ""
    try:
        cs = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                     headers=hdr, timeout=4, insecure=True)
        myname = lg._gname(cs.get("gameName") or cs.get("displayName") or "")
    except Exception:
        pass

    def nm(p):
        return lg._gname(p.get("summonerName") or p.get("gameName") or "")
    mine = t1 if (myname and any(nm(p) == myname for p in t1)) else \
        (t2 if (myname and any(nm(p) == myname for p in t2)) else t1)   # fallback: teamOne
    other = t2 if mine is t1 else t1

    def row(p):
        return {"champ_id": int(p.get("championId") or 0),
                "role": _ROLE.get((p.get("selectedPosition") or p.get("assignedPosition")
                                   or p.get("position") or "").upper(), "")}
    al = [row(p) for p in mine if p.get("championId")]
    en = [row(p) for p in other if p.get("championId")]
    return (al or None), (en or None)


def _comp_read(dd, rows):
    """A one-line profile of a team: damage split + how many divers/tanks/scalers."""
    ad = ap = 0
    divers = tanks = scalers = 0
    for r in rows:
        cid = r["champ_id"]
        dt = ltag.dmg_type(dd, cid)
        ad += dt in ("AD", "mixed")
        ap += dt in ("AP", "mixed")
        tags = dd.get("id2tags", {}).get(cid, []) or []
        if "Assassin" in tags:
            divers += 1
        if "Tank" in tags:
            tanks += 1
        if "Marksman" in tags or dd.get("id2name", {}).get(cid) in ("Kassadin", "Vayne", "Jax", "Kayle"):
            scalers += 1
    return {"ad": ad, "ap": ap, "divers": divers, "tanks": tanks, "scalers": scalers}


def _plan(dd, my, en):
    """Plain how-to-play lines for this matchup, from the two comp reads."""
    ec, mc = _comp_read(dd, en), _comp_read(dd, my)
    out = []
    if ec["ad"] >= 3 and ec["ap"] <= 1:
        out.append("Enemy is AD-heavy — rush armor / Seeker's, Randuin's on tanks.")
    elif ec["ap"] >= 3 and ec["ad"] <= 1:
        out.append("Enemy is AP-heavy — build MR / Maw / Hexdrinker early.")
    if ec["divers"] >= 2:
        out.append(f"{ec['divers']} assassins — respect level 6, group, buy Zhonya's/GA, ward flanks.")
    if mc["scalers"] >= 2 and ec["divers"] + ec["tanks"] <= mc["scalers"]:
        out.append("You out-scale — survive the early game, don't coinflip, win the late.")
    elif ec["scalers"] >= 2:
        out.append("They out-scale — force early tempo and objectives, end before 3 items.")
    if ec["tanks"] >= 2:
        out.append("Two+ tanks — buy % HP / armor-pen; don't waste burst on the frontline.")
    return out[:4] or ["Even comps — play your matchup, track the enemy jungler, trade objectives."]


def brief(dd):
    """The loading brief, or None if no game roster is readable yet."""
    my, en = _roster()
    if not (my and en):
        return None

    def enrich(rows):
        out = []
        for r in rows:
            cid = r["champ_id"]
            out.append({"champ": dd.get("id2name", {}).get(cid, "?"), "role": r["role"],
                        "dmg": ltag.dmg_type(dd, cid), "phrases": ltag.phrases(dd, cid)})
        return out
    return {"allies": enrich(my), "enemies": enrich(en), "plan": _plan(dd, my, en)}
