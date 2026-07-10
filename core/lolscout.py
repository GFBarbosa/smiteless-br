#!/usr/bin/env python3
"""lolscout.py — fresh per-player scouting via the Riot API (never stale, unlike
op.gg's cached profile). For every player in the current game it computes, from
their real recent ranked matches: account winrate over the last N games + their
winrate on the champ they're playing THIS game.

Data source for the roster: LCU gameflow session (gives puuid + championId for
all 10 players once a game is forming — loading screen / in-game). Enemies are
anonymized in champ select, so this is a loading/in-game feature.

Rate-limit aware (dev key: 100 req / 2 min, 20 req/s) and caches match results
permanently (a match never changes) so repeat presses are instant.

Usage:
  python lolscout.py                 # auto from the running client, print scout
  python lolscout.py --count 10      # last N games (default 10)
"""
import sys, os, json, time, hashlib, shutil, threading, urllib.request, urllib.error
import concurrent.futures as _futures

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))
import lolbuild as lb
import lolgame as lg

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REGIONAL = "americas"      # match-v5 + account-v1 (regional routing)
PLATFORM = "na1"           # summoner-v4 + league-v4 (platform routing)
CACHE = os.path.expanduser("~/.claude/cache/riot")
IDS_TTL = 600          # re-pull a player's match-id list at most every 10 min
RANK_TTL = 1800        # re-pull a player's rank at most every 30 min
MASTERY_ALL_TTL = 12 * 3600     # a whole account's mastery barely moves -> cache half a day
FAM_TTL = 6 * 3600              # rebuild the cross-account familiarity pool at most every 6h
ACCOUNTS_FILE = os.path.expanduser("~/.claude/smiteless_accounts.json")   # your main + smurfs
FAM_FILE = os.path.join(CACHE, "familiarity_lvl.json")                    # pooled mastery LEVEL cache
KEYOK_TTL = 300        # cache a key's validity ~5 min so each scout doesn't re-ping Riot
_CALLS = []            # sliding-window call timestamps for rate limiting
_CALLS_LOCK = threading.Lock()   # scouting runs the 10 players in parallel -> serialize the throttle
_KEYOK = {}            # key -> (ts, True/False); only definitive results are cached


def read_key():
    # Use the most-recently-modified key file, so a fresh update always wins even if the
    # two files (~/.riot_api_key and .txt) somehow got out of sync.
    existing = [p for p in (os.path.expanduser("~/.riot_api_key"),
                            os.path.expanduser("~/.riot_api_key.txt")) if os.path.exists(p)]
    if not existing:
        return None
    try:
        return open(max(existing, key=os.path.getmtime), encoding="utf-8").read().strip() or None
    except Exception:
        return None


