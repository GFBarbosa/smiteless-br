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
    """(riot_id, summoner_level) for a summonerId. The LCU summoner blob already carries
    summonerLevel, so the new-account / smurf evidence is free on the loading path."""
    if not sid:
        return "", None
    try:
        r = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/summoners/{sid}",
                    headers=hdr, timeout=4, insecure=True)
        gn, tl = r.get("gameName", ""), r.get("tagLine", "")
        lvl = int(r.get("summonerLevel") or 0) or None
        return (f"{gn}#{tl}" if gn and tl else ""), lvl
    except Exception:
        return "", None


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


def _player_scout(dd, puuid, cid, key, riot_id=None):
    """Full per-ACCOUNT read for the loading scoreboard: solo rank (+LP, season W/L),
    last-10 form, recent + this-champ record, pooled KDA, deaths/game, avg performance
    score (how they actually play), mastery on this champ, their MAIN role over the last
    10 games, and the recent match ids (drives the lobby-wide duo pass). `riot_id` lets the
    scout fall back to u.gg when Riot's match history is down (see lolscout.scout)."""
    out = {"rank_full": None, "pts": 0, "mlevel": 0, "n": 0, "w": 0, "cg": 0, "cw": 0,
           "form": [], "kdar": None, "kavg": "", "dpg": None, "perf": None,
           "main_pos": "", "mids": [], "recent": []}
    try:
        out["rank_full"] = ls.rank(puuid, key)
    except Exception:
        pass
    try:
        n, w, cg, cw, form, mids, kda, perf, recent = ls.scout(dd, puuid, cid, key, 10,
                                                               riot_id=riot_id)
        out.update(n=n, w=w, cg=cg, cw=cw, form=form, mids=mids or [], perf=perf,
                   recent=recent or [])
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
    out["main_pos"] = _main_pos(out["recent"])
    return out


