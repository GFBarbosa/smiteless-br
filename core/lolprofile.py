#!/usr/bin/env python3
"""lolprofile.py - your "home" page data: who you are (from the live client), your rank,
recent form, champion win rates, and a per-game performance SCORE graded against the whole
lobby (how hard did you carry?). Pure Riot API via lolscout's rate-limited client.
"""
import json
import ssl
import base64
import urllib.request

import lolscout as ls
import phasecheck

_ctx = ssl._create_unverified_context()


def current_riot_id():
    """'GameName#TAG' of the logged-in summoner via the LCU, or None if the client is closed."""
    lf = phasecheck._lockfile()
    if not lf:
        return None
    try:
        _n, _p, port, pw, _proto = open(lf).read().split(":")
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        req = urllib.request.Request(
            f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=4, context=_ctx) as r:
            d = json.load(r)
        gn, tl = d.get("gameName"), d.get("tagLine")
        return f"{gn}#{tl}" if gn and tl else None
    except Exception:
        return None


def match_detail(mid, key):
    """Full per-participant stats for a match (cached forever - match data is immutable)."""
    fp = ls._cache_path("matchx", mid)
    import os
    if os.path.exists(fp):
        try:
            return json.load(open(fp))
        except Exception:
            pass
    d = ls._get(f"https://{ls.REGIONAL}.api.riotgames.com/lol/match/v5/matches/{mid}", key)
    if not d or "info" not in d:
        return None
    info = d["info"]
    if info.get("gameMode") not in ("CLASSIC", None) or (info.get("gameDuration", 0) or 0) < 300:
        out = {"skip": True}                     # ARAM / remakes don't belong on a SR profile
        try:
            json.dump(out, open(fp, "w"))
        except Exception:
            pass
        return out
    parts = []
    for p in info["participants"]:
        cs = (p.get("totalMinionsKilled", 0) or 0) + (p.get("neutralMinionsKilled", 0) or 0)
        parts.append({
            "puuid": p.get("puuid", ""), "champ": p.get("championName", ""),
            "win": bool(p.get("win")), "team": p.get("teamId", 0),
            "k": p.get("kills", 0), "d": p.get("deaths", 0), "a": p.get("assists", 0),
            "dmg": p.get("totalDamageDealtToChampions", 0) or 0,
            "gold": p.get("goldEarned", 0) or 0, "cs": cs,
            "vision": p.get("visionScore", 0) or 0,
            "pos": (p.get("teamPosition") or "").upper(),
        })
    out = {"dur": info.get("gameDuration", 0), "parts": parts}
    try:
        json.dump(out, open(fp, "w"))
    except Exception:
        pass
    return out


def _grade_game(parts, mine, dur):
    """Score 0-100 + letter + label for `mine`, ranked against everyone in the lobby."""
    mins = max(1.0, (dur or 0) / 60.0)
    team_k = {1: 0, 200: 0}
    for p in parts:
        team_k[p["team"]] = team_k.get(p["team"], 0) + p["k"]
    mx = lambda key: max((p[key] for p in parts), default=1) or 1
    md, mg, mc = mx("dmg"), mx("gold"), mx("cs")

    def composite(p):
        kda = (p["k"] + p["a"]) / max(1, p["d"])
        kp = (p["k"] + p["a"]) / max(1, team_k.get(p["team"], 1))
        return (0.30 * min(kda / 5.0, 1.0) + 0.25 * min(kp, 1.0)
                + 0.25 * p["dmg"] / md + 0.10 * p["gold"] / mg + 0.10 * p["cs"] / mc)

    scores = sorted((composite(p) for p in parts), reverse=True)
    c = composite(mine)
    rank = 1 + sum(1 for s in scores if s > c + 1e-9)        # 1 = best in lobby
    score = int(round(c * 100))
    if score >= 82:
        letter = "S+"
    elif score >= 72:
        letter = "S"
    elif score >= 60:
        letter = "A"
    elif score >= 46:
        letter = "B"
    elif score >= 32:
        letter = "C"
    else:
        letter = "D"
    if mine["win"] and rank <= 2 and score >= 78:
        label = "hard carry"
    elif mine["win"] and rank <= 3:
        label = "carried"
    elif not mine["win"] and rank <= 2:
        label = "carried, team lost"
    elif rank >= 9:
        label = "rough one"
    elif not mine["win"] and rank >= 7:
        label = "could've done better"
    else:
        label = "solid" if score >= 55 else "okay"
    return score, letter, label, rank


def build_profile(dd, key=None, count=14):
    """The whole home page: {riot_id, rank, recent(W-L), champs[], games[], avg_score}. None
    if we can't tell who you are (client closed)."""
    key = key or ls.read_key()
    if not key:
        return {"error": "no Riot API key"}
    rid = current_riot_id()
    if not rid:
        return None
    puuid = ls.resolve_puuid(rid, key)
    if not puuid:
        return {"riot_id": rid, "error": "couldn't resolve account (key valid?)"}
    rk = ls.rank(puuid, key)
    ids = ls.recent_ids(puuid, key, count) or []
    games, champ = [], {}
    wins = 0
    for mid in ids:
        d = match_detail(mid, key)
        if not d or d.get("skip"):
            continue
        mine = next((p for p in d["parts"] if p["puuid"] == puuid), None)
        if not mine:
            continue
        score, letter, label, lobby_rank = _grade_game(d["parts"], mine, d["dur"])
        games.append({"champ": mine["champ"], "win": mine["win"], "k": mine["k"], "d": mine["d"],
                      "a": mine["a"], "score": score, "letter": letter, "label": label,
                      "rank": lobby_rank, "pos": mine["pos"], "mid": mid,
                      "dur": d.get("dur", 0)})
        wins += 1 if mine["win"] else 0
        cs = champ.setdefault(mine["champ"], {"g": 0, "w": 0, "score": 0})
        cs["g"] += 1
        cs["w"] += 1 if mine["win"] else 0
        cs["score"] += score
    n = len(games)
    champs = sorted(
        ({"champ": c, "g": v["g"], "w": v["w"], "wr": round(v["w"] / v["g"] * 100),
          "avg": round(v["score"] / v["g"])} for c, v in champ.items()),
        key=lambda x: (-x["g"], -x["wr"]))
    return {"riot_id": rid, "puuid": puuid, "rank": rk, "n": n, "wins": wins, "losses": n - wins,
            "wr": round(wins / n * 100) if n else 0,
            "avg_score": round(sum(g["score"] for g in games) / n) if n else 0,
            "champs": champs[:6], "games": games}
