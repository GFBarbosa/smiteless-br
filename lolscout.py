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
import sys, os, json, time, hashlib, shutil, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
_CALLS = []            # sliding-window call timestamps for rate limiting


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
    url = f"https://{PLATFORM}.api.riotgames.com/lol/status/v4/platform-data"
    last = None
    for _ in range(2):
        req = urllib.request.Request(url, headers={"X-Riot-Token": key, "User-Agent": lb.UA,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                r.read()
            return True
        except urllib.error.HTTPError as e:
            last = (e.code in (401, 403))      # status host isn't Cloudflare-gated -> real auth result
        except Exception:
            last = None
    return False if last else None


def _throttle():
    # Personal key: match-v5 (the scout's bulk) allows 2000 req / 10 s. Stay under that
    # with margin; a 429 (handled in _get with Retry-After) is the backstop.
    now = time.time()
    while _CALLS and now - _CALLS[0] > 10:
        _CALLS.pop(0)
    if len(_CALLS) >= 1500:                     # under 2000 / 10s
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
        for sub in ("puuid", "ids", "match", "rank", "mastery"):
            shutil.rmtree(os.path.join(CACHE, sub), ignore_errors=True)
        try:
            os.makedirs(CACHE, exist_ok=True)
            open(fp, "w").write(h)
        except Exception:
            pass


def recent_ids(puuid, key, count):
    fp = _cache_path("ids", puuid)
    if os.path.exists(fp):
        try:
            c = json.load(open(fp))
            if time.time() - c.get("ts", 0) < IDS_TTL and len(c.get("ids", [])) >= count:
                return c["ids"][:count]
        except Exception:
            pass
    d = _get(f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/by-puuid/"
             f"{puuid}/ids?queue=420&type=ranked&start=0&count={count}", key)
    if d is None:
        return []
    try:
        json.dump({"ids": d, "ts": time.time()}, open(fp, "w"))
    except Exception:
        pass
    return d


def match_results(mid, key):
    """{puuid: [win, championName]} for all 10 participants. Cached forever."""
    fp = _cache_path("match", mid)
    if os.path.exists(fp):
        try:
            return json.load(open(fp))
        except Exception:
            pass
    d = _get(f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{mid}", key)
    if not d or "info" not in d:
        return None
    res = {p["puuid"]: [bool(p["win"]), p.get("championName", "")]
           for p in d["info"]["participants"]}
    try:
        json.dump(res, open(fp, "w"))
    except Exception:
        pass
    return res


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


def scout(dd, puuid, champ_id, key, count):
    """Return (games, wins, champ_games, champ_wins, form) over the last `count`
    ranked. `form` is a list of bool (True=win) in recent-first order."""
    ids = recent_ids(puuid, key, count)
    n = w = cg = cw = 0
    form = []
    for mid in ids:
        res = match_results(mid, key)
        if not res or puuid not in res:
            continue
        win, cname = res[puuid]
        n += 1
        w += 1 if win else 0
        form.append(bool(win))
        if dd["name2id"].get(dd["norm"](cname)) == champ_id:
            cg += 1
            cw += 1 if win else 0
    return n, w, cg, cw, form


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
        myteam = me.get("team") if me else None
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
        players.sort(key=lambda x: (x[3], x[4]))  # (puuid,cid,role,is_ally,is_me,riot_id): enemies first, you last
        for puuid, cid, role, is_ally, is_me, riot_id in players:
            n, w, cg, cw, form = scout(dd, puuid, cid, key, count)
            yield {"cid": cid, "role": role, "is_ally": is_ally, "is_me": is_me,
                   "n": n, "w": w, "cg": cg, "cw": cw, "form": form, "riot_id": riot_id,
                   "rank": rank(puuid, key), "mastery": mastery(puuid, cid, key)}
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