def _main_pos(recent):
    """Their real position over the recent games (from the same match reads) — a main is a
    position holding at least max(3, half) of the sample, anything less is noise."""
    posc = {}
    for _c, _w, pos in recent or []:
        if pos:
            posc[pos] = posc.get(pos, 0) + 1
    if not posc:
        return ""
    best = max(posc, key=posc.get)
    if posc[best] >= max(3, (sum(posc.values()) + 1) // 2):
        return _ROLE.get(best.upper(), "")
    return ""


def _profile_tags(row, ally):
    """The profile-read tags, per docs/TAGS.md: every tag is a CLAIM whose EVIDENCE is cited
    in the pill text itself — no evidence, no tag. THIS-GAME reads (what to expect on the
    champ they locked TODAY) render before ACCOUNT reads (who the account is), because a
    Morgana one-trick can be a Brand feeder in the same lobby and the tag must say which.
    Tone is relative to YOU: an enemy on a loss streak is 'good' (for you).
    Inferences (smurf?) always carry a '?'; facts (new account · lvl 34) don't."""
    this_game, account = [], []

    def tone(good_for_them):
        return ("good" if good_for_them else "bad") if ally else ("bad" if good_for_them else "good")

    rk = row.get("rank_full") or {}
    sg = int(rk.get("w", 0) or 0) + int(rk.get("l", 0) or 0)
    swr = round(rk["w"] / sg * 100) if sg else None
    form, n, w = row.get("form") or [], row.get("n", 0), row.get("w", 0)
    pts, cg, cw = row.get("pts", 0), row.get("cg", 0), row.get("cw", 0)
    perf, dpg, champ = row.get("perf"), row.get("dpg"), row.get("champ", "?")
    level, recent = row.get("level"), row.get("recent") or []

    # their dominant RECENT champ (evidence for off-champ + heater attribution)
    champc = {}
    for cname, _win, _pos in recent:
        champc[cname] = champc.get(cname, 0) + 1
    top_champ, top_n = ("", 0)
    if champc:
        top_champ = max(champc, key=champc.get)
        top_n = champc[top_champ]

    # ---- THIS-GAME reads: the champ they locked today ----
    if row.get("scouted") and pts < 6000 and cg == 0:
        this_game.append((f"first {champ}? · {pts // 1000}k pts, 0 of last {n}" if n
                          else f"first {champ}? · {pts // 1000}k pts", tone(False)))
    if (n >= 8 and cg <= 1 and top_champ and top_n * 2 >= n
            and top_champ != champ):
        this_game.append((f"off-champ · {top_n} of last {n} on {top_champ}", tone(False)))
    if cg >= 4 and cw / cg <= 0.35:
        this_game.append((f"cold on {champ} · {cw}-{cg - cw} recent", tone(False)))
    elif cg >= 5:
        this_game.append((f"comfort · {cw}-{cg - cw} on {champ}", tone(cw * 2 >= cg)))
    if pts >= 250_000:
        this_game.append((f"{champ} OTP · {pts // 1000}k pts", tone(True)))
    elif pts >= 100_000:
        this_game.append((f"{champ} main · {pts // 1000}k pts", tone(True)))

    # ---- ACCOUNT reads: who this account is ----
    # smurf?: experienced player on a NEW account. Level is the load-bearing evidence
    # (ranked unlocks at 30; real smurfs sit in the fresh 30-60 band). No level -> no tag.
    smurfish = (level is not None and level <= 60 and n >= 8 and w / n >= 0.70
                and ((perf is not None and perf >= 75) or (cg >= 3 and cw / cg >= 0.7)))
    if smurfish:
        ev = f"lvl {level} · {w}-{n - w}"
        if perf is not None and perf >= 75:
            ev += f" · {int(perf)} perf"
        account.append((f"smurf? · {ev}", tone(True)))
    elif level is not None and level <= 60:
        account.append((f"new account · lvl {level}", "neutral"))
    elif 0 < sg <= 25:
        account.append((f"fresh ranked · {sg} games this season", "neutral"))
    # live streak, with champ attribution: a heater earned on a different champ than
    # today's is context, not a threat read on this pick
    if form:
        lead = 1
        while lead < len(form) and form[lead] == form[0]:
            lead += 1
        if lead >= 3:
            if form[0]:
                streak_champs = [c for c, _w2, _p in recent[:lead]]
                on_one = (streak_champs and streak_champs.count(max(
                    set(streak_champs), key=streak_champs.count)) * 10 >= 7 * len(streak_champs))
                hot = max(set(streak_champs), key=streak_champs.count) if on_one else ""
                if hot and hot != champ:
                    account.append((f"{lead}W heater · on {hot}", "neutral"))
                else:
                    account.append((f"{lead}W heater", tone(True)))
            else:
                account.append((f"{lead}L skid · tilt risk", tone(False)))
    # autofill / off-role
    mp = row.get("main_pos")
    if mp and row.get("role") and mp != row["role"]:
        account.append((f"off-role · {mp} main", tone(False)))
    # how they die (or don't)
    if dpg is not None and n >= 5:
        if dpg >= 6.5:
            account.append((f"bleeds · {dpg} deaths/game", tone(False)))
        elif dpg <= 2.6:
            account.append((f"hard to kill · {dpg} deaths/game", tone(True)))
    # how they actually play, independent of W/L (the sanctioned quality read)
    if perf is not None and not smurfish:
        if perf >= 85:
            account.append((f"carries · {int(perf)} avg perf", tone(True)))
        elif perf <= 45:
            account.append((f"passenger · {int(perf)} perf", tone(False)))
    # season shape
    if sg >= 400:
        account.append((f"grinder · {sg} ranked this season", "neutral"))
    if swr is not None and sg >= 100:
        if swr >= 55:
            account.append((f"climbing · {swr}% season", tone(True)))
        elif swr <= 45:
            account.append((f"hardstuck · {swr}% season", tone(False)))
    return this_game + account


_DUO_SHARED = 3          # same-team shared recent games = confirmed duo
_DUO_LOOSE = 2           # same-team shared recent games = probable duo ('duo?')


def _duo_pass(team_rows, key=None):
    """Cross-reference ONE TEAM's recent match ids: players sharing recent ranked games
    ON THE SAME SIDE of those games are queued together. 2 verified same-side games is
    already a strong read (10-game windows drift out of sync fast, which is how obvious
    duos were slipping through at the old 3-id-overlap bar) — it renders as 'duo?'; 3+ is
    confirmed. The tag cites its evidence per the tag spec (docs/TAGS.md)."""
    for i, a in enumerate(team_rows):
        for b in team_rows[i + 1:]:
            if not (a.get("mids") and b.get("mids")):
                continue
            shared = set(a["mids"]) & set(b["mids"])
            if len(shared) < _DUO_LOOSE:
                continue
            if key and a.get("puuid") and b.get("puuid"):
                same = ls.same_side_games(shared, a["puuid"], b["puuid"], key)
            else:
                same = len(shared)
            if same < _DUO_LOOSE:
                continue
            mark = "duo" if same >= _DUO_SHARED else "duo?"
            an = (a.get("player") or a.get("champ") or "?").split("#")[0]
            bn = (b.get("player") or b.get("champ") or "?").split("#")[0]
            a["tags"].insert(0, (f"{mark} · {bn} ({same} shared)", "info"))
            b["tags"].insert(0, (f"{mark} · {an} ({same} shared)", "info"))


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


def _wincons(dd, my, en):
    """The pre-game WIN/LOSE condition pair (§5): the one thing the loading screen can say
    that the live board doesn't — how this specific comp matchup is won and thrown."""
    mc, ec = _comp_read(dd, my), _comp_read(dd, en)
    if mc["scalers"] > ec["scalers"]:
        return {"win": "drag it late — farm, stall, don't coinflip; you out-scale at 3 items",
                "lose": "bleeding early kills before your spikes come online"}
    if ec["scalers"] > mc["scalers"]:
        return {"win": "end before 25 — turn every kill into towers and objectives",
                "lose": "letting it go late — their comp outgrows yours"}
    if mc["divers"] > ec["divers"]:
        return {"win": "force fights and picks — your comp hits harder in chaos",
                "lose": "letting them poke and siege on their own terms"}
    return {"win": "take the next neutral objective off a pick — trade cross-map",
            "lose": "coin-flipping 5v5s without vision or a numbers edge"}


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
                   "pts": 0, "mlevel": 0, "main_pos": "", "mids": [], "recent": [],
                   "level": None, "puuid": None}
            if key:
                try:
                    ign, lvl = _ign_for(port, hdr, row["sid"])
                    puuid = ls.resolve_puuid(ign, key) if ign else None
                    if puuid and len(puuid) > 70:
                        rec["player"] = ign
                        rec["level"] = lvl
                        rec["puuid"] = puuid
                        rec.update(_player_scout(dd, puuid, cid, key, riot_id=ign))
                        rec["scouted"] = True
                        rec["tags"] = _profile_tags(rec, ally)
                except Exception:
                    pass
            out.append(rec)
        return out
    allies, enemies = enrich(my, True), enrich(en, False)
    if key:
        _duo_pass(allies, key)
        _duo_pass(enemies, key)
    return {"allies": allies, "enemies": enemies,
            "plan": _plan(dd, my, en), "wincons": _wincons(dd, my, en),
            "scouted": bool(key)}
