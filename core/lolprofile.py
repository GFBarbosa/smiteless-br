#!/usr/bin/env python3
"""lolprofile.py - your "home" page data: who you are (from the live client), your rank,
recent form, champion win rates, and a per-game performance SCORE graded against the whole
lobby (how hard did you carry?). Pure Riot API via lolscout's rate-limited client.
"""
import os
import time
import json
import ssl
import base64
import urllib.request

import lolscout as ls
import phasecheck

_ctx = ssl._create_unverified_context()

# ---- rank -> single monotonic value, for the LP trend sparkline and session LP swing ----
_TIER_ORDER = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND",
               "MASTER", "GRANDMASTER", "CHALLENGER"]
_DIV_VAL = {"IV": 0, "III": 1, "II": 2, "I": 3, "": 3}
LP_HISTORY = os.path.expanduser("~/.claude/cache/lol_lp_history.json")
SESSION_GAP = 3 * 3600       # a >3h break starts a new "session"
TILT_STREAK = 3              # this many losses in a row trips the take-a-break nudge


def _rank_value(rk):
    """One number that orders any rank (tier*div*lp) so we can graph it / diff a session."""
    if not rk or not rk.get("tier"):
        return None
    t = (rk["tier"] or "").upper()
    if t not in _TIER_ORDER:
        return None
    base = _TIER_ORDER.index(t) * 400
    if t in ("MASTER", "GRANDMASTER", "CHALLENGER"):
        return base + int(rk.get("lp", 0) or 0)          # apex: no division, lp can exceed 100
    return base + _DIV_VAL.get(rk.get("div", ""), 0) * 100 + int(rk.get("lp", 0) or 0)


def _lp_history(rk):
    """Append a snapshot of the current rank (deduped) and return the full history list."""
    try:
        hist = json.load(open(LP_HISTORY))
        if not isinstance(hist, list):
            hist = []
    except Exception:
        hist = []
    rv = _rank_value(rk)
    if rv is not None:
        w, l = int((rk or {}).get("w", 0) or 0), int((rk or {}).get("l", 0) or 0)
        last = hist[-1] if hist else None
        changed = (not last) or last.get("rv") != rv or last.get("w") != w or last.get("l") != l
        if changed:
            hist.append({"ts": int(time.time()), "rv": rv, "w": w, "l": l,
                         "lp": int(rk.get("lp", 0) or 0), "tier": rk.get("tier"), "div": rk.get("div")})
            hist = hist[-250:]
            try:
                os.makedirs(os.path.dirname(LP_HISTORY), exist_ok=True)
                json.dump(hist, open(LP_HISTORY, "w"))
            except Exception:
                pass
    return hist


def _session(hist, games):
    """{games, wins, losses, lp_delta, streak, tilt} for the current play session.
    Session = the contiguous run of recent snapshots with no >SESSION_GAP break. Streak/tilt
    come from the games list (most-recent first), which is exact even with no rank history."""
    streak = 0
    if games:
        first = games[0]["win"]
        for g in games:
            if g["win"] == first:
                streak += 1
            else:
                break
    streak_signed = streak if (games and games[0]["win"]) else -streak
    tilt = bool(games and not games[0]["win"] and streak >= TILT_STREAK)
    out = {"games": 0, "wins": 0, "losses": 0, "lp_delta": None,
           "streak": streak_signed, "tilt": tilt}
    if len(hist) >= 2:
        start = hist[-1]
        for i in range(len(hist) - 1, 0, -1):
            if hist[i]["ts"] - hist[i - 1]["ts"] > SESSION_GAP:
                start = hist[i]
                break
            start = hist[i - 1]
        cur = hist[-1]
        out["wins"] = max(0, cur.get("w", 0) - start.get("w", 0))
        out["losses"] = max(0, cur.get("l", 0) - start.get("l", 0))
        out["games"] = out["wins"] + out["losses"]
        if cur.get("rv") is not None and start.get("rv") is not None:
            out["lp_delta"] = cur["rv"] - start["rv"]
    return out


