#!/usr/bin/env python3
"""lolgame.py — resolve the CURRENT game's champs/roles from whatever source is
live, so Win+B works in champ select, on the loading screen, AND in-game.

Priority (richest data first):
  1. LCU champ-select session   -> champ select (incl. post-lock 15s finalization)
  2. Live Client Data API :2999 -> in-game (champ names + teams + ranked roles)
  3. LCU gameflow session       -> loading screen (champ-select endpoint is dead)

Returns champ IDs uniformly: dict(my, pos, allies=[(cid,pos)], enemies=[cid],
phase, source) or (None, error_message). Role is cached per-champ so a
loading-screen press (gameflow exposes no role) can recover the role picked in
champ select / seen in-game.
"""
import os, json, base64, time, string, urllib.error
import lolbuild as lb  # reuse http(), ROLE, LOCKFILES, UA

ROLE = lb.ROLE
ROLECACHE = os.path.expanduser("~/.claude/cache/lolrole.json")


def _lockfile():
    lf = next((p for p in lb.LOCKFILES if os.path.exists(p)), None)
    if not lf:
        for d in string.ascii_uppercase:
            p = f"{d}:\\Riot Games\\League of Legends\\lockfile"
            if os.path.exists(p):
                lf = p
                break
    return lf


def _lcu():
    """(port, headers) for the local LCU, or None if the client isn't running."""
    lf = _lockfile()
    if not lf:
        return None
    try:
        _name, _pid, port, pw, _proto = open(lf).read().split(":")
    except Exception:
        return None
    auth = base64.b64encode(f"riot:{pw}".encode()).decode()
    hdr = {"Authorization": f"Basic {auth}", "Accept": "application/json", "User-Agent": lb.UA}
    return port, hdr


def save_role(cid, pos):
    if not (cid and pos):
        return
    try:
        os.makedirs(os.path.dirname(ROLECACHE), exist_ok=True)
        json.dump({"champ": cid, "pos": pos, "ts": time.time()}, open(ROLECACHE, "w"))
    except Exception:
        pass


def load_role(cid):
    try:
        d = json.load(open(ROLECACHE))
        if d.get("champ") == cid and time.time() - d.get("ts", 0) < 7200:
            return d.get("pos") or ""
    except Exception:
        pass
    return ""


def _cid(dd, name):
    return dd["name2id"].get(dd["norm"](name or "")) or 0


def _gname(s):
    return (s or "").split("#")[0].strip().lower()


# ---------- source 1: champ select ----------
def _from_champ_select(dd):
    lc = _lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        s = lb.http(f"https://127.0.0.1:{port}/lol-champ-select/v1/session",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None
    local = s.get("localPlayerCellId")
    mine = next((m for m in s.get("myTeam", []) if m.get("cellId") == local), None)
    if mine is None:
        return None
    my = mine.get("championId", 0) or mine.get("championPickIntent", 0)  # show hovered champ pre-lock
    pos = ROLE.get((mine.get("assignedPosition") or "").lower(), "")
    allies = [(m.get("championId", 0) or m.get("championPickIntent", 0),
               ROLE.get((m.get("assignedPosition") or "").lower(), ""))
              for m in s.get("myTeam", [])]
    enemies = [(e.get("championId", 0), ROLE.get((e.get("assignedPosition") or "").lower(), ""))
               for e in s.get("theirTeam", []) if e.get("championId", 0) > 0]
    if not my:
        return dict(my=0, pos=pos, allies=allies, enemies=enemies,
                    phase="ChampSelect", source="champ select", err="not_locked")
    save_role(my, pos)
    return dict(my=my, pos=pos, allies=allies, enemies=enemies,
                phase="ChampSelect", source="champ select")


# ---------- source 2: live client (in-game) ----------
def _from_live_client(dd):
    try:
        d = lb.http("https://127.0.0.1:2999/liveclientdata/allgamedata",
                    timeout=3, insecure=True)
    except Exception:
        return None
    players = d.get("allPlayers") or []
    if not players:
        return None
    ap = d.get("activePlayer") or {}
    me_name = ap.get("riotId") or ""
    if not me_name:
        gn = ap.get("riotIdGameName") or ap.get("summonerName") or ""
        tl = ap.get("riotIdTagLine") or ""
        me_name = f"{gn}#{tl}" if tl else gn
    myg = _gname(me_name)

    def pg(p):
        return _gname(p.get("riotId") or p.get("summonerName") or p.get("riotIdGameName", ""))

    me = next((p for p in players if pg(p) == myg), None) if myg else None
    if me is None:
        return None
    myteam = me.get("team")

    def pos_of(p):
        return ROLE.get((p.get("position") or "").lower(), "")

    my = _cid(dd, me.get("championName", ""))
    pos = pos_of(me) or load_role(my)
    allies = [(_cid(dd, p.get("championName", "")), pos_of(p))
              for p in players if p.get("team") == myteam]
    enemies = [(_cid(dd, p.get("championName", "")), pos_of(p))
               for p in players if p.get("team") != myteam and _cid(dd, p.get("championName", ""))]
    save_role(my, pos)
    return dict(my=my, pos=pos, allies=allies, enemies=enemies,
                phase="InProgress", source="live game")


# ---------- source 3: gameflow (loading screen) ----------
def _from_gameflow(dd):
    lc = _lcu()
    if not lc:
        return None
    port, hdr = lc
    try:
        s = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/session",
                    headers=hdr, timeout=4, insecure=True)
    except Exception:
        return None
    phase = s.get("phase", "") or ""
    gd = s.get("gameData") or {}
    t1, t2 = gd.get("teamOne") or [], gd.get("teamTwo") or []
    if not (t1 or t2):
        return None
    mypuuid = ""
    try:
        cs = lb.http(f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                     headers=hdr, timeout=4, insecure=True)
        mypuuid = cs.get("puuid", "")
    except Exception:
        pass
    myteam = other = None
    me = None
    for team, opp in ((t1, t2), (t2, t1)):
        for p in team:
            if mypuuid and p.get("puuid") == mypuuid:
                myteam, other, me = team, opp, p
                break
        if me:
            break
    if me is None:
        return None
    my = me.get("championId", 0)
    pos = load_role(my)  # gameflow exposes no role; recover from cache if we have it
    allies = [(p.get("championId", 0), "") for p in myteam]
    enemies = [(p.get("championId", 0), "") for p in other if p.get("championId", 0) > 0]
    if pos:
        save_role(my, pos)
    return dict(my=my, pos=pos, allies=allies, enemies=enemies,
                phase=phase or "Loading", source="loading screen")


def resolve(dd):
    """Return (info, None) or (None, error). Tries each source by phase priority."""
    info = _from_champ_select(dd)
    if info:
        if info.get("err") == "not_locked":
            return None, "In champ select but you haven't locked a champ yet."
        return info, None
    for fn in (_from_live_client, _from_gameflow):
        info = fn(dd)
        if info and info.get("my"):
            return info, None
    return None, ("No live game found — open champ select, or be on the loading "
                  "screen / in-game (all three work).")
