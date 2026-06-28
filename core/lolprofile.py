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
            cached = json.load(open(fp))
            parts = cached.get("parts") if isinstance(cached, dict) else None
            if not parts or any("obj" not in p for p in parts):
                cached = None  # old cache format (before objective stats) -> refresh once
            if cached is not None:
                return cached
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
        obj = ((p.get("turretTakedowns", 0) or 0)
               + (p.get("inhibitorTakedowns", 0) or 0)
               + (p.get("dragonKills", 0) or 0)
               + (p.get("baronKills", 0) or 0)
               + (p.get("riftHeraldTakedowns", 0) or 0))
        parts.append({
            "puuid": p.get("puuid", ""), "champ": p.get("championName", ""),
            "win": bool(p.get("win")), "team": p.get("teamId", 0),
            "k": p.get("kills", 0), "d": p.get("deaths", 0), "a": p.get("assists", 0),
            "dmg": p.get("totalDamageDealtToChampions", 0) or 0,
            "gold": p.get("goldEarned", 0) or 0, "cs": cs,
            "vision": p.get("visionScore", 0) or 0,
            "obj": obj,
            "pos": (p.get("teamPosition") or "").upper(),
        })
    out = {"dur": info.get("gameDuration", 0), "parts": parts}
    try:
        json.dump(out, open(fp, "w"))
    except Exception:
        pass
    return out


def _grade_game(parts, mine, dur):
    """Role-aware, lobby-relative score (can exceed 100 for true carry games)."""
    mins = max(1.0, (dur or 0) / 60.0)
    def clamp(v, lo=0.0, hi=1.25):
        return max(lo, min(hi, float(v)))

    role = (mine.get("pos") or "").upper()
    if role == "MIDDLE":
        role = "MID"
    t = _ROLE_TARGETS.get(role, {"kp": 0.52, "dmg": 0.18, "obj": 0.17, "d10": 2.0, "csm": 5.6, "vpm": 0.9})

    team_k = {}
    team_dmg = {}
    team_gold = {}
    team_obj = {}
    for p in parts:
        tm = int(p.get("team") or 0)
        team_k[tm] = team_k.get(tm, 0.0) + float(p.get("k") or 0)
        team_dmg[tm] = team_dmg.get(tm, 0.0) + float(p.get("dmg") or 0)
        team_gold[tm] = team_gold.get(tm, 0.0) + float(p.get("gold") or 0)
        team_obj[tm] = team_obj.get(tm, 0.0) + float(p.get("obj") or 0)

    def raw_points(p):
        tm = int(p.get("team") or 0)
        k = float(p.get("k") or 0)
        a = float(p.get("a") or 0)
        d = float(p.get("d") or 0)
        kda = (k + a) / max(1.0, d)
        kp = (k + a) / max(1.0, team_k.get(tm, 1.0))
        dmg_share = float(p.get("dmg") or 0) / max(1.0, team_dmg.get(tm, 1.0))
        obj_share = float(p.get("obj") or 0) / max(1.0, team_obj.get(tm, 1.0))
        csm = float(p.get("cs") or 0) / mins
        vpm = float(p.get("vision") or 0) / mins
        d10 = d / mins * 10.0
        base = (
            22.0 * clamp(kda / 4.0) +
            18.0 * clamp(kp / max(0.01, t["kp"])) +
            14.0 * clamp(dmg_share / max(0.01, t["dmg"])) +
            10.0 * (1.0 if team_obj.get(tm, 0.0) < 3 else clamp(obj_share / max(0.01, t["obj"]), 0.0, 1.35)) +
            8.0 * clamp(csm / max(0.01, t["csm"]), 0.0, 1.20) +
            6.0 * clamp(vpm / max(0.01, t["vpm"]), 0.0, 1.20)
        )
        death_pen = max(0.0, d10 - t["d10"]) * 5.0
        return max(0.0, base - death_pen)

    raw = [raw_points(p) for p in parts]
    c = raw_points(mine)
    scores = sorted(raw, reverse=True)
    rank = 1 + sum(1 for s in scores if s > c + 1e-9)        # 1 = best in lobby
    lobby_avg = sum(raw) / max(1, len(raw))
    lobby_top = max(raw) if raw else c
    carry_bonus = max(0.0, c - lobby_avg) * 0.45
    if bool(mine.get("win")) and rank <= 2:
        carry_bonus += max(0.0, c - (lobby_top * 0.92)) * 0.7
    score = int(round(c + carry_bonus))

    if score >= 115:
        letter = "S+"
    elif score >= 100:
        letter = "S"
    elif score >= 85:
        letter = "A"
    elif score >= 70:
        letter = "B"
    elif score >= 55:
        letter = "C"
    else:
        letter = "D"
    if mine["win"] and rank <= 2 and score >= 104:
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