def key_ok(key):
    """Quick key-validity check via lol-status on the PLATFORM host (na1), which is not
    Cloudflare-gated like the regional host. True = valid, False = genuinely rejected,
    None = couldn't tell (network). Lets us distinguish a bad key from a transient 403."""
    if not key:
        return False
    cached = _KEYOK.get(key)
    if cached and time.time() - cached[0] < KEYOK_TTL:
        return cached[1]
    url = f"https://{PLATFORM}.api.riotgames.com/lol/status/v4/platform-data"
    last = None
    for _ in range(2):
        req = urllib.request.Request(url, headers={"X-Riot-Token": key, "User-Agent": lb.UA,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                r.read()
            _KEYOK[key] = (time.time(), True)
            return True
        except urllib.error.HTTPError as e:
            last = (e.code in (401, 403))      # status host isn't Cloudflare-gated -> real auth result
        except Exception:
            last = None
    result = False if last else None
    if result is not None:                     # cache only definitive verdicts, not transient outages
        _KEYOK[key] = (time.time(), result)
    return result


def _throttle():
    # Personal key: match-v5 (the scout's bulk) allows 2000 req / 10 s. Stay under that
    # with margin; a 429 (handled in _get with Retry-After) is the backstop. Locked because
    # the scout dispatches all 10 players concurrently.
    with _CALLS_LOCK:
        now = time.time()
        while _CALLS and now - _CALLS[0] > 10:
            _CALLS.pop(0)
        if len(_CALLS) >= 1500:                 # under 2000 / 10s
            time.sleep(max(0.0, 10 - (now - _CALLS[0]) + 0.2))
        elif _CALLS and now - _CALLS[-1] < 0.008:   # ~125/s burst cap
            time.sleep(0.008)
        _CALLS.append(time.time())


class KeyStale(Exception):
    pass


_HDRS = {"User-Agent": lb.UA, "Accept": "application/json, text/plain, */*",
         "Accept-Language": "en-US,en;q=0.9"}      # look like a browser to dodge Cloudflare


def _get(url, key, timeout=8):
    headers = dict(_HDRS, **{"X-Riot-Token": key})
    for attempt in range(4):
        _throttle()
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:                       # rate limited -> wait (capped) + retry
                try:
                    ra = int(e.headers.get("Retry-After", "2"))
                except Exception:
                    ra = 2
                time.sleep(min(ra, 10) + 0.5)
                continue
            if e.code == 401:                       # 401 = definitively bad/expired key
                raise KeyStale()
            if e.code == 403:                       # almost always a TRANSIENT Cloudflare block on
                time.sleep(0.5 * (attempt + 1))     # the regional host (NOT a stale key) -> back off
                continue                            # and retry; if it never clears, skip this call
            return None
        except Exception:
            return None
    return None                                     # exhausted retries (e.g. persistent 403) -> skip


def forget_player(puuid, riot_id=None):
    """Drop the TTL'd caches for ONE player (match-id list + rank + mastery) so the next
    fetch is fresh - a just-finished game isn't in the 10-min ids cache or the 30-min rank
    cache yet, which is what made the profile look 'not updated'. Match data is immutable,
    so matchx/match stay cached (the new game re-fetches when its id appears)."""
    if not puuid:
        return
    for kind in ("ids", "idsall", "rank", "mastery"):   # files: {puuid}.json / {puuid}_{cid}.json
        d = os.path.join(CACHE, kind)
        try:
            for f in os.listdir(d):
                if f.startswith(puuid):
                    os.remove(os.path.join(d, f))
        except Exception:
            pass


def _cache_path(kind, name):
    d = os.path.join(CACHE, kind)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name + ".json")


def ensure_key_namespace(key):
    """Riot encrypts PUUIDs per API key (and match results embed those PUUIDs), so when
    the key changes the cached puuids/matches/ranks become undecryptable (HTTP 400). If
    the key's fingerprint changed since last time, wipe the key-specific caches so they
    re-fetch fresh under the new key."""
    h = hashlib.sha1((key or "").encode()).hexdigest()[:12]
    fp = os.path.join(CACHE, "_keyhash")
    old = ""
    try:
        old = open(fp).read().strip()
    except Exception:
        pass
    if old != h:
        # matchx/idsall too: profile match caches embed per-key-encrypted puuids, so under a
        # NEW key the "which one is me" lookup silently never matches -> empty match history
        # (bit anyone rotating daily dev keys).
        for sub in ("puuid", "ids", "idsall", "match", "matchx", "rank", "mastery"):
            shutil.rmtree(os.path.join(CACHE, sub), ignore_errors=True)
        try:
            os.makedirs(CACHE, exist_ok=True)
            open(fp, "w").write(h)
        except Exception:
            pass


def recent_ids(puuid, key, count, queue="ranked"):
    """Recent match ids. queue='ranked' (solo 420 - the scout's form read) or 'all'
    (every queue - the PROFILE's match history, so normals/flex players see games too;
    ARAM etc. get filtered later by match_detail's CLASSIC check)."""
    kind = "ids" if queue == "ranked" else "idsall"
    fp = _cache_path(kind, puuid)
    if os.path.exists(fp):
        try:
            c = json.load(open(fp))
            if time.time() - c.get("ts", 0) < IDS_TTL and len(c.get("ids", [])) >= count:
                return c["ids"][:count]
        except Exception:
            pass
    filt = "queue=420&type=ranked&" if queue == "ranked" else ""
    d = _get(f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
             f"{puuid}/ids?{filt}start=0&count={count}", key)
    if d is None:
        return []
    try:
        json.dump({"ids": d, "ts": time.time()}, open(fp, "w"))
    except Exception:
        pass
    return d


def match_results(mid, key):
    """{puuid: [win, champ, k, d, a, cs, dmg, vision, obj, team, pos]} for all 10 participants —
    the full per-player stat line lets callers judge SKILL from how someone actually plays (CS,
    kill participation, damage share, deaths, vision), not just their W/L. Same match fetch as
    before (no extra API cost), cached forever. Old cache entries hold a shorter list ([win,
    champ] or through KDA) and still read fine — every reader checks the length before indexing."""
    fp = _cache_path("match", mid)
    if os.path.exists(fp):
        try:
            return json.load(open(fp))
        except Exception:
            pass
    d = _get(f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{mid}", key)
    if not d or "info" not in d:
        return None
    res = {p["puuid"]: [
        bool(p["win"]), p.get("championName", ""),
        int(p.get("kills", 0)), int(p.get("deaths", 0)), int(p.get("assists", 0)),
        int(p.get("totalMinionsKilled", 0)) + int(p.get("neutralMinionsKilled", 0)),   # cs
        int(p.get("totalDamageDealtToChampions", 0)),                                  # dmg to champs
        int(p.get("visionScore", 0)),                                                  # vision
        (int(p.get("turretTakedowns", 0)) + int(p.get("dragonKills", 0))              # objective takedowns
         + int(p.get("baronKills", 0)) + int(p.get("riftHeraldTakedowns", 0))
         + int(p.get("inhibitorTakedowns", 0))),
        int(p.get("teamId", 0)),                                                       # team
        p.get("teamPosition", "") or p.get("individualPosition", ""),                  # role that game
    ] for p in d["info"]["participants"]}
    res["_q"] = d["info"].get("queueId", 0)      # queue id, so aggregates can filter SR-only
    res["_dur"] = int(d["info"].get("gameDuration", 0))   # seconds, for per-minute stats
    try:                                         # atomic write: two parallel scouts can share a match
        tmp = f"{fp}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w") as f:
            json.dump(res, f)
        os.replace(tmp, fp)
    except Exception:
        pass
    return res


def match_timeline(mid, key):
    """Match-v5 TIMELINE distilled to a compact, cache-friendly shape (per-minute gold/cs/xp
    for all 10 + every champion kill), cached forever. {pids, mins, deaths} or None. pids is the
    puuid list in participantId order (index 0 = pid 1); mins[i][pid] = {g, cs, xp}."""
    fp = _cache_path("timeline", mid)
    if os.path.exists(fp):
        try:
            return json.load(open(fp))
        except Exception:
            pass
    d = _get(f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{mid}/timeline", key)
    if not d or "info" not in d:
        return None
    mins, deaths = [], []
    for fr in d["info"].get("frames", []):
        pf = fr.get("participantFrames") or {}
        row = {}
        for pid in range(1, 11):
            p = pf.get(str(pid)) or {}
            row[str(pid)] = {"g": p.get("totalGold", 0) or 0,
                             "cs": (p.get("minionsKilled", 0) or 0) + (p.get("jungleMinionsKilled", 0) or 0),
                             "xp": p.get("xp", 0) or 0}
        mins.append(row)
        for e in (fr.get("events") or []):
            if e.get("type") == "CHAMPION_KILL":
                deaths.append({"v": e.get("victimId"), "k": e.get("killerId"),
                               "t": int((e.get("timestamp") or 0) / 1000)})
    out = {"pids": (d.get("metadata") or {}).get("participants", []), "mins": mins, "deaths": deaths}
    try:
        json.dump(out, open(fp, "w"))
    except Exception:
        pass
    return out


def rank(puuid, key):
    """Solo-queue rank (league-v4 by-puuid), cached ~30 min since it drifts. Returns
    {tier, div, lp, w, l} or None (unranked / lookup failed)."""
    fp = _cache_path("rank", puuid)
    if os.path.exists(fp):
        try:
            c = json.load(open(fp))
            if time.time() - c.get("ts", 0) < RANK_TTL:
                return c.get("rank")
        except Exception:
            pass
    d = _get(f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}", key)
    r = None
    if isinstance(d, list):
        solo = next((e for e in d if e.get("queueType") == "RANKED_SOLO_5x5"), None)
        if solo:
            r = {"tier": solo.get("tier", ""), "div": solo.get("rank", ""),
                 "lp": solo.get("leaguePoints", 0), "w": solo.get("wins", 0), "l": solo.get("losses", 0)}
    try:
        json.dump({"rank": r, "ts": time.time()}, open(fp, "w"))
    except Exception:
        pass
    return r


def mastery(puuid, champ_id, key):
    """Champion mastery on the champ they're playing THIS game (champion-mastery-v4),
    cached ~30 min. Returns {level, points} or None (no mastery entry = effectively a
    first-timer, or lookup failed)."""
    if not champ_id:
        return None
    fp = _cache_path("mastery", f"{puuid}_{champ_id}")
    if os.path.exists(fp):
        try:
            c = json.load(open(fp))
            if time.time() - c.get("ts", 0) < RANK_TTL:
                return c.get("m")
        except Exception:
            pass
    d = _get(f"https://{PLATFORM}.api.riotgames.com/lol/champion-mastery/v4/"
             f"champion-masteries/by-puuid/{puuid}/by-champion/{champ_id}", key)
    m = None
    if isinstance(d, dict) and "championPoints" in d:
        m = {"level": d.get("championLevel", 0), "points": d.get("championPoints", 0)}
    try:
        json.dump({"m": m, "ts": time.time()}, open(fp, "w"))
    except Exception:
        pass
    return m


def all_mastery(puuid, key):
    """{championId: masteryLevel} for a puuid — ALL champs in one champion-mastery-v4 call,
    cached ~12h (mastery barely moves). {} on failure. Level (not points) so callers can gate
    suggestions on 'mastery 5+'. Cache kind 'masterylvl' so it never mixes with old point caches."""
    if not puuid:
        return {}
    fp = _cache_path("masterylvl", puuid)
    try:
        c = json.load(open(fp))
        if time.time() - c.get("ts", 0) < MASTERY_ALL_TTL:
            return {int(k): v for k, v in c.get("m", {}).items()}
    except Exception:
        pass
    d = _get(f"https://{PLATFORM}.api.riotgames.com/lol/champion-mastery/v4/"
             f"champion-masteries/by-puuid/{puuid}", key)
    out = {}
    if isinstance(d, list):
        for r in d:
            cid = r.get("championId")
            if cid:
                out[int(cid)] = r.get("championLevel", 0) or 0
    try:
        json.dump({"m": out, "ts": time.time()}, open(fp, "w"))
    except Exception:
        pass
    return out


# ---------- the user's accounts (main + smurfs) ----------
# Auto-remembered as each logs into the client, plus manual adds from Settings. Used to pool
# champion mastery across accounts so "familiar champ" means familiar on ANY of them.
def _norm_rid(rid):
    return (rid or "").strip().lower()


def load_accounts():
    """[{riot_id, source, ts}] — the user's known accounts."""
    try:
        d = json.load(open(ACCOUNTS_FILE, encoding="utf-8"))
        out = []
        for a in d.get("accounts", []):
            rid = (a.get("riot_id") or "").strip()
            if rid and "#" in rid:
                out.append({"riot_id": rid, "source": a.get("source", "auto"), "ts": a.get("ts", 0)})
        return out
    except Exception:
        return []


def _write_accounts(accts):
    try:
        os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
        tmp = f"{ACCOUNTS_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"accounts": accts}, f, indent=2)
        os.replace(tmp, ACCOUNTS_FILE)
    except Exception:
        pass


def remember_account(riot_id, source="auto"):
    """Record an account we've seen logged in (or a manual add). Returns True if newly added
    (in which case the familiarity aggregate is invalidated so it re-pools with this account)."""
    riot_id = (riot_id or "").strip()
    if not riot_id or "#" not in riot_id:
        return False
    accts = load_accounts()
    if any(_norm_rid(a["riot_id"]) == _norm_rid(riot_id) for a in accts):
        return False
    accts.append({"riot_id": riot_id, "source": source, "ts": int(time.time())})
    _write_accounts(accts)
    invalidate_familiarity()
    return True


def save_accounts(riot_ids):
    """Replace the account list from Settings (dedup, keep order). Preserves the source/ts of
    accounts already known; new lines are tagged 'manual'. Invalidates the familiarity cache."""
    prev = {_norm_rid(a["riot_id"]): a for a in load_accounts()}
    out, seen = [], set()
    for rid in riot_ids:
        rid = (rid or "").strip()
        k = _norm_rid(rid)
        if not rid or "#" not in rid or k in seen:
            continue
        seen.add(k)
        old = prev.get(k)
        out.append({"riot_id": rid, "source": (old or {}).get("source", "manual"),
                    "ts": (old or {}).get("ts", int(time.time()))})
    _write_accounts(out)
    invalidate_familiarity()
    return out


# ---------- pooled familiarity (max mastery per champ across all accounts) ----------
_FAM = {"ts": 0.0, "data": {}, "busy": False}


def invalidate_familiarity():
    _FAM["ts"] = 0.0
    _FAM["data"] = {}
    try:
        os.remove(FAM_FILE)
    except Exception:
        pass


def _compute_familiarity():
    try:
        key = read_key()
        agg = {}
        if key:
            for a in load_accounts():
                pu = resolve_puuid(a["riot_id"], key)
                if not pu:
                    continue
                for cid, pts in all_mastery(pu, key).items():
                    if pts > agg.get(cid, 0):
                        agg[cid] = pts
        if agg:
            _FAM["data"] = agg
            _FAM["ts"] = time.time()
            try:
                os.makedirs(CACHE, exist_ok=True)
                json.dump({"m": agg, "ts": _FAM["ts"]}, open(FAM_FILE, "w"))
            except Exception:
                pass
    finally:
        _FAM["busy"] = False


def familiarity(base=None):
    """Best-available {championId: masteryPoints} pooled across the user's accounts, merged
    (max) with `base` (the live current-account mastery from the LCU). NON-BLOCKING: returns
    the cached aggregate immediately and refreshes it in the background when stale, so it
    never stalls a champ-select render. Falls back to just `base` before the pool is built."""
    if not _FAM["data"]:
        try:
            c = json.load(open(FAM_FILE))
            _FAM["data"] = {int(k): v for k, v in c.get("m", {}).items()}
            _FAM["ts"] = c.get("ts", 0)
        except Exception:
            pass
    if not _FAM["busy"] and time.time() - _FAM["ts"] > FAM_TTL:
        import threading
        _FAM["busy"] = True
        threading.Thread(target=_compute_familiarity, daemon=True).start()
    merged = dict(_FAM["data"])
    for cid, pts in (base or {}).items():
        if pts and pts > merged.get(cid, 0):
            merged[cid] = pts
    return merged


def _part(rec):
    """A rich match_results row (list) -> the participant dict that _grade_game reads."""
    return {"win": rec[0], "k": rec[2], "d": rec[3], "a": rec[4], "cs": rec[5],
            "dmg": rec[6], "vision": rec[7], "obj": rec[8], "team": rec[9], "pos": rec[10]}


def scout(dd, puuid, champ_id, key, count):
    """Return (games, wins, champ_games, champ_wins, form, match_ids, kda, perf) over the last
    `count` ranked. `form` is a list of bool (True=win) in recent-first order. `kda` pools this
    player's recent kills/deaths/assists ({g, k, d, a}). `perf` is the average per-game
    PERFORMANCE score (how well they actually played vs their role's benchmarks — CS, kill
    participation, damage share, deaths, vision), or None if no detailed matches were cached
    yet. perf is the skill read that survives a bad-luck losing streak on off-champs — it grades
    how you play, not whether you won. match_ids drives duo detection."""
    import lolprofile as lp                        # lazy: lolprofile imports us (avoid a cycle)
    ids = recent_ids(puuid, key, count)
    n = w = cg = cw = 0
    form = []
    tk = td = ta = kg = 0                          # KDA totals + games that carried KDA data
    perfs = []
    for mid in ids:
        res = match_results(mid, key)
        if not res or puuid not in res:
            continue
        rec = res[puuid]
        win, cname = rec[0], rec[1]
        n += 1
        w += 1 if win else 0
        form.append(bool(win))
        if len(rec) >= 5:                          # new-format cache carries KDA
            tk += rec[2]; td += rec[3]; ta += rec[4]; kg += 1
        if len(rec) >= 11:                         # full stat line -> grade how they PLAYED
            parts = [_part(v) for v in res.values() if isinstance(v, list) and len(v) >= 11]
            try:
                s, _lt, _lb = lp._grade_game(parts, _part(rec), res.get("_dur", 0))
                perfs.append(s)
            except Exception:
                pass
        if dd["name2id"].get(dd["norm"](cname)) == champ_id:
            cg += 1
            cw += 1 if win else 0
    perf = round(sum(perfs) / len(perfs), 1) if perfs else None
    return n, w, cg, cw, form, ids, {"g": kg, "k": tk, "d": td, "a": ta}, perf


def _safe(s):
    return "".join(c if c.isalnum() else "_" for c in s)


def resolve_puuid(riot_id, key):
    """riotId 'Name#TAG' -> encrypted Match-V5 puuid (cached permanently; ids are stable)."""
    if not riot_id or "#" not in riot_id:
        return None
    fp = _cache_path("puuid", _safe(riot_id))
    if os.path.exists(fp):
        try:
            return json.load(open(fp))
        except Exception:
            pass
    import urllib.parse
    name, tag = riot_id.rsplit("#", 1)
    d = _get(f"https://{REGIONAL}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
             f"{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}", key)
    if isinstance(d, dict) and d.get("puuid"):
        try:
            json.dump(d["puuid"], open(fp, "w"))
        except Exception:
            pass
        return d["puuid"]
    return None


def _prune_match_cache(cap=4000):
    """Cap the permanent match cache (a match never changes, so it grows forever).
    Keeps the most-recently-used `cap` files, drops the oldest."""
    d = os.path.join(CACHE, "match")
    try:
        files = [os.path.join(d, f) for f in os.listdir(d)]
    except Exception:
        return
    if len(files) <= cap:
        return
    files.sort(key=lambda f: os.path.getmtime(f))
    for f in files[:len(files) - cap]:
        try:
            os.remove(f)
        except Exception:
            pass


def roster(dd, key):
    """[(puuid, champ_id, role, is_ally, is_me, riot_id)] for all 10. Primary source is
    the Live Client API (in-game): it exposes riotIds we can resolve to real puuids (and
    use to open op.gg). The gameflow session hands back placeholder UUIDs that Match-V5
    rejects, so we only use it if it happens to carry encrypted (78-char) puuids."""
    # --- primary: live client (in-game) ---
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata", timeout=3, insecure=True)
    except Exception:
        d = None
    if d and d.get("allPlayers"):
        players = d["allPlayers"]
        ap = d.get("activePlayer") or {}
        me_name = ap.get("riotId") or ""
        if not me_name:
            gn, tl = ap.get("riotIdGameName", ""), ap.get("riotIdTagLine", "")
            me_name = f"{gn}#{tl}" if tl else gn
        myg = lg._gname(me_name)
        rid = lambda p: p.get("riotId") or p.get("summonerName") or ""
        me = next((p for p in players if lg._gname(rid(p)) == myg), None)
        myteam = me.get("team") if me else "ORDER"   # spectator/replay (no active player): ORDER = "ally" side
        out = []
        for p in players:
            puuid = resolve_puuid(rid(p), key)
            if not puuid:
                continue
            cid = dd["name2id"].get(dd["norm"](p.get("championName", ""))) or 0
            role = lb.ROLE.get((p.get("position") or "").lower(), "")
            out.append((puuid, cid, role, p.get("team") == myteam, p is me, rid(p)))
        if out:
            return out, None
    # --- fallback: gameflow, ONLY if it carries real (encrypted) puuids ---
    lc = lg._lcu()
    if lc:
        port, hdr = lc
        try:
            s = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/session",
                        headers=hdr, timeout=4, insecure=True)
            gd = s.get("gameData") or {}
            t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
            allp = [p for p in t1 + t2 if p.get("puuid")]
            if allp and all(len(p["puuid"]) > 70 for p in allp):  # encrypted puuids
                mypuuid = ""
                try:
                    mypuuid = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                                      headers=hdr, timeout=4, insecure=True).get("puuid", "")
                except Exception:
                    pass
                mine = t1 if any(p.get("puuid") == mypuuid for p in t1) else t2
                out = []
                for team in (mine, t2 if mine is t1 else t1):
                    for p in team:
                        if p.get("puuid"):
                            out.append((p["puuid"], p.get("championId", 0), "",
                                        team is mine, p.get("puuid") == mypuuid, ""))
                return out, None
        except Exception:
            pass
    return None, ("Scouting needs the live game running (be in-game) - the loading "
                  "screen only exposes placeholder IDs that can't be looked up.")