def _coach(champs):
    """{more, less, slump} pool advice from per-champ win rates. Sample-gated (3+ games each
    way) so one lucky game never drives a suggestion. Crucially: your DOMINANT MAIN never
    gets "ease off" - a one-trick on a bad run is a slump, not a pick problem - it gets a
    'slump' note instead ("rough patch on X - likely variance, not the pick")."""
    pool = [c for c in champs if c.get("g", 0) >= 3]
    if not pool:
        return None
    total = sum(c.get("g", 0) for c in champs)
    second = sorted((c.get("g", 0) for c in champs), reverse=True)[1] if len(champs) > 1 else 0
    def is_main(c):
        return c.get("g", 0) >= max(3, int(total * 0.4)) or (second and c.get("g", 0) >= 2 * second)
    best = max(pool, key=lambda c: (c["wr"], c["g"]))
    worst = min(pool, key=lambda c: (c["wr"], -c["g"]))
    out = {}
    if best["wr"] >= 55:
        out["more"] = {"champ": best["champ"], "wr": best["wr"], "g": best["g"]}
    if worst["wr"] <= 45 and worst["champ"] != (out.get("more") or {}).get("champ"):
        if is_main(worst):
            out["slump"] = {"champ": worst["champ"], "wr": worst["wr"], "g": worst["g"]}
        else:
            out["less"] = {"champ": worst["champ"], "wr": worst["wr"], "g": worst["g"]}
    return out or None


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
    if os.path.exists(fp):
        try:
            cached = json.load(open(fp))
            parts = cached.get("parts") if isinstance(cached, dict) else None
            if not parts or any(("obj" not in p or "name" not in p) for p in parts):
                cached = None  # old cache format (pre-objective / pre-name+items) -> refresh once
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
        gn, tl = p.get("riotIdGameName") or "", p.get("riotIdTagline") or ""
        name = f"{gn}#{tl}" if (gn and tl) else (gn or p.get("summonerName") or "")
        items = [p.get(f"item{j}", 0) or 0 for j in range(6)]
        parts.append({
            "puuid": p.get("puuid", ""), "champ": p.get("championName", ""),
            "name": name,
            "win": bool(p.get("win")), "team": p.get("teamId", 0),
            "k": p.get("kills", 0), "d": p.get("deaths", 0), "a": p.get("assists", 0),
            "dmg": p.get("totalDamageDealtToChampions", 0) or 0,
            "gold": p.get("goldEarned", 0) or 0, "cs": cs,
            "vision": p.get("visionScore", 0) or 0,
            "obj": obj,
            "items": [i for i in items if i],
            "pos": (p.get("teamPosition") or "").upper(),
        })
    out = {"dur": info.get("gameDuration", 0), "parts": parts}
    try:
        json.dump(out, open(fp, "w"))
    except Exception:
        pass
    return out


def _grade_game(parts, mine, dur):
    """ABSOLUTE, goal-based score: how YOU performed against your role's benchmarks - never
    ranked against the lobby, so the same game scores the same no matter how the other nine
    did. KP / damage share / objective share are your personal participation measured against
    a role TARGET (a standard stat you control by playing well), not a comparison of who
    out-scored whom. ~85 = you hit your role's goals; 100+ = you blew past them; <55 = off."""
    mins = max(1.0, (dur or 0) / 60.0)
    def clamp(v, lo=0.0, hi=1.5):
        return max(lo, min(hi, float(v)))

    role = (mine.get("pos") or "").upper()
    if role == "MIDDLE":
        role = "MID"
    t = _ROLE_TARGETS.get(role, {"kp": 0.52, "dmg": 0.18, "obj": 0.17, "d10": 2.0, "csm": 5.6, "vpm": 0.9})

    team = int(mine.get("team") or 0)
    team_k = sum(float(p.get("k") or 0) for p in parts if int(p.get("team") or 0) == team)
    team_dmg = sum(float(p.get("dmg") or 0) for p in parts if int(p.get("team") or 0) == team)
    team_obj = sum(float(p.get("obj") or 0) for p in parts if int(p.get("team") or 0) == team)

    k = float(mine.get("k") or 0)
    a = float(mine.get("a") or 0)
    d = float(mine.get("d") or 0)
    kda = (k + a) / max(1.0, d)
    kp = (k + a) / max(1.0, team_k)
    dmg_share = float(mine.get("dmg") or 0) / max(1.0, team_dmg)
    obj_share = float(mine.get("obj") or 0) / max(1.0, team_obj)
    csm = float(mine.get("cs") or 0) / mins
    vpm = float(mine.get("vision") or 0) / mins
    d10 = d / mins * 10.0

    base = (
        24.0 * clamp(kda / 4.0) +
        20.0 * clamp(kp / max(0.01, t["kp"])) +
        16.0 * clamp(dmg_share / max(0.01, t["dmg"])) +
        12.0 * (1.0 if team_obj < 3 else clamp(obj_share / max(0.01, t["obj"]))) +
        8.0 * clamp(csm / max(0.01, t["csm"]), 0.0, 1.3) +
        6.0 * clamp(vpm / max(0.01, t["vpm"]), 0.0, 1.3)
    )
    death_pen = max(0.0, d10 - t["d10"]) * 5.0
    raw = max(0.0, base - death_pen) + (6.0 if mine.get("win") else -2.0)   # winning is the goal
    score = int(round(max(0.0, raw)))

    letter = ("S+" if score >= 115 else "S" if score >= 100 else "A" if score >= 85
              else "B" if score >= 70 else "C" if score >= 55 else "D")
    if mine.get("win"):
        label = ("hard carry" if score >= 115 else "carried" if score >= 100
                 else "great game" if score >= 85 else "solid win" if score >= 70
                 else "decent game" if score >= 55 else "scrappy win")
    else:
        label = ("carried, lost" if score >= 100 else "great game, lost" if score >= 85
                 else "kept fighting" if score >= 70 else "tough loss" if score >= 55
                 else "rough game")
    return score, letter, label


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
    score, letter, _label = _grade_game(parts, mine, dur)
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


