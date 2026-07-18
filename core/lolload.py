#!/usr/bin/env python3
"""lolload.py - the LOADING-SCREEN brief: know the players AND the matchup before the game.

The loading screen is the first time everyone's IGN is exposed, so it's the first time you can
actually scout the lobby. Riot hands out placeholder puuids in the gameflow session, but each
player carries a real summonerId -> the LCU resolves that to a real Name#TAG -> the Riot API
resolves THAT to a real puuid -> full scout (rank, recent form, one-trick, mastery). Champ
select just cached all of it, so it's near-instant here.

So the brief carries both: per-player SCOUT tags (rank, hot/tilted streak, OTP, off-champ) and
per-champ good/bad tags + a plain game-plan for the comp. All read-only off the local client
and the user's own Riot key.
"""
import lolgame as lg
import lolbuild as lb
import loltags as ltag
import lolscout as ls

_ROLE = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID", "MID": "MID", "BOTTOM": "BOT",
         "BOT": "BOT", "UTILITY": "SUP", "SUPPORT": "SUP"}
_TIER = {"IRON": "Iron", "BRONZE": "Bronze", "SILVER": "Silver", "GOLD": "Gold",
         "PLATINUM": "Plat", "EMERALD": "Emerald", "DIAMOND": "Diamond", "MASTER": "Master",
         "GRANDMASTER": "GM", "CHALLENGER": "Chall"}


def _ign_for(port, hdr, sid):
    if not sid:
        return ""
    try:
        r = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/summoners/{sid}",
                    headers=hdr, timeout=4, insecure=True)
        gn, tl = r.get("gameName", ""), r.get("tagLine", "")
        return f"{gn}#{tl}" if gn and tl else ""
    except Exception:
        return ""


def _roster():
    """(my_rows, enemy_rows, (port, hdr)) or None. Each row: {sid, champ_id, role, me}."""
    lc = lg._lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        s = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/session",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None
    gd = (s or {}).get("gameData") or {}
    t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
    if not (t1 and t2):
        return None
    mysid = None
    try:
        mysid = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                        headers=hdr, timeout=4, insecure=True).get("summonerId")
    except Exception:
        pass
    mine = t1 if any(p.get("summonerId") == mysid for p in t1) else \
        (t2 if any(p.get("summonerId") == mysid for p in t2) else t1)
    other = t2 if mine is t1 else t1

    def rows(team):
        out = []
        for p in team:
            if p.get("championId"):
                out.append({"sid": p.get("summonerId"), "champ_id": int(p["championId"]),
                            "role": _ROLE.get((p.get("selectedPosition") or "").upper(), ""),
                            "me": p.get("summonerId") == mysid})
        return out
    return rows(mine), rows(other), (port, hdr)


def _player_tags(dd, puuid, cid, key, ally):
    """(rank_str, [(text, tone)]) — tone is 'good'/'bad'/'neutral' RELATIVE TO YOU (an enemy on
    a loss streak is 'good'; your ally on one is 'bad')."""
    rank_str = ""
    try:
        rk = ls.rank(puuid, key)
        if rk and rk.get("tier"):
            rank_str = f"{_TIER.get(rk['tier'].upper(), rk['tier'].title())} {rk.get('div', '')}".strip()
    except Exception:
        pass
    try:
        n, w, cg, cw, form, _ids, _kda, _perf = ls.scout(dd, puuid, cid, key, 8)
    except Exception:
        n = w = cg = 0
        form = []
    tags = []

    def tone(is_good_for_them):
        # good for them + they're an enemy = bad for you, etc.
        if is_good_for_them:
            return "bad" if not ally else "good"
        return "good" if not ally else "bad"

    if form:
        lead = 1
        for i in range(1, len(form)):
            if form[i] == form[0]:
                lead += 1
            else:
                break
        if lead >= 3:
            tags.append((f"{lead}W hot" if form[0] else f"{lead}L skid", tone(form[0])))
    if n >= 5 and not tags:
        wr = w / n
        if wr >= 0.65:
            tags.append((f"{int(wr*100)}% climbing", tone(True)))
        elif wr <= 0.35:
            tags.append((f"{int(wr*100)}% struggling", tone(False)))
    try:
        m = ls.mastery(puuid, cid, key)
    except Exception:
        m = None
    pts = (m or {}).get("points", 0)
    if cg >= 6 or pts >= 100000:
        tags.append(("OTP", "bad" if not ally else "good"))     # a one-trick is dangerous / reliable
    elif pts < 12000 and cg == 0:
        tags.append(("off-champ", tone(False)))                 # sub-12k mastery pick wins ~44%
    return rank_str, tags[:3]


def _comp_read(dd, rows):
    ad = ap = divers = tanks = scalers = 0
    for r in rows:
        cid = r["champ_id"]
        dt = ltag.dmg_type(dd, cid)
        ad += dt in ("AD", "mixed")
        ap += dt in ("AP", "mixed")
        tags = dd.get("id2tags", {}).get(cid, []) or []
        divers += "Assassin" in tags
        tanks += "Tank" in tags
        if "Marksman" in tags or dd.get("id2name", {}).get(cid) in ("Kassadin", "Vayne", "Jax", "Kayle"):
            scalers += 1
    return {"ad": ad, "ap": ap, "divers": divers, "tanks": tanks, "scalers": scalers}


def _plan(dd, my, en):
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


def brief(dd, key=None, scout=True):
    """The loading brief. scout=False returns FAST (champs + tags + damage + plan, no Riot API)
    so the overlay can appear instantly; scout=True additionally pulls each player's rank/form/
    OTP tags (slow, rate-limited — run it off the render loop). None if no roster is readable."""
    r = _roster()
    if not r:
        return None
    my, en, (port, hdr) = r
    key = (key or ls.read_key()) if scout else None

    def enrich(rows, ally):
        out = []
        for row in rows:
            cid = row["champ_id"]
            rec = {"champ": dd.get("id2name", {}).get(cid, "?"), "role": row["role"],
                   "dmg": ltag.dmg_type(dd, cid), "phrases": ltag.phrases(dd, cid),
                   "rank": "", "ptags": [], "me": row["me"]}
            if key:
                try:
                    ign = _ign_for(port, hdr, row["sid"])
                    puuid = ls.resolve_puuid(ign, key) if ign else None
                    if puuid and len(puuid) > 70:
                        rec["rank"], rec["ptags"] = _player_tags(dd, puuid, cid, key, ally)
                except Exception:
                    pass
            out.append(rec)
        return out
    return {"allies": enrich(my, True), "enemies": enrich(en, False),
            "plan": _plan(dd, my, en), "scouted": bool(key)}