def fmt_row(dd, champ_id, is_ally, is_me, n, w, cg, cw):
    champ = dd["id2name"].get(champ_id, str(champ_id))
    side = "YOU  " if is_me else ("ALLY " if is_ally else "ENEMY")
    if n:
        acct = f"{w}-{n - w} ({w / n * 100:.0f}%)"
    else:
        acct = "no recent ranked"
    if cg:
        champ_wr = f"{cw}-{cg - cw} ({cw / cg * 100:.0f}%) on {champ}"
    else:
        champ_wr = f"{champ}: not in last games"
    return f"{side} {champ:13} last{n}: {acct:15} | {champ_wr}"


def iter_scout_struct(dd, count=10):
    """Yield structured per-player dicts as each resolves (drives the image renderer):
    {cid, role, is_ally, is_me, n, w, cg, cw, form} — or a single {'error': ...}."""
    key = read_key()
    if not key:
        yield {"error": "No Riot API key file (~/.riot_api_key)."}
        return
    if key_ok(key) is False:             # confirmed bad key (via the non-Cloudflare status host)
        yield {"error": "Riot key rejected (401/403) - open the overlay key bar (Get key) to update it."}
        return
    ensure_key_namespace(key)            # key changed? -> drop the old key's undecryptable cache
    _prune_match_cache()                  # keep the permanent match cache bounded
    # Everything network-y is inside the try: roster() (puuid resolution) can also raise
    # KeyStale, and the scout must NEVER crash its caller - a bad key/outage just means
    # "no scout this game", not a dead overlay.
    try:
        players, err = roster(dd, key)
        if err:
            yield {"error": err}
            return
        players.sort(key=lambda x: (not x[3], x[4]))   # allies first, enemies last (x[3]=is_ally)

        def _one(p):
            puuid, cid, role, is_ally, is_me, riot_id = p
            n, w, cg, cw, form, mids, kda, perf = scout(dd, puuid, cid, key, count)
            return {"cid": cid, "role": role, "is_ally": is_ally, "is_me": is_me,
                    "n": n, "w": w, "cg": cg, "cw": cw, "form": form, "riot_id": riot_id,
                    "rank": rank(puuid, key), "mastery": mastery(puuid, cid, key),
                    "mids": mids, "kda": kda, "perf": perf}

        # Scout all 10 AT ONCE. The scout is latency-bound (each player = ~N match fetches), so
        # running them concurrently fills the board in ~one player's time instead of ten. The
        # throttle lock keeps us within the rate limit; results stream back as each finishes.
        with _futures.ThreadPoolExecutor(max_workers=min(10, len(players)) or 1) as ex:
            futs = [ex.submit(_one, p) for p in players]
            for fut in _futures.as_completed(futs):
                try:
                    yield fut.result()
                except KeyStale:
                    yield {"error": "Riot key rejected - open the overlay key bar (Get key) to update it."}
                    return
                except Exception:
                    continue                           # one player failed -> skip, keep the rest
    except KeyStale:
        yield {"error": "Riot key rejected - open the overlay key bar (Get key) to update it."}
    except Exception as e:
        yield {"error": f"player scout unavailable ({type(e).__name__})"}