def build_profile(dd, key=None, count=14, riot_id=None, puuid=None):
    """The whole home page: {riot_id, rank, recent(W-L), champs[], games[], avg_score}.
    With riot_id/puuid it builds ANY player's profile (search / click-through); session,
    LP trend and the tilt nudge are self-only (they come from the local snapshot history).
    None if we can't tell who you are (client closed)."""
    key = key or ls.read_key()
    if not key:
        return {"error": "no Riot API key — add one in Settings"}
    try:
        ls.ensure_key_namespace(key)      # key rotated? old caches hold old-key puuids -> wipe
        other = bool(riot_id or puuid)
        rid = riot_id
        if not other:
            rid = current_riot_id()
            if not rid:
                return None
        if not puuid:
            puuid = ls.resolve_puuid(rid, key)
        if not puuid:
            return {"riot_id": rid, "error": "couldn't find that player — expired key? (check Settings)"}
        rk = ls.rank(puuid, key)
        # ALL queues, not just ranked solo - normals/flex players have match histories too.
        # match_detail keeps only Summoner's Rift (CLASSIC) games.
        ids = ls.recent_ids(puuid, key, count, queue="all") or []
    except ls.KeyStale:
        return {"riot_id": rid if 'rid' in dir() else None,
                "error": "your Riot API key expired — paste a new one in Settings"}
    games, champ = [], {}
    wins = 0
    for mid in ids:
        d = match_detail(mid, key)
        if not d or d.get("skip"):
            continue
        mine = next((p for p in d["parts"] if p["puuid"] == puuid), None)
        if not mine:
            continue
        if other and not rid and mine.get("name"):
            rid = mine["name"]                     # clicked-through by puuid: recover the name
        score, letter, label = _grade_game(d["parts"], mine, d["dur"])
        review = review_for_player(d["parts"], puuid, d.get("dur", 0))
        team = int(mine.get("team") or 0)
        team_k = sum(int(p.get("k") or 0) for p in d["parts"] if int(p.get("team") or 0) == team)
        team_dmg = sum(float(p.get("dmg") or 0) for p in d["parts"] if int(p.get("team") or 0) == team)
        mins = max(1.0, (d.get("dur", 0) or 0) / 60.0)
        games.append({"champ": mine["champ"], "win": mine["win"], "k": mine["k"], "d": mine["d"],
                      "a": mine["a"], "score": score, "letter": letter, "label": label,
                      "pos": mine["pos"], "mid": mid,
                      "dur": d.get("dur", 0), "review": review.get("tips", []),
                      "review_kind": review.get("kind", "improve"),
                      "cs": mine.get("cs", 0), "csm": round(mine.get("cs", 0) / mins, 1),
                      "dmg": mine.get("dmg", 0), "vision": mine.get("vision", 0),
                      "kp": round((mine["k"] + mine["a"]) / max(1.0, float(team_k)) * 100),
                      "dmg_share": round(float(mine.get("dmg", 0)) / max(1.0, team_dmg) * 100)})
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
    # session / LP trend come from the LOCAL snapshot history -> self-profile only
    hist = [] if other else _lp_history(rk)
    trend = [h["rv"] for h in hist[-24:] if h.get("rv") is not None]   # LP sparkline (#8)
    # profile-wide averages + role split (for the header/averages strip)
    avgs = {}
    if n:
        tk_ = sum(g["k"] for g in games)
        td = sum(g["d"] for g in games)
        ta = sum(g["a"] for g in games)
        avgs = {"kda": round((tk_ + ta) / max(1, td), 2),
                "k": round(tk_ / n, 1), "d": round(td / n, 1), "a": round(ta / n, 1),
                "kp": round(sum(g.get("kp", 0) for g in games) / n),
                "csm": round(sum(g.get("csm", 0) for g in games) / n, 1),
                "dmg_share": round(sum(g.get("dmg_share", 0) for g in games) / n)}
    roles = {}
    for g in games:
        pos = (g.get("pos") or "").upper()
        if pos:
            roles[pos] = roles.get(pos, 0) + 1
    return {"riot_id": rid or "?", "puuid": puuid, "rank": rk, "n": n, "wins": wins,
            "losses": n - wins, "other": other,
            "wr": round(wins / n * 100) if n else 0,
            "avg_score": round(sum(g["score"] for g in games) / n) if n else 0,
            "champs": champs[:6], "games": games, "avgs": avgs, "roles": roles,
            "session": (None if other else _session(hist, games)),
            "coach": _coach(champs), "lp_trend": trend}


