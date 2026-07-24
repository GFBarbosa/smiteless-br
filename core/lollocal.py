#!/usr/bin/env python3
"""lollocal.py — YOUR match history straight from the League client (LCU).

Riot's public Match-V5 lives on the regional host, which Cloudflare-gates and rate-limits;
when it's down the profile can't resolve a puuid at all and (misleadingly) blames the API key.
But the client sitting on this machine already HAS your match history — it renders it in the
client's own Match History tab — and it needs no key, no internet round-trip to Riot's edge,
and it never 403s. So for YOUR OWN profile the client is a better source than the web API.

Two endpoints do the work:
  /lol-match-history/v1/products/lol/current-summoner/matches  -> your recent games (list;
      Riot only returns YOUR participant row here, so it's used just for the game ids)
  /lol-match-history/v1/games/{gameId}                          -> the FULL game: all ten
      participants + identities (real Name#TAG), which is what the grade needs for team shares

Everything is normalized to the exact shape lolprofile.match_detail() returns, so the profile's
grading/review pipeline consumes it unchanged.

CAVEAT — puuid namespace: the LCU hands out plain 36-char account UUIDs, NOT Riot's per-API-key
ENCRYPTED puuids. The two never match, so LCU-sourced games are cached separately (kind
'lcumatch') and a profile built from this source must use my_puuid() as "me" throughout.
"""
import os, json, time

import lolgame as lg
import lolbuild as lb
import lolscout as ls

# Summoner's Rift queues (ranked solo/flex, drafts, blind, swiftplay) — ARAM etc. never
# belong on an SR profile, same rule lolprofile.match_detail applies to Riot data.
RANKED_SOLO = 420
SR_QUEUES = {400, 420, 430, 440, 480, 490, 700}
MIN_DUR = 300               # sub-5-minute games are remakes


def _get(path, timeout=6):
    lc = lg._lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        return lb.http(f"https://127.0.0.1:{port}{path}", headers=hdr,
                       timeout=timeout, insecure=True)
    except Exception:
        return None


def available():
    """True when the client is up and answering — i.e. this source can be used at all."""
    return _get("/lol-summoner/v1/current-summoner", timeout=3) is not None


def my_puuid():
    """Your LCU (plain, unencrypted) puuid — the id that identifies YOU inside LCU game data."""
    d = _get("/lol-summoner/v1/current-summoner", timeout=4)
    return (d or {}).get("puuid") or None


def my_riot_id():
    d = _get("/lol-summoner/v1/current-summoner", timeout=4) or {}
    gn, tl = d.get("gameName"), d.get("tagLine")
    return f"{gn}#{tl}" if gn and tl else None


def rank():
    """Solo-queue rank in ls.rank()'s shape ({tier, div, lp, w, l}) or None — read off the
    client, so it works with the Riot API completely down."""
    d = _get("/lol-ranked/v1/current-ranked-stats", timeout=5)
    q = ((d or {}).get("queueMap") or {}).get("RANKED_SOLO_5x5") or {}
    if not q.get("tier"):
        return None
    tier = str(q["tier"]).upper()
    if tier in ("NONE", "UNRANKED", ""):
        return None
    return {"tier": tier, "div": q.get("division", "") or "",
            "lp": int(q.get("leaguePoints", 0) or 0),
            "w": int(q.get("wins", 0) or 0), "l": int(q.get("losses", 0) or 0)}


def recent_game_ids(count=14, ranked_only=True):
    """Your recent game ids (most-recent first) from the client. The list endpoint returns
    only your own participant row per game, so it's used purely to enumerate ids — the full
    game is fetched per id below. Over-fetches, because ARAM/remakes get filtered out."""
    want = max(count * 3, count + 10)          # headroom for filtered queues/remakes
    d = _get(f"/lol-match-history/v1/products/lol/current-summoner/matches"
             f"?begIndex=0&endIndex={want}", timeout=10)
    games = ((d or {}).get("games") or {}).get("games") or []
    out = []
    for g in games:
        q = g.get("queueId")
        if ranked_only and q != RANKED_SOLO:
            continue
        if not ranked_only and q not in SR_QUEUES:
            continue
        if g.get("gameMode") not in ("CLASSIC", None):
            continue
        if (g.get("gameDuration") or 0) < MIN_DUR:
            continue
        if g.get("gameId"):
            out.append(int(g["gameId"]))
    return out