_ROLE_LABEL = {"TOP": "top", "JUNGLE": "jungle", "MID": "mid", "BOTTOM": "adc", "UTILITY": "support"}
_ROLE_TARGETS = {
    "TOP": {"kp": 0.46, "dmg": 0.20, "obj": 0.16, "d10": 2.2, "csm": 6.2, "vpm": 0.65},
    "JUNGLE": {"kp": 0.58, "dmg": 0.16, "obj": 0.28, "d10": 2.0, "csm": 5.0, "vpm": 0.95},
    "MID": {"kp": 0.55, "dmg": 0.24, "obj": 0.15, "d10": 2.0, "csm": 7.0, "vpm": 0.75},
    "BOTTOM": {"kp": 0.58, "dmg": 0.27, "obj": 0.18, "d10": 1.9, "csm": 7.2, "vpm": 0.70},
    "UTILITY": {"kp": 0.62, "dmg": 0.08, "obj": 0.22, "d10": 1.8, "csm": 1.2, "vpm": 1.80},
}
_ROLE_WIN_CONDITION = {
    "TOP": "Use your lead to pressure side lane and force numbers advantage.",
    "JUNGLE": "Convert tempo into neutral control and first move on river fights.",
    "MID": "Crash waves then move first; your tempo should decide side skirmishes.",
    "BOTTOM": "Play around item spikes and front-to-back positioning in objective fights.",
    "UTILITY": "Own vision timings and engage/peel windows before every objective.",
}