SEASON_START = 1767225600   # 2026-01-01 UTC - season 16; update at the next season rollover
_SR_QUEUES = {400, 420, 430, 440, 480, 490, 700}   # Summoner's Rift queues (normals/ranked/swift)


def season_champs(dd, puuid, key, cap=60):
    """Top champions across THE SEASON (not just the games on screen): one ids call
    (startTime-filtered, up to 100) + permanently-cached match results. Returns
    [{champ, g, w, wr}] sorted by games. Partial data on a throttled dev key still works."""
    try:
        ids = ls._get(f"https://{ls.REGIONAL}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
                      f"{puuid}/ids?startTime={SEASON_START}&start=0&count=100", key) or []
    except ls.KeyStale:
        return []
    agg = {}
    for mid in ids[:cap]:
        try:
            res = ls.match_results(mid, key)
        except ls.KeyStale:
            break
        if not res or puuid not in res:
            continue
        q = res.get("_q")
        if q is not None and q not in _SR_QUEUES:   # skip ARAM/arena (old caches lack _q -> keep)
            continue
        win, cname = res[puuid]
        c = agg.setdefault(cname, {"g": 0, "w": 0})
        c["g"] += 1
        c["w"] += 1 if win else 0
    out = sorted(({"champ": c, "g": v["g"], "w": v["w"],
                   "wr": round(v["w"] / v["g"] * 100)} for c, v in agg.items()),
                 key=lambda x: (-x["g"], -x["wr"]))
    return out


DUO_SHARED = 3             # shared recent matches to call two players a likely duo


def match_duos(parts, key, count=10):
    """{puuid: group_index} for players in this PAST match who look like premades - same
    inference the live scout uses: pairs on the same team sharing several recent ranked
    games. All recent_ids calls are cached, so an expanded game costs at most 10 lookups."""
    ids_of = {}
    for p in parts:
        pu = p.get("puuid")
        if pu:
            try:
                ids_of[pu] = set(ls.recent_ids(pu, key, count) or [])
            except Exception:
                ids_of[pu] = set()
    groups, gidx = {}, 0
    plist = [p for p in parts if p.get("puuid")]
    for i, a in enumerate(plist):
        for b in plist[i + 1:]:
            if int(a.get("team") or 0) != int(b.get("team") or 0):
                continue
            shared = len(ids_of.get(a["puuid"], set()) & ids_of.get(b["puuid"], set()))
            if shared >= DUO_SHARED:
                ga, gb = groups.get(a["puuid"]), groups.get(b["puuid"])
                g = ga if ga is not None else (gb if gb is not None else gidx)
                if ga is None and gb is None:
                    gidx += 1
                groups[a["puuid"]] = g
                groups[b["puuid"]] = g
    return groups