_POS = {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MIDDLE", "MID": "MIDDLE",
        "BOTTOM": "BOTTOM", "BOT": "BOTTOM"}


def _position(tl):
    """Riot-style teamPosition from the LCU's (lane, role) pair, so the grade's role
    benchmarks key the same way they do on Match-V5 data."""
    lane = _POS.get(str((tl or {}).get("lane") or "").upper(), "")
    role = str((tl or {}).get("role") or "").upper()
    if lane == "BOTTOM" and role == "DUO_SUPPORT":
        return "UTILITY"
    return lane


def game_detail(dd, gid):
    """One full game in lolprofile.match_detail()'s shape:
       {dur, ts, parts: [{puuid, champ, name, win, team, k, d, a, dmg, gold, cs, vision,
                          obj, items, pos}]}
    or {'skip': True} for ARAM/remakes, or None if the client couldn't serve it. Cached
    forever under its own kind — LCU puuids are a different namespace from Riot's."""
    fp = ls._cache_path("lcumatch", str(gid))
    if os.path.exists(fp):
        try:
            return json.load(open(fp, encoding="utf-8"))
        except Exception:
            pass
    g = _get(f"/lol-match-history/v1/games/{gid}", timeout=10)
    if not g or not g.get("participants"):
        return None
    if g.get("gameMode") not in ("CLASSIC", None) or (g.get("gameDuration") or 0) < MIN_DUR:
        out = {"skip": True}
        try:
            json.dump(out, open(fp, "w", encoding="utf-8"))
        except Exception:
            pass
        return out
    ident = {i.get("participantId"): (i.get("player") or {})
             for i in (g.get("participantIdentities") or [])}
    parts = []
    for p in g["participants"]:
        st = p.get("stats") or {}
        pl = ident.get(p.get("participantId")) or {}
        gn, tl_ = pl.get("gameName") or "", pl.get("tagLine") or ""
        name = f"{gn}#{tl_}" if (gn and tl_) else (gn or pl.get("summonerName") or "")
        cs = int(st.get("totalMinionsKilled", 0) or 0) + int(st.get("neutralMinionsKilled", 0) or 0)
        # NOTE: the LCU stat block carries turret/inhibitor kills but no per-player
        # dragon/baron/herald attribution (Match-V5 does), so objective share on this path
        # is turrets+inhibitors only — slightly conservative, never wrong-signed.
        obj = int(st.get("turretKills", 0) or 0) + int(st.get("inhibitorKills", 0) or 0)
        items = [int(st.get(f"item{j}", 0) or 0) for j in range(6)]
        parts.append({
            "puuid": pl.get("puuid", "") or "",
            "champ": dd["id2name"].get(int(p.get("championId") or 0), ""),
            "name": name,
            "win": bool(st.get("win")),
            "team": int(p.get("teamId", 0) or 0),
            "k": int(st.get("kills", 0) or 0), "d": int(st.get("deaths", 0) or 0),
            "a": int(st.get("assists", 0) or 0),
            "dmg": int(st.get("totalDamageDealtToChampions", 0) or 0),
            "gold": int(st.get("goldEarned", 0) or 0), "cs": cs,
            "vision": int(st.get("visionScore", 0) or 0),
            "obj": obj,
            "items": [i for i in items if i],
            "pos": _position(p.get("timeline")),
        })
    out = {"dur": int(g.get("gameDuration", 0) or 0), "parts": parts,
           "ts": int(g.get("gameCreation") or 0)}
    try:
        json.dump(out, open(fp, "w", encoding="utf-8"))
    except Exception:
        pass
    return out


if __name__ == "__main__":                      # manual check: python core/lollocal.py
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    dd = lb.ddragon()
    print("client up:", available(), "| me:", my_riot_id(), "| rank:", rank())
    ids = recent_game_ids(10)
    print(f"{len(ids)} ranked-solo games: {ids[:5]}")
    if ids:
        d = game_detail(dd, ids[0])
        me = next((p for p in d["parts"] if p["puuid"] == my_puuid()), None)
        print(f"newest: {len(d['parts'])} players, dur {d['dur']}s")
        if me:
            print(f"  you: {me['champ']} {me['pos']} {me['k']}/{me['d']}/{me['a']} "
                  f"cs={me['cs']} win={me['win']}")
