#!/usr/bin/env python3
"""lolugg.py — u.gg match-history FALLBACK for the scout.

Riot's Match-V5 API lives on the regional host (americas.api.riotgames.com), which
Cloudflare-blocks or rate-limits often enough that the scout sometimes sees ZERO recent
games for a player who very much has them — the loading board then reads "no recent
ranked" for the whole lobby. u.gg runs its own match indexer, so when Riot's history
call comes back empty we ask u.gg for the same recent ranked games (champ, W/L, KDA,
role, match id, a carry score) and normalize them to the EXACT shape lolscout.scout()
builds from Riot data. So the pipeline is: try Riot first, fall back to u.gg.

Best-effort and defensive by construction: any network / shape hiccup returns [] and the
scout simply behaves as if there were no games (identical to a Riot miss), never raising
into its caller. Solo-queue only, to mirror the scout's queue=420 focus.

Endpoint + response shape verified live against u.gg's public GraphQL API
(POST https://u.gg/api) — see docs / the getPlayerMatchSummaries operation.
"""
import os, json, time, urllib.request, urllib.error

API = "https://u.gg/api"
REGION_DEFAULT = "na1"
CACHE = os.path.expanduser("~/.claude/cache/ugg")
TTL = 600                      # cache a player's pull ~10 min (matches Riot's ids-list TTL)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

# u.gg's seasonIds filter is REQUIRED and season-scoped. Pass a wide recent range so a
# season/split rollover never silently blanks the fallback — u.gg ignores ids that don't
# exist (verified: a bogus id returns 0 matches, not an error), so an over-broad range is safe.
SEASON_IDS = list(range(18, 45))

# u.gg role ints -> Riot teamPosition strings (what match_results/_main_pos already speak).
# Anchored on two clean reads from live data: Tristana games came back role=4 (ADC/bottom)
# and a support one-trick's games came back role=5 (utility); 1-3 fill in top/jungle/mid.
# Role only feeds the secondary off-role tag, so a rare misread here is low-stakes.
_ROLE = {1: "TOP", 2: "JUNGLE", 3: "MIDDLE", 4: "BOTTOM", 5: "UTILITY"}
_RANKED_SOLO = "ranked_solo_5x5"

_QUERY = (
    "query getPlayerMatchSummaries($riotUserName: String!, $riotTagLine: String!, "
    "$regionId: String!, $seasonIds: [Int!]!, $page: Int) {"
    "  fetchPlayerMatchSummaries(riotUserName: $riotUserName, riotTagLine: $riotTagLine, "
    "regionId: $regionId, seasonIds: $seasonIds, page: $page) {"
    "    totalNumMatches"
    "    matchSummaries { championId kills deaths assists win role queueType matchId "
    "psHardCarry psTeamPlay }"
    "  }"
    "}"
)

# hits/misses so a diagnostic can tell whether the fallback ever actually fired
_STATS = {"hit": 0, "miss": 0, "err": 0}


def _platform(region):
    """u.gg matchId is the raw Riot gameId; Riot match ids are '{PLATFORM}_{gameId}'. Rebuild
    that prefix so a u.gg-sourced match id lines up with a Riot-sourced one for the same game
    (keeps duo detection working even when one player came from Riot and the other from u.gg)."""
    return (region or REGION_DEFAULT).upper()


def _cache_path(riot_id, region):
    os.makedirs(CACHE, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in f"{region}_{riot_id}")
    return os.path.join(CACHE, safe + ".json")


def _post(riot_id, region, timeout):
    name, _, tag = (riot_id or "").partition("#")
    if not (name and tag):
        return None
    payload = json.dumps({
        "operationName": "getPlayerMatchSummaries",
        "query": _QUERY,
        "variables": {"riotUserName": name, "riotTagLine": tag, "regionId": region,
                      "seasonIds": SEASON_IDS, "page": 1},
    }).encode("utf-8")
    req = urllib.request.Request(API, data=payload, headers={
        "User-Agent": UA, "Content-Type": "application/json",
        "Accept": "application/json", "Origin": "https://u.gg", "Referer": "https://u.gg/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def recent_matches(riot_id, count=10, region=REGION_DEFAULT, ranked_only=True, timeout=8):
    """Recent games for a 'Name#TAG' from u.gg, most-recent-first, normalized to:
      [{champ_id, win, k, d, a, pos, match_id, perf}]
    `match_id` is Riot-formatted ('NA1_<gameId>') so it de-dupes against Riot ids. `perf` is
    u.gg's own hard-carry score (0-100+), a stand-in for our per-game grade on this path.
    Returns [] on ANY failure — the caller treats that exactly like 'no recent games'."""
    region = region or REGION_DEFAULT
    fp = _cache_path(riot_id, region)
    try:                                     # serve a fresh cache without hitting the network
        c = json.load(open(fp, encoding="utf-8"))
        if time.time() - c.get("ts", 0) < TTL and c.get("rows"):
            return c["rows"][:count]
    except Exception:
        pass
    try:
        j = _post(riot_id, region, timeout)
    except Exception:
        _STATS["err"] += 1
        try:                                 # stale-but-present cache beats nothing on an outage
            return json.load(open(fp, encoding="utf-8")).get("rows", [])[:count]
        except Exception:
            return []
    ms = (((j or {}).get("data") or {}).get("fetchPlayerMatchSummaries") or {}).get("matchSummaries") or []
    plat = _platform(region)
    out = []
    for m in ms:
        if ranked_only and m.get("queueType") != _RANKED_SOLO:
            continue
        cid = m.get("championId")
        mid = m.get("matchId")
        if not cid or not mid:
            continue
        out.append({
            "champ_id": int(cid), "win": bool(m.get("win")),
            "k": int(m.get("kills", 0)), "d": int(m.get("deaths", 0)), "a": int(m.get("assists", 0)),
            "pos": _ROLE.get(m.get("role"), ""), "match_id": f"{plat}_{mid}",
            "perf": m.get("psHardCarry"),
        })
        if len(out) >= count:
            break
    if out:
        _STATS["hit"] += 1
        try:
            tmp = f"{fp}.{os.getpid()}.tmp"
            json.dump({"rows": out, "ts": time.time()}, open(tmp, "w"))
            os.replace(tmp, fp)
        except Exception:
            pass
    else:
        _STATS["miss"] += 1
    return out[:count]


if __name__ == "__main__":                   # quick manual check: python lolugg.py "Name#TAG"
    import sys
    rid = sys.argv[1] if len(sys.argv) > 1 else "Ablazeolive#NA1"
    rows = recent_matches(rid, count=10)
    print(f"{rid}: {len(rows)} games  stats={_STATS}")
    for r in rows:
        print(f"  champ {r['champ_id']:>4}  {'W' if r['win'] else 'L'}  "
              f"{r['k']}/{r['d']}/{r['a']}  {r['pos']:<8} {r['match_id']}  perf={r['perf']}")