def iter_scout(dd, count=10):
    """Yield ('header'|'row'|'error', text) progressively so callers can stream it."""
    header_done = False
    for r in iter_scout_struct(dd, count):
        if "error" in r:
            yield ("error", r["error"])
            return
        if not header_done:
            yield ("header", f"PLAYER SCOUT (Riot API, live - last {count} ranked each):")
            header_done = True
        yield ("row", fmt_row(dd, r["cid"], r["is_ally"], r["is_me"],
                              r["n"], r["w"], r["cg"], r["cw"]))


def _takeflag(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        v = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
        return v
    return default


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)
    os.replace(tmp, path)


def _touch(path):
    if path:
        try:
            open(path, "w").close()
        except Exception:
            pass


def main():
    argv = sys.argv[1:]
    outp = _takeflag(argv, "--out")
    fm = _takeflag(argv, "--fm")
    try:
        count = int(_takeflag(argv, "--count", "10"))
    except Exception:
        count = 10
    dd = lb.ddragon()
    if outp:                                  # file mode: stream rows as they resolve
        lines = []
        for _kind, text in iter_scout(dd, count):
            lines.append(text)
            _write(outp, "\n".join(lines))
        _touch(fm)
    else:                                     # console mode
        t0 = time.time()
        for _kind, text in iter_scout(dd, count):
            print(text)
        print(f"\n(scouted in {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