def review_for_player(parts, my_puuid, dur):
    """Role/champ-aware top-3 review notes. A/S games get strengths, otherwise improvements."""
    mine = next((p for p in parts if p.get("puuid") == my_puuid), None)
    if not mine:
        return {"kind": "improve", "tips": []}
    mins = max(1.0, (dur or 0) / 60.0)
    team = int(mine.get("team") or 0)
    team_k = sum(int(p.get("k") or 0) for p in parts if int(p.get("team") or 0) == team)
    team_dmg = sum(float(p.get("dmg") or 0) for p in parts if int(p.get("team") or 0) == team)
    my_obj = float(mine.get("obj") or 0)
    team_obj = sum(float(p.get("obj") or 0) for p in parts if int(p.get("team") or 0) == team)
    kp = (float(mine.get("k") or 0) + float(mine.get("a") or 0)) / max(1.0, float(team_k))
    dmg_share = float(mine.get("dmg") or 0) / max(1.0, float(team_dmg))
    obj_share = my_obj / max(1.0, team_obj)
    d10 = float(mine.get("d") or 0) / mins * 10.0
    csm = float(mine.get("cs") or 0) / mins
    vpm = float(mine.get("vision") or 0) / mins
    pos = (mine.get("pos") or "").upper()
    if pos == "MIDDLE":
        pos = "MID"
    role_cfg = _ROLE_TARGETS.get(pos, {"kp": 0.52, "dmg": 0.18, "obj": 0.17, "d10": 2.0, "csm": 5.6, "vpm": 0.9})
    champ = mine.get("champ", "your champ")
    role_name = _ROLE_LABEL.get(pos, "role")
    score, letter, _label, _rank = _grade_game(parts, mine, dur)
    positive = letter in ("A", "S", "S+")
    lane_opp = next((p for p in parts if int(p.get("team") or 0) != team and (p.get("pos") or "").upper() == pos), None)
    cands = []
    if positive:
        if d10 <= role_cfg["d10"]:
            cands.append(("deaths", role_cfg["d10"] - d10 + 0.05,
                          f"{champ} {role_name}: strong discipline at {d10:.1f} deaths/10m."))
        if kp >= role_cfg["kp"]:
            cands.append(("kp", kp - role_cfg["kp"] + 0.05,
                          f"{champ}: high fight impact ({kp*100:.0f}% KP) kept your team in every skirmish."))
        if dmg_share >= role_cfg["dmg"]:
            cands.append(("dmg", dmg_share - role_cfg["dmg"] + 0.05,
                          f"{champ}: carried damage load ({dmg_share*100:.0f}% share) for your role."))
        if team_obj >= 3 and obj_share >= role_cfg["obj"]:
            cands.append(("obj", obj_share - role_cfg["obj"] + 0.05,
                          f"{champ}: objective impact was excellent ({obj_share*100:.0f}% participation share)."))
        if csm >= role_cfg["csm"]:
            cands.append(("farm", (csm - role_cfg["csm"]) / 10.0 + 0.03,
                          f"{champ}: efficient economy ({csm:.1f} CS/min) kept your spikes on time."))
        if lane_opp and pos in ("TOP", "MID", "BOTTOM"):
            od = float(lane_opp.get("dmg") or 0)
            if mine.get("dmg", 0) > od:
                cands.append(("lane", (mine.get("dmg", 0) - od) / max(1.0, od) + 0.03,
                              f"{champ}: you out-pressured lane counterpart in damage ({int(mine.get('dmg', 0)//1000)}k vs {int(od//1000)}k)."))
    else:
        if d10 > role_cfg["d10"]:
            cands.append(("deaths", d10 - role_cfg["d10"] + 0.05,
                          f"{champ} {role_name}: deaths were high ({d10:.1f}/10m). Hold cooldowns for second engage windows."))
        if kp < role_cfg["kp"]:
            cands.append(("kp", role_cfg["kp"] - kp + 0.05,
                          f"{champ}: KP was {kp*100:.0f}% (target ~{int(role_cfg['kp']*100)}%). Move earlier on river/side fights."))
        if dmg_share < role_cfg["dmg"]:
            cands.append(("dmg", role_cfg["dmg"] - dmg_share + 0.05,
                          f"{champ}: damage share was low ({dmg_share*100:.0f}%). Take more front-half trades around power spikes."))
        if team_obj >= 3 and obj_share < role_cfg["obj"]:
            cands.append(("obj", role_cfg["obj"] - obj_share + 0.05,
                          f"{champ}: objective involvement lagged ({obj_share*100:.0f}% share). Be first to setup at spawn timers."))
        if pos != "UTILITY" and csm < role_cfg["csm"]:
            cands.append(("farm", (role_cfg["csm"] - csm) / 10.0 + 0.03,
                          f"{champ}: farm pace was {csm:.1f} CS/min. Protect side waves before forcing next play."))
        if pos in ("JUNGLE", "UTILITY") and vpm < role_cfg["vpm"]:
            cands.append(("vision", (role_cfg["vpm"] - vpm) / 3.0 + 0.03,
                          f"{champ}: vision tempo was low ({vpm:.2f}/min). Reset earlier for control wards before objectives."))
        if lane_opp and pos in ("TOP", "MID", "BOTTOM"):
            od = float(lane_opp.get("dmg") or 0)
            if mine.get("dmg", 0) < od * 0.85:
                cands.append(("lane", (od - mine.get("dmg", 0)) / max(1.0, od) + 0.04,
                              f"{champ}: lane pressure was behind ({int(mine.get('dmg', 0)//1000)}k vs {int(od//1000)}k). Contest prio on better windows."))
    cands.append(("identity", 0.01, f"{champ} win condition: {_ROLE_WIN_CONDITION.get(pos, _ROLE_WIN_CONDITION['MID'])}"))
    cands.sort(key=lambda x: x[1], reverse=True)
    seen, out = set(), []
    for k, _w, txt in cands:
        if k in seen:
            continue
        seen.add(k)
        out.append(txt)
        if len(out) >= 3:
            break
    return {"kind": ("positive" if positive else "improve"), "tips": out}


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
        review = review_for_player(d["parts"], puuid, d.get("dur", 0))
        games.append({"champ": mine["champ"], "win": mine["win"], "k": mine["k"], "d": mine["d"],
                      "a": mine["a"], "score": score, "letter": letter, "label": label,
                      "rank": lobby_rank, "pos": mine["pos"], "mid": mid,
                      "dur": d.get("dur", 0), "review": review.get("tips", []),
                      "review_kind": review.get("kind", "improve")})
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
