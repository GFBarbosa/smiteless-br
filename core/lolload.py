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


def _player_scout(dd, puuid, cid, key):
    """Full per-ACCOUNT read for the loading scoreboard: solo rank (+LP, season W/L),
    last-10 form, recent + this-champ record, pooled KDA, deaths/game, avg performance
    score (how they actually play), mastery on this champ, their MAIN role over the last
    10 games, and the recent match ids (drives the lobby-wide duo pass)."""
    out = {"rank_full": None, "pts": 0, "mlevel": 0, "n": 0, "w": 0, "cg": 0, "cw": 0,
           "form": [], "kdar": None, "kavg": "", "dpg": None, "perf": None,
           "main_pos": "", "mids": []}
    try:
        out["rank_full"] = ls.rank(puuid, key)
    except Exception:
        pass
    try:
        n, w, cg, cw, form, mids, kda, perf = ls.scout(dd, puuid, cid, key, 10)
        out.update(n=n, w=w, cg=cg, cw=cw, form=form, mids=mids or [], perf=perf)
        g = (kda or {}).get("g", 0)
        if g:
            out["kdar"] = round((kda["k"] + kda["a"]) / max(1, kda["d"]), 1)
            out["kavg"] = f"{kda['k'] / g:.1f} / {kda['d'] / g:.1f} / {kda['a'] / g:.1f}"
            out["dpg"] = round(kda["d"] / g, 1)
    except Exception:
        pass
    try:
        m = ls.mastery(puuid, cid, key) or {}
        out["pts"], out["mlevel"] = int(m.get("points", 0)), int(m.get("level", 0))
    except Exception:
        pass
    # main role over the recent games — pure disk reads (scout just cached these matches)
    posc = {}
    for mid in out["mids"]:
        try:
            res = ls.match_results(mid, key)
        except Exception:
            continue
        rec = (res or {}).get(puuid)
        if rec and len(rec) >= 11 and rec[10]:
            posc[rec[10]] = posc.get(rec[10], 0) + 1
    if posc:
        best = max(posc, key=posc.get)
        if posc[best] >= max(3, (sum(posc.values()) + 1) // 2):   # a real main, not noise
            out["main_pos"] = _ROLE.get(best.upper(), "")
    return out


def _profile_tags(row, ally):
    """The DETAILED, UNIQUE profile-read tags — what kind of player this account is, said
    plainly. Tone is relative to YOU: an enemy on a loss streak is 'good' (for you).
    Ordered sharpest-first; the renderer draws the first few that fit."""
    tags = []

    def tone(good_for_them):
        return ("good" if good_for_them else "bad") if ally else ("bad" if good_for_them else "good")

    rk = row.get("rank_full") or {}
    sg = int(rk.get("w", 0) or 0) + int(rk.get("l", 0) or 0)
    swr = round(rk["w"] / sg * 100) if sg else None
    form, n, w = row.get("form") or [], row.get("n", 0), row.get("w", 0)
    pts, cg, cw = row.get("pts", 0), row.get("cg", 0), row.get("cw", 0)
    perf, dpg, champ = row.get("perf"), row.get("dpg"), row.get("champ", "?")
    # live streak (sharpest signal there is)
    if form:
        lead = 1
        while lead < len(form) and form[lead] == form[0]:
            lead += 1
        if lead >= 3:
            tags.append((f"{lead}W streak · confident" if form[0]
                         else f"{lead}L streak · tilt risk", tone(form[0])))
    # smurf read: stomping recents on a barely-played ranked account
    if n >= 8 and w / n >= 0.65 and 0 < sg < 80:
        tags.append(("SMURF READ · new acct, stomping", tone(True)))
    # champ relationship: OTP / main / comfort / first-time
    if pts >= 250_000:
        tags.append((f"{champ} OTP · {pts // 1000}k pts", tone(True)))
    elif pts >= 100_000:
        tags.append((f"{champ} main · {pts // 1000}k pts", tone(True)))
    elif row.get("scouted") and pts < 6000 and cg == 0:
        tags.append((f"first-time {champ}?", tone(False)))
    if cg >= 5:
        tags.append((f"comfort pick · {cw}-{cg - cw} recently", tone(cw * 2 >= cg)))
    # autofill / off-role
    mp = row.get("main_pos")
    if mp and row.get("role") and mp != row["role"]:
        tags.append((f"off-role · {mp} main", tone(False)))
    # how they die (or don't)
    if dpg is not None and n >= 5:
        if dpg >= 6.5:
            tags.append((f"bleeds · {dpg} deaths/game", tone(False)))
        elif dpg <= 2.6:
            tags.append(("hard to kill · low deaths", tone(True)))
    # how they actually play, independent of W/L
    if perf is not None:
        if perf >= 85:
            tags.append((f"carries games · {int(perf)} avg perf", tone(True)))
        elif perf <= 45:
            tags.append(("passenger · low impact", tone(False)))
    # account character
    if sg >= 400:
        tags.append((f"grinder · {sg} ranked this season", "neutral"))
    elif 0 < sg <= 25:
        tags.append(("fresh ranked account", "neutral"))
    if swr is not None and sg >= 100:
        if swr >= 55:
            tags.append((f"climbing · {swr}% season wr", tone(True)))
        elif swr <= 45:
            tags.append((f"hardstuck · {swr}% season wr", tone(False)))
    return tags


_DUO_SHARED = 3          # recent ranked games in common (same team) that flag a premade


def _duo_pass(team_rows):
    """Cross-reference ONE TEAM's recent match ids: players sharing >=3 recent ranked
    games are almost certainly queued together. Prepends a 'duo · NAME' tag to both."""
    for i, a in enumerate(team_rows):
        for b in team_rows[i + 1:]:
            if not (a.get("mids") and b.get("mids")):
                continue
            if len(set(a["mids"]) & set(b["mids"])) >= _DUO_SHARED:
                an = (a.get("player") or a.get("champ") or "?").split("#")[0]
                bn = (b.get("player") or b.get("champ") or "?").split("#")[0]
                a["tags"].insert(0, (f"duo · {bn}", "info"))
                b["tags"].insert(0, (f"duo · {an}", "info"))


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
            rec = {"champ": dd.get("id2name", {}).get(cid, "?"), "cid": cid, "role": row["role"],
                   "dmg": ltag.dmg_type(dd, cid), "phrases": ltag.phrases(dd, cid),
                   "me": row["me"], "player": "", "scouted": False, "tags": [],
                   "rank_full": None, "form": [], "n": 0, "w": 0, "cg": 0, "cw": 0,
                   "kdar": None, "kavg": "", "dpg": None, "perf": None,
                   "pts": 0, "mlevel": 0, "main_pos": "", "mids": []}
            if key:
                try:
                    ign = _ign_for(port, hdr, row["sid"])
                    puuid = ls.resolve_puuid(ign, key) if ign else None
                    if puuid and len(puuid) > 70:
                        rec["player"] = ign
                        rec.update(_player_scout(dd, puuid, cid, key))
                        rec["scouted"] = True
                        rec["tags"] = _profile_tags(rec, ally)
                except Exception:
                    pass
            out.append(rec)
        return out
    allies, enemies = enrich(my, True), enrich(en, False)
    if key:
        _duo_pass(allies)
        _duo_pass(enemies)
    return {"allies": allies, "enemies": enemies,
            "plan": _plan(dd, my, en), "scouted": bool(key)}
